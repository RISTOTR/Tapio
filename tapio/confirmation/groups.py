"""Minimal review plan and atomic group writes using the existing decision writer."""

import json
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from apps.api.app.domain.models import Document, Transaction
from integrations.gmail.cache import private_write
from integrations.gmail.receipts import norm
from tapio.confirmation.batch import prepare_candidates
from tapio.confirmation.grouping import DEFAULT_REVIEW_BUDGET, analyze
from tapio.confirmation.persistent import LOCK
from tapio.confirmation.receipt_support import integrate_receipt, receipt_fresh
from tapio.confirmation.replay import replay_confirmations
from tapio.confirmation.service import Commit, ConfirmationService, review_state
from tapio.knowledge.category_mappings import current_mappings
from tapio.knowledge.concepts import apply_concepts, identity
from tapio.knowledge.models import KnowledgeEvent, digest
from tapio.knowledge.uncertainty import apply_uncertainty, observations
from tapio.knowledge.user_rules import apply_user_rules


class GroupReview:
    def __init__(self, queue):
        self.queue = queue
        self.plans = {}

    def versions(self):
        q = self.queue
        return {
            "concept": q.concepts.version(),
            "rule": q.rules.version(),
            "mapping": q.mappings.version(),
            "receipts": {
                p.name: digest(p.read_text()) for p in sorted((q.root / "receipts").glob("*.json"))
            },
        }

    def verify_sources(self):
        from tapio.pilot.config import load_config, readonly_engine, source_fingerprints

        config, _ = load_config()
        engine = readonly_engine()
        try:
            actual = source_fingerprints(engine, config)
            if actual != self.queue.manifest()["source_fingerprints"]:
                raise ValueError("STALE_SOURCE_EVIDENCE")
            return actual
        finally:
            engine.dispose()

    def build(self, budget=DEFAULT_REVIEW_BUDGET):
        with LOCK:
            return self._build(budget)

    def _build(self, budget):
        q = self.queue
        fingerprints = self.verify_sources()
        versions = self.versions()
        with q.factory() as db:
            tables = {
                name: [
                    dict(r) for r in db.execute(select(Document.metadata.tables[name])).mappings()
                ]
                for name in (
                    "transactions",
                    "transaction_label_reviews",
                    "confirmation_revisions",
                    "invoices",
                    "transaction_invoice_allocations",
                    "transaction_reversal_candidates",
                )
            }
            tables = json.loads(json.dumps(tables, default=str))
            states = {str(t.id): review_state(db, t)[:2] for t in db.scalars(select(Transaction))}
        manifest = q.manifest()
        h = manifest["initial_knowledge_hash"]
        base = q.root / "knowledge"
        events = [
            KnowledgeEvent.model_validate(e)
            for e in json.loads((base / ("events-" + h + ".json")).read_text())
        ]
        snapshot, _ = replay_confirmations(
            events,
            tables["confirmation_revisions"],
            {t["id"]: t.get("normalized_counterparty", "") for t in tables["transactions"]},
        )
        history = observations(tables, states)
        mappings = q.mappings.apply(current_mappings(q.concepts.candidates(), tables, states))
        by_id = {t["id"]: t for t in tables["transactions"]}
        cards = []
        for c in prepare_candidates(tables, snapshot, datetime.now(UTC), states, bounded=True):
            tx = by_id[c["transaction"]["id"]]
            path = q.root / "receipts" / (tx["id"] + ".json")
            if path.exists():
                c = integrate_receipt(c, json.loads(path.read_text()))
            c = apply_concepts(
                c, tx, q.concepts.candidates(), q.concepts.decisions(), mappings=mappings
            )
            c = apply_user_rules(c, tx, q.rules.active())
            c = apply_uncertainty(c, tx, history, bool(c.get("semantic_concepts")))
            c["identity_key"] = norm(identity(tx))
            cards.append(c)
        plan = analyze(cards, history, budget)
        eligible = {c["transaction"]["id"] for c in cards}
        excluded = [
            {
                "transaction_id": txid,
                "reason": "INSUFFICIENT_EVIDENCE",
                "why_review": "Existing source/reversal/document eligibility guard; "
                "requires evidence reconciliation before confirmation",
            }
            for txid, (state, _) in states.items()
            if txid not in eligible
            and not all(
                state.get("authority", {}).get(f) == "HUMAN_CONFIRMED" and state.get(f) is not None
                for f in ("category", "context")
            )
        ]
        plan["excluded"] = excluded
        plan["summary"]["ineligible_pending"] = len(excluded)
        plan["summary"]["eligible_pending"] = len(cards)
        plan["summary"]["total_pending"] += len(excluded)
        # Excluded items still require manual investigation: no claimed savings for them.
        plan["summary"]["manual_actions_before"] += 4 * len(excluded)
        plan["summary"]["manual_actions_after"] += 4 * len(excluded)
        before = plan["summary"]["manual_actions_before"]
        plan["summary"]["estimated_reduction_percent"] = (
            round(100 * plan["summary"]["estimated_actions_saved"] / before, 1) if before else 0
        )
        batch = {
            "version": "MINIMAL_REVIEW_V1",
            "cards": plan["cards"],
            "cards_hash": digest(plan["cards"]),
            "source_fingerprints": fingerprints,
            "baseline_revisions": {r["id"]: digest(r) for r in tables["confirmation_revisions"]},
            "knowledge_versions": versions,
        }
        plan_id = digest(batch)
        batch["batch_id"] = "MINIMAL-" + plan_id
        service = ConfirmationService(q.factory, batch, enabled=q.enabled) if cards else None
        if service:
            service.evidence_check = lambda c: (
                self.versions() == versions and receipt_fresh(c, q.root)
            )
        plan["plan_id"] = plan_id
        plan["writes_enabled"] = q.enabled()
        plan["versions"] = versions
        self.plans = {k: v for k, v in self.plans.items() if v[2] > time.time()}
        if len(self.plans) >= 32:
            raise ValueError("TOO_MANY_REVIEW_PLANS_REFRESH_LATER")
        self.plans[plan_id] = (plan, service, time.time() + 7200)
        private_write(q.root / "minimal_review/report.json", json.dumps(plan, indent=2).encode())
        return plan

    def get(self, plan_id):
        entry = self.plans.get(plan_id)
        if not entry or entry[2] < time.time():
            raise ValueError("REVIEW_PLAN_EXPIRED_REFRESH")
        return entry[:2]

    def preview(self, plan_id, group_id, sid):
        plan, s = self.get(plan_id)
        group = next((g for g in plan["groups"] if g["id"] == group_id), None)
        if not group:
            raise ValueError("GROUP_NOT_ALLOWLISTED")
        previews = []
        for cid in group["card_ids"]:
            current = s.current_review(cid)
            previews.append(
                s.preview(
                    {
                        "card_id": cid,
                        "action": "CONFIRM",
                        "fields": group["fields"],
                        "review_version": current["review_version"],
                    },
                    sid,
                )
            )
        payload = {
            "browser_session": sid,
            "batch_hash": s.batch["cards_hash"],
            "expires": time.time() + 900,
            "group_id": group_id,
            "tokens": [p["token"] for p in previews],
        }
        return {
            "mode": "DRY_RUN",
            "persisted": False,
            "group": group,
            "previews": previews,
            "token": s.sign(payload),
        }

    def commit(self, plan_id, token, sid):
        with LOCK:
            plan, s = self.get(plan_id)
            payload = s.verify(token, sid)
            if self.versions() != plan["versions"]:
                raise ValueError("STALE_GROUP_KNOWLEDGE")
            self.verify_sources()
            group = next(g for g in plan["groups"] if g["id"] == payload["group_id"])
            audit = {
                "group_id": group["id"],
                "transaction_ids": group["transaction_ids"],
                "reason": group["reason"],
                "fields": group["fields"],
                "REPEATED_CONFIRMATION_AVOIDED": len(group["card_ids"]) - 1,
            }
            results = []
            # One transaction: any member stale or failed means no member is committed.
            with self.queue.factory.begin() as db:
                list(
                    db.scalars(
                        select(Transaction)
                        .where(Transaction.id.in_([UUID(t) for t in group["transaction_ids"]]))
                        .order_by(Transaction.id)
                        .with_for_update()
                    )
                )
                for member_token in payload["tokens"]:
                    results.append(
                        s._commit(
                            Commit(token=member_token, explicit_click="APPLY_DISPLAYED_CHANGES"),
                            sid,
                            transaction=db,
                            group_audit=audit,
                        )
                    )
            return {"status": "APPLIED", "results": results, "group_id": group["id"]}

    def individual_commit(self, plan_id, request, sid):
        with LOCK:
            _, s = self.get(plan_id)
            self.verify_sources()
            return s.commit(request, sid)

    def skip(self, plan_id, group_id):
        plan, _ = self.get(plan_id)
        group = next((g for g in plan["groups"] if g["id"] == group_id), None)
        if group is None:
            raise ValueError("GROUP_NOT_ALLOWLISTED")
        # Skip only affects presentation; no human classification or knowledge is written.
        path = self.queue.root / "minimal_review/skips" / (group_id + ".json")
        if not path.exists():
            private_write(
                path,
                json.dumps(
                    {
                        "group_id": group_id,
                        "transaction_ids": group["transaction_ids"],
                        "action": "SKIP_GROUP",
                    }
                ).encode(),
            )
        return {"status": "SKIPPED", "classification_written": False}
