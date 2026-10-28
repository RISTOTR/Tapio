"""Synchronous verification/reporting for the fixed local human-write pilot only."""

import json
import threading
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Transaction
from tapio.confirmation.replay import replay_confirmations
from tapio.knowledge.models import KnowledgeEvent, canonical, digest
from tapio.knowledge.store import load_bundle, save_bundle


class ControlledPilot:
    def __init__(
        self,
        service,
        root=Path("data/interim/controlled_confirmation"),
        base_root=Path("data/interim/full_csv_confirmation"),
    ):
        self.service = service
        self.root = root
        self.base_root = base_root
        self.lock = threading.RLock()

    def write(self, name, value):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Append-only attempts; derived report is atomically replaceable.
        if name.startswith("attempts/"):
            if path.exists():
                return
            with path.open("x") as out:
                path.chmod(0o600)
                out.write(canonical(value))
        else:
            temporary = path.with_suffix(".tmp")
            temporary.write_text(canonical(value))
            temporary.chmod(0o600)
            temporary.replace(path)

    def attempts(self):
        return [json.loads(p.read_text()) for p in sorted((self.root / "attempts").glob("*.json"))]

    def skipped(self, card_id):
        return any(a.get("card_id") == card_id and a["action"] == "SKIP" for a in self.attempts())

    def block(self):
        self.write("blocked.json", {"reason": "POST_WRITE_VERIFICATION_REQUIRED"})

    def preflight(self):
        if (self.root / "blocked.json").exists():
            raise ValueError("CONTROLLED_PILOT_VERIFICATION_REQUIRED")
        self.verify_sources()

    def verify_sources(self):
        from tapio.pilot.config import load_config, readonly_engine, source_fingerprints

        config, _ = load_config()
        engine = readonly_engine()
        try:
            return source_fingerprints(engine, config)
        finally:
            engine.dispose()

    def record_stale(self):
        self.write(
            "attempts/" + uuid4().hex + ".json",
            {
                "action": "STALE",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def after(self, request, browser_session, result):
        from tapio.confirmation.service import Commit

        payload = self.service.verify(Commit.model_validate(request).token, browser_session)
        selection = payload["selection"]
        # The revision itself is the authoritative CONFIRM/CHANGE record, even if
        # the process stopped after database commit and before this report.
        if result["status"] == "SKIPPED":
            self.write(
                "attempts/" + digest(payload["nonce"]) + ".json",
                {
                    "action": "SKIP",
                    "batch_id": self.service.batch.get("batch_id", "FIXED_FIVE"),
                    "card_id": selection["card_id"],
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        report = self.refresh()
        return {
            **result,
            "verification": {
                "source_transactions_unchanged": True,
                "legacy_review_rows_unchanged": True,
                "unrelated_rows_changed": 0,
                "audit_records": report["audit_records"],
                "knowledge_events": report["knowledge_events"],
                "knowledge_replay": "VERIFIED",
            },
        }

    def refresh(self):
        from tapio.confirmation.service import review_state, row_data

        fingerprints = self.verify_sources()
        cards = self.service.cards
        allowed = {c["transaction"]["id"]: c for c in cards.values()}
        with self.service.factory() as db:
            revisions = [row_data(r) for r in db.scalars(select(ConfirmationRevision))]
            baseline = self.service.batch.get("baseline_revisions", {})
            actual = {r["id"]: digest(r) for r in revisions}
            if any(actual.get(rid) != h for rid, h in baseline.items()):
                raise ValueError("HISTORICAL_REVISION_CHANGED")
            revisions = [r for r in revisions if r["id"] not in baseline]
            if any(r["transaction_id"] not in allowed for r in revisions):
                raise ValueError("UNRELATED_CONFIRMATION_REVISION")
            for r in revisions:
                card = allowed[r["transaction_id"]]
                event = KnowledgeEvent.model_validate(r["knowledge_event"])
                assert r["audit"]["card_id"] == card["card_id"]
                assert r["audit"]["knowledge_event_ids"] == [digest(event)]
                assert r["audit"]["new_values"] == r["state"]
                assert r["audit"]["user_selected_values"] == r["fields"]
                assert len(event.claims) == len(r["fields"])
                for field, value in r["fields"].items():
                    predicate = (
                        "confirmed_category"
                        if field == "category"
                        else "confirmed_business_context"
                    )
                    assert any(c.predicate == predicate and c.value == value for c in event.claims)
                tx = db.get(Transaction, r["transaction_id"])
                assert digest(row_data(tx)) == card["source_hash"]
                _, _, latest = review_state(db, tx)
                assert latest is not None
        base_root = self.base_root
        diff = json.loads((base_root / "knowledge_diff.json").read_text())
        base_path = base_root / "knowledge" / ("snapshot-" + diff["new_events_hash"] + ".json")
        base = load_bundle(base_path)
        base_events = [
            KnowledgeEvent.model_validate(e)
            for e in json.loads(
                base_path.with_name("events-" + base.events_hash + ".json").read_text()
            )
        ]
        merchants = {tx: c["transaction"]["merchant"] for tx, c in allowed.items()}
        snapshot, events = replay_confirmations(base_events, revisions, merchants)
        assert save_bundle(self.root / "knowledge", events) == snapshot
        old_ids, new_ids = {i.id for i in base.items}, {i.id for i in snapshot.items}
        counts = Counter(r["action"] for r in revisions)
        skips = {a["card_id"] for a in self.attempts() if a["action"] == "SKIP"}
        reviewed = {r["audit"]["card_id"] for r in revisions} | skips
        statuses = {cid: self.service.card_status(cid) for cid in cards}
        report = {
            "phase": "HUMAN_REVIEW_COMPLETE"
            if len(reviewed) == len(cards)
            else "AWAITING_HUMAN_REVIEW",
            "batch_hash": self.service.batch["cards_hash"],
            "batch_id": self.service.batch.get("batch_id", "FIXED_FIVE"),
            "total_cards": len(cards),
            "cards_reviewed": len(reviewed),
            "cards": statuses,
            "CONFIRM": counts["CONFIRM"],
            "CHANGE": counts["CHANGE"],
            "SKIP": len(skips),
            "category_only": sum(set(r["fields"]) == {"category"} for r in revisions),
            "context_only": sum(set(r["fields"]) == {"context"} for r in revisions),
            "both_fields": sum(len(r["fields"]) == 2 for r in revisions),
            "stale_state_blocks": sum(a["action"] == "STALE" for a in self.attempts()),
            "audit_records": len(revisions),
            "knowledge_events": len(revisions),
            "knowledge_diff": {
                "before": len(base.items),
                "after": len(snapshot.items),
                "added": len(new_ids - old_ids),
                "superseded": len(old_ids - new_ids),
                "events_hash": snapshot.events_hash,
                "contradictions_before": len(base.contradictions),
                "contradictions_after": len(snapshot.contradictions),
            },
            "legacy_review_rows_changed": 0,
            "unrelated_rows_changed": 0,
            "source_fingerprints": fingerprints,
            "recommendation": "KEEP_FIXED_BATCH_ONLY",
            "post_pilot_full_verification": "PENDING" if reviewed else "NOT_STARTED",
            "interpretation": "Human workflow verification, not model accuracy.",
        }
        if self.service.batch.get("version") == "GENERAL_CONFIRMATION_V1":
            report.update(general_metrics(cards, revisions, skips))
            report["recommendation"] = "KEEP_SMALL_BATCH_ONLY"
        self.write("report.json", report)
        return report


def general_metrics(cards, revisions, skips):
    latest = {}
    for r in sorted(revisions, key=lambda r: r["sequence"]):
        latest[r["audit"]["card_id"]] = r
    quality = Counter()
    reason_outcomes = {}
    for cid, card in cards.items():
        proposed = {
            k: v
            for k, v in card["suggestion"].items()
            if k in ("category", "context") and v is not None
        }
        row = latest.get(cid)
        if row:
            final = {
                k: v
                for k, v in row["state"].items()
                if k in ("category", "context") and v is not None
            }
            if not proposed:
                outcome = "no_suggestion_manually_classified"
            elif any(k not in final for k in proposed):
                outcome = "suggestion_partially_reviewed"
            elif final == proposed:
                outcome = "suggestion_accepted_unchanged"
            elif any(final.get(k) == v for k, v in proposed.items()):
                outcome = "suggestion_partially_changed"
            else:
                outcome = "suggestion_fully_changed"
        elif cid in skips:
            outcome = "no_suggestion_skipped" if not proposed else "suggestion_skipped"
        else:
            outcome = "not_reviewed"
        quality[outcome] += 1
        codes = {r["code"] for r in card["reasons"]}
        if card.get("multi_context"):
            codes.add("MULTI_CONTEXT_MERCHANT")
        for code in codes:
            reason_outcomes.setdefault(code, Counter())[outcome] += 1
    pay = {cid for cid, c in cards.items() if c.get("paytrail_purpose")}
    return {
        "suggestion_vs_final": dict(quality),
        "reason_code_outcomes": {k: dict(v) for k, v in reason_outcomes.items()},
        "reason_analysis_limitation": (
            "Exposure and decision association only; no causal usefulness or accuracy claim."
        ),
        "abstentions_manually_classified": quality["no_suggestion_manually_classified"],
        "paytrail_confirmations": len(pay & latest.keys()),
        "paytrail_skips": len(pay & skips),
        "multi_context_cases": sum(c.get("multi_context", False) for c in cards.values()),
        "corrections": sum(r["sequence"] > 1 for r in revisions),
    }
