"""Minimal review plan and atomic group writes using the existing decision writer."""

import hashlib
import hmac
import json
import re
import time
from datetime import UTC, datetime

from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Document, Transaction
from integrations.gmail.cache import private_write
from tapio.confirmation.batch import prepare_candidates
from tapio.confirmation.grouping import DEFAULT_REVIEW_BUDGET, analyze
from tapio.confirmation.persistent import LOCK
from tapio.confirmation.receipt_support import integrate_receipt, receipt_fresh
from tapio.confirmation.replay import replay_confirmations
from tapio.confirmation.service import Commit, ConfirmationService, review_state_data
from tapio.knowledge.category_mappings import current_mappings
from tapio.knowledge.concepts import apply_concepts, identity
from tapio.knowledge.models import KnowledgeEvent, digest
from tapio.knowledge.reuse import Reuse
from tapio.knowledge.uncertainty import apply_uncertainty, observations
from tapio.knowledge.user_rules import apply_user_rules


class GroupReview:
    def __init__(self, queue):
        self.queue = queue
        self.plans = {}
        self.latest_plan_id = None

    def review_generation(self, db=None):
        if db is None:
            with self.queue.factory() as session:
                return self.review_generation(session)
        return self.generation_from_tables(
            {
                name: [
                    dict(r) for r in db.execute(select(Document.metadata.tables[name])).mappings()
                ]
                for name in ("transactions", "confirmation_revisions", "transaction_label_reviews")
            }
        )

    @staticmethod
    def generation_from_tables(tables):
        return digest(
            {
                name: sorted(
                    (json.loads(json.dumps(r, default=str)) for r in tables[name]),
                    key=lambda r: str(r["id"]),
                )
                for name in ("transactions", "confirmation_revisions", "transaction_label_reviews")
            }
        )

    def is_current(self, plan):
        return (
            plan.get("review_generation") == self.review_generation()
            and plan["versions"] == self.versions()
        )

    def live(self, plan_id=None, budget=DEFAULT_REVIEW_BUDGET):
        with LOCK:
            if not self.latest_plan_id:
                report = self.queue.root / "minimal_review/report.json"
                if report.exists():
                    self.latest_plan_id = json.loads(report.read_text())["plan_id"]
            previous = (
                self.get(plan_id or self.latest_plan_id)[0]
                if (plan_id or self.latest_plan_id)
                else None
            )
            if previous and previous.get("budget") == budget and self.is_current(previous):
                return previous
            # Old URLs and concurrent tabs should converge on the refreshed plan,
            # rather than each rebuilding the same queue after a saved decision.
            if self.latest_plan_id and self.latest_plan_id != plan_id:
                latest = self.get(self.latest_plan_id)[0]
                if latest.get("budget") == budget and self.is_current(latest):
                    return latest
            return self._build(budget, previous)

    def versions(self):
        q = self.queue
        return {
            "reuse": digest(Reuse.load(q.root).data),
            "concept": q.concepts.version(),
            "rule": q.rules.version(),
            "mapping": q.mappings.version(),
            "receipts": {
                p.name: digest(p.read_text()) for p in sorted((q.root / "receipts").glob("*.json"))
            },
        }

    def verify_sources(self):
        from tapio.confirmation.source_updates import accepted_fingerprints
        from tapio.pilot.config import load_config, readonly_engine, source_fingerprints

        config, _ = load_config()
        config = {
            **config,
            "source_fingerprints": accepted_fingerprints(
                self.queue, config.get("source_fingerprints", {})
            ),
        }
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

    def _build(self, budget, previous=None):
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
        legacy = {r["transaction_id"]: r for r in tables["transaction_label_reviews"]}
        latest = {}
        for r in sorted(tables["confirmation_revisions"], key=lambda r: r["sequence"]):
            latest[r["transaction_id"]] = r
        states = {
            t["id"]: review_state_data(t, legacy.get(t["id"]), latest.get(t["id"]))
            for t in tables["transactions"]
        }
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
        reuse = Reuse.load(q.root, tables)
        history = reuse.history(observations(tables, states))
        candidates, decisions, rules = (
            q.concepts.candidates(),
            q.concepts.decisions(),
            q.rules.active(),
        )
        mappings = q.mappings.apply(current_mappings(candidates, tables, states))
        by_id = {t["id"]: t for t in tables["transactions"]}
        cards = []
        for c in prepare_candidates(tables, snapshot, datetime.now(UTC), states, bounded=True):
            tx = by_id[c["transaction"]["id"]]
            path = q.root / "receipts" / (tx["id"] + ".json")
            if path.exists():
                c = integrate_receipt(c, json.loads(path.read_text()))
            c = apply_concepts(
                c,
                tx,
                candidates,
                decisions,
                mappings=mappings,
                reuse=reuse,
            )
            c = apply_user_rules(c, tx, rules, reuse=reuse)
            c["identity_resolution"] = reuse.resolve(identity(tx))
            c["identity_key"] = reuse.key(identity(tx))
            if "MULTI_CONTEXT" in c["identity_resolution"]["limitations"]:
                c["multi_context"] = True
                c["suggestion"]["context"] = None
            c["purpose_review_required"] = (
                "MIXED_PURPOSE" in c["identity_resolution"]["limitations"]
            )
            c = apply_uncertainty(
                c, tx, history, bool(c.get("semantic_concepts")), identity_key=c["identity_key"]
            )
            cards.append(c)
        plan = analyze(cards, history, budget)
        if previous:
            old = {c["transaction"]["id"]: c for c in previous["cards"]}
            for c in plan["cards"]:
                before = old.get(c["transaction"]["id"], {}).get("review_analysis", {})
                a = c["review_analysis"]
                if before and not before.get("known_entity") and a["known_entity"] and a["history"]:
                    a["novelty_transition"] = "FALSE_NOVEL_RECENT_REVIEW"
                    a["recent_review_ids"] = sorted(
                        {h["review_id"] for h in a["history"]}
                        - {h["review_id"] for h in before.get("history", [])}
                    )
        plan["review_generation"] = self.generation_from_tables(tables)
        applied_groups = {
            r["audit"]["group_confirmation"]["group_id"]: r["audit"]["group_confirmation"]
            for r in tables["confirmation_revisions"]
            if r["audit"].get("group_confirmation")
        }
        plan["summary"]["actual_repeated_confirmations_avoided"] = sum(
            g["REPEATED_CONFIRMATION_AVOIDED"] for g in applied_groups.values()
        )
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
            "review_generation": plan["review_generation"],
            "review_budget": budget,
        }
        plan_id = digest(batch)
        batch["batch_id"] = "MINIMAL-" + plan_id
        service = (
            ConfirmationService(
                q.factory, batch, enabled=q.enabled, signing_key=(q.root / "queue.key").read_bytes()
            )
            if cards
            else None
        )
        if service:
            service.evidence_check = lambda c: (
                self.versions() == versions and receipt_fresh(c, q.root)
            )
        plan["plan_id"] = plan_id
        plan["writes_enabled"] = q.enabled()
        plan["versions"] = versions
        self.plans = {k: v for k, v in self.plans.items() if v[2] > time.time()}
        if len(self.plans) >= 32:
            self.plans.pop(min(self.plans, key=lambda k: self.plans[k][2]))
        if plan_id in self.plans:
            service = self.plans[plan_id][1]
        self.plans[plan_id] = (plan, service, time.time() + 7200)
        private_write(q.root / "minimal_review/report.json", json.dumps(plan, indent=2).encode())
        artifact = {"plan": plan, "batch": batch}
        signature = hmac.new(
            (q.root / "queue.key").read_bytes(), digest(artifact).encode(), hashlib.sha256
        ).hexdigest()
        private_write(
            q.root / "minimal_review/plans" / (plan_id + ".json"),
            json.dumps({"data": artifact, "signature": signature}).encode(),
        )
        self.latest_plan_id = plan_id
        return plan

    def get(self, plan_id):
        entry = self.plans.get(plan_id)
        if entry and entry[2] >= time.time():
            return entry[:2]
        if not re.fullmatch(r"[a-f0-9]{64}", plan_id):
            raise ValueError("INVALID_REVIEW_PLAN")
        q = self.queue
        try:
            envelope = json.loads(
                (q.root / "minimal_review/plans" / (plan_id + ".json")).read_text()
            )
            artifact = envelope["data"]
            signature = hmac.new(
                (q.root / "queue.key").read_bytes(), digest(artifact).encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, envelope["signature"]):
                raise ValueError("REVIEW_PLAN_INTEGRITY")
            plan, batch = artifact["plan"], artifact["batch"]
            if plan["plan_id"] != plan_id:
                raise ValueError("REVIEW_PLAN_INTEGRITY")
            s = (
                ConfirmationService(
                    q.factory,
                    batch,
                    enabled=q.enabled,
                    signing_key=(q.root / "queue.key").read_bytes(),
                )
                if batch["cards"]
                else None
            )
            if s:
                s.evidence_check = lambda c: (
                    self.versions() == plan["versions"] and receipt_fresh(c, q.root)
                )
            self.plans[plan_id] = (plan, s, time.time() + 7200)
            return plan, s
        except (OSError, KeyError, TypeError) as exc:
            raise ValueError("REVIEW_PLAN_UNAVAILABLE_REFRESH") from exc

    def preview(self, plan_id, group_id, sid):
        plan, s = self.get(plan_id)
        if not self.is_current(plan):
            raise ValueError("STALE_GROUP_HISTORY_REFRESH")
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
                list(db.scalars(select(Transaction).order_by(Transaction.id).with_for_update()))
                nonces = [s.verify(t, sid)["nonce"] for t in payload["tokens"]]
                applied = set(
                    db.scalars(
                        select(ConfirmationRevision.idempotency_key).where(
                            ConfirmationRevision.idempotency_key.in_(nonces)
                        )
                    )
                )
                if not set(nonces) <= applied:
                    self.check_history(s, db)
                for member_token in payload["tokens"]:
                    results.append(
                        s._commit(
                            Commit(token=member_token, explicit_click="APPLY_DISPLAYED_CHANGES"),
                            sid,
                            transaction=db,
                            group_audit=audit,
                        )
                    )
            self.latest_plan_id = None
            return {
                "queue_refresh_required": True,
                "status": "APPLIED",
                "results": results,
                "group_id": group["id"],
            }

    def check_history(self, service, db):
        if service.batch.get("review_generation") != self.review_generation(db):
            raise ValueError("STALE_GROUP_HISTORY_REFRESH")

    def individual_preview(self, plan_id, selection, sid):
        with LOCK:
            plan, service = self.get(plan_id)
            current = service.current_review(selection.card_id)
            if not self.completed(current) and not self.is_current(plan):
                raise ValueError("STALE_PENDING_REVIEW_REFRESH")
            return service.preview(selection, sid)

    @staticmethod
    def completed(current):
        return all(
            current[f]["authority"] == "HUMAN_CONFIRMED" and current[f]["value"] is not None
            for f in ("category", "context")
        )

    def individual_commit(self, plan_id, request, sid):
        with LOCK:
            _, s = self.get(plan_id)
            self.verify_sources()
            with self.queue.factory.begin() as db:
                list(db.scalars(select(Transaction).order_by(Transaction.id).with_for_update()))
                payload = s.verify(request.token, sid)
                selection = payload["selection"]
                if not db.scalar(
                    select(ConfirmationRevision.id).where(
                        ConfirmationRevision.idempotency_key == payload["nonce"]
                    )
                ):
                    current = s.current_review(selection["card_id"])
                    if selection["action"] == "CONFIRM" or not self.completed(current):
                        self.check_history(s, db)
                result = s._commit(request, sid, transaction=db)
            self.latest_plan_id = None
            return {**result, "queue_refresh_required": True}

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
