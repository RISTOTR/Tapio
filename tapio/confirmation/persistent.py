"""Persistent bounded queue, immutable windows, explicit pagination and no auto-review."""

import hashlib
import hmac
import json
import os
import re
import threading
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from apps.api.app.domain.models import Document, Transaction
from integrations.gmail.cache import private_write
from integrations.gmail.receipts import receipt_events
from tapio.confirmation.batch import freeze_batch, prepare_candidates
from tapio.confirmation.concept_review import ConceptReview
from tapio.confirmation.mapping_review import MappingReview
from tapio.confirmation.receipt_support import integrate_receipt, receipt_fresh
from tapio.confirmation.replay import replay_confirmations
from tapio.confirmation.rule_review import RuleReview
from tapio.confirmation.service import ConfirmationService, review_state
from tapio.knowledge.category_mappings import current_mappings, mapping_events
from tapio.knowledge.concepts import apply_concepts, identity, words
from tapio.knowledge.models import KnowledgeEvent, digest
from tapio.knowledge.store import load_bundle, save_bundle
from tapio.knowledge.uncertainty import apply_uncertainty, observations, replay_unknown
from tapio.knowledge.user_rules import apply_user_rules
from tapio.pilot.config import digest as file_hash

ROOT = Path("data/interim/persistent_review")
LOCK = threading.RLock()
TERMINAL = {"CONFIRMED", "CHANGED", "SKIPPED", "STALE", "BLOCKED"}


class PersistentQueue:
    def __init__(self, factory, root=ROOT):
        self.factory, self.root = factory, Path(root)
        self.concepts = ConceptReview(root)
        self.rules = RuleReview(self.root / "user_rules")
        self.mappings = MappingReview(self.root / "category_mapping_review")
        self._service = None

    def manifest(self):
        envelope = json.loads((self.root / "queue.json").read_text())
        value = envelope["data"]
        signature = hmac.new(
            (self.root / "queue.key").read_bytes(),
            json.dumps(value, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, envelope["signature"]):
            raise ValueError("QUEUE_INTEGRITY")
        if value["active"] is not None and not re.fullmatch(r"W[0-9]{4}", value["active"]):
            raise ValueError("QUEUE_WINDOW_ID")
        if len(value["transaction_ids"]) > 1000 or len(set(value["transaction_ids"])) != len(
            value["transaction_ids"]
        ):
            raise ValueError("QUEUE_BOUND_EXCEEDED")
        return value

    def save_manifest(self, value):
        signature = hmac.new(
            (self.root / "queue.key").read_bytes(),
            json.dumps(value, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()
        private_write(
            self.root / "queue.json",
            json.dumps({"data": value, "signature": signature}, indent=2).encode(),
        )

    def enabled(self):
        try:
            seal = json.loads((self.root / "verified.json").read_text())
            return (
                os.getenv("TAPIO_CONFIRMATION_WRITES", "false").lower() == "true"
                and seal["verified"]
                and all(file_hash(p) == h for p, h in seal["implementation_hashes"].items())
            )
        except (OSError, ValueError, KeyError):
            return False

    def service(self):
        active = self.manifest()["active"]
        if self._service is not None and self._service.batch["window_id"] == active:
            return self._service
        root = self.root / "windows" / active
        batch = json.loads((root / "preview.json").read_text())
        if digest(batch) != self.manifest()["windows"][active]["batch_digest"]:
            raise ValueError("WINDOW_INTEGRITY")
        service = ConfirmationService(
            self.factory,
            batch,
            enabled=lambda: (
                self.enabled()
                and self.manifest()["active"] == active
                and not (root / "blocked.json").exists()
            ),
        )
        from tapio.confirmation.controlled import ControlledPilot

        service.monitor = ControlledPilot(service, root, root)
        service.monitor.lock = LOCK
        service.evidence_check = lambda c: (
            self.concepts.version() == batch["concept_version"]
            and ("rule_version" not in batch or self.rules.version() == batch["rule_version"])
            and (
                "mapping_version" not in batch
                or self.mappings.version() == batch["mapping_version"]
            )
            and receipt_fresh(c, self.root)
        )
        self._service = service
        return service

    def progress(self):
        queue = self.manifest()
        service = self.service()
        states = {cid: service.card_status(cid)["write_state"] for cid in service.cards}
        counts = Counter(
            "READY" if v == "READY_TO_CONFIRM" else "BLOCKED" if v == "READ_ONLY" else v
            for v in states.values()
        )
        used = set(tx for window in queue["windows"].values() for tx in window["transaction_ids"])
        return {
            "working_set_id": queue["active"],
            "total": len(queue["transaction_ids"]),
            "pending": len(set(queue["transaction_ids"]) - used),
            "window_states": dict(counts),
            "window_size": len(states),
            "reviewed": sum(counts[s] for s in ("CONFIRMED", "CHANGED", "SKIPPED")),
            "archived_windows": len(queue["windows"]) - 1,
            "can_advance": all(v in TERMINAL for v in states.values()),
            "writes_enabled": self.enabled(),
            "pending_user_rules": sum(r["decision"] == "PENDING" for r in self.rules.records()),
        }

    def advance(self, expected_window, *, initial=False, refresh=False):
        with LOCK:
            queue = self.manifest()
            if queue["active"] != expected_window:
                raise ValueError("STALE_QUEUE_WINDOW")
            if not initial and (not self.enabled() or not self.progress()["can_advance"]):
                raise ValueError("COMPLETE_CURRENT_WINDOW_FIRST")
            if any(
                r["decision"] == "PENDING" and not r.get("optional_candidate", False)
                for r in self.rules.records()
            ):
                raise ValueError("REVIEW_USER_RULE_CANDIDATES_FIRST")
            used = set(
                tx for window in queue["windows"].values() for tx in window["transaction_ids"]
            )
            pending = set(queue["transaction_ids"]) - used
            if refresh and not initial:
                pending = {
                    c["transaction"]["id"]
                    for cid, c in self.service().cards.items()
                    if self.service().card_status(cid)["write_state"]
                    in {"STALE", "BLOCKED", "READ_ONLY"}
                }
            if not pending:
                raise ValueError("QUEUE_COMPLETE")
            from tapio.pilot.config import load_config, readonly_engine, source_fingerprints

            config, _ = load_config()
            engine = readonly_engine()
            try:
                if source_fingerprints(engine, config) != queue["source_fingerprints"]:
                    raise ValueError("STALE_SOURCE_EVIDENCE")
            finally:
                engine.dispose()
            with self.factory() as db:
                tables = {
                    name: json.loads(
                        json.dumps(
                            [
                                dict(r)
                                for r in db.execute(
                                    select(Document.metadata.tables[name])
                                ).mappings()
                            ],
                            default=str,
                        )
                    )
                    for name in (
                        "transactions",
                        "transaction_label_reviews",
                        "confirmation_revisions",
                        "invoices",
                        "transaction_invoice_allocations",
                        "transaction_reversal_candidates",
                    )
                }
                states = {
                    str(t.id): review_state(db, t)[:2] for t in db.scalars(select(Transaction))
                }
            if initial:
                h = queue["initial_knowledge_hash"]
                base = self.root / "knowledge"
            else:
                service = self.service()
                service.monitor.refresh(persist=False)
                h = service.batch["knowledge_hash"]
                base = self.root / "windows" / queue["active"] / "knowledge"
            snapshot = load_bundle(base / ("snapshot-" + h + ".json"))
            events = [
                KnowledgeEvent.model_validate(e)
                for e in json.loads((base / ("events-" + h + ".json")).read_text())
            ]
            if not initial:
                allowed = {c["transaction"]["id"]: c for c in service.cards.values()}
                snapshot, events = replay_confirmations(
                    events,
                    [r for r in tables["confirmation_revisions"] if r["transaction_id"] in allowed],
                    {tx: c["transaction"]["merchant"] for tx, c in allowed.items()},
                )
            mappings = self.mappings.apply(
                current_mappings(self.concepts.candidates(), tables, states)
            )
            now = datetime.now(UTC)
            candidates = prepare_candidates(tables, snapshot, now, states, bounded=True)
            by_id = {t["id"]: t for t in tables["transactions"]}
            known_identities = {
                words(identity(t))
                for t in tables["transactions"]
                if states[t["id"]][0].get("authority", {}).get("category") == "HUMAN_CONFIRMED"
            }
            uncertainty = observations(tables, states)
            selected = []
            for card in candidates:
                txid = card["transaction"]["id"]
                if txid not in pending:
                    continue
                path = self.root / "receipts" / (txid + ".json")
                if path.exists():
                    card = integrate_receipt(card, json.loads(path.read_text()))
                card = apply_concepts(
                    card,
                    by_id[txid],
                    self.concepts.candidates(),
                    self.concepts.decisions(),
                    mappings=mappings,
                )
                card = apply_user_rules(card, by_id[txid], self.rules.active())
                from tapio.knowledge.concepts import matches

                semantic_known = any(
                    r["active"] and matches(r["term"], r["match_mode"], identity(by_id[txid]))
                    for r in self.concepts.records()
                )
                card = apply_uncertainty(card, by_id[txid], uncertainty, semantic_known)
                card["unseen_exact_identity"] = words(identity(by_id[txid])) not in known_identities
                if card.get("concept_candidates"):
                    card["pilot_tags"].append("PENDING_SEMANTIC_CANDIDATE")
                if any(
                    c["concept"]
                    in {"AIRLINE", "DEPARTMENT_STORE", "GENERAL_RETAILER", "AIRPORT_FOOD_SERVICE"}
                    for c in card.get("concept_candidates", [])
                ):
                    card["pilot_tags"].append("ENTITY_VS_PURCHASE_PURPOSE")
                selected.append(card)
            # Prefer potential concept coverage but retain diverse baseline cases.
            selected.sort(
                key=lambda c: (
                    not bool(c.get("user_rules")),
                    not bool(c.get("semantic_category_added") and c.get("unseen_exact_identity")),
                    not bool(c["semantic_category_used"]),
                    not bool(c.get("paytrail_purpose")),
                    c["transaction"]["date"],
                    c["card_id"],
                )
            )
            if not selected:
                raise ValueError("NO_ELIGIBLE_PENDING_TRANSACTIONS")
            size = min(queue["window_size"], len(selected))
            fingerprints = queue["source_fingerprints"]
            baseline = {r["id"]: digest(r) for r in tables["confirmation_revisions"]}
            if size >= 25:
                batch = freeze_batch(
                    selected,
                    snapshot.events_hash,
                    fingerprints,
                    baseline,
                    size=size,
                    bounded=True,
                    created_at=now,
                )
            else:
                cards = selected[:size]
                batch = {
                    "cards": cards,
                    "cards_hash": digest(cards),
                    "baseline_revisions": baseline,
                    "source_fingerprints": fingerprints,
                    "created_at": now.isoformat(),
                }
            window_id = f"W{len(queue['windows']) + 1:04d}"
            batch.update(
                version="PERSISTENT_CONFIRMATION_V1",
                window_id=window_id,
                uncertainty_version="EXPLICIT_UNKNOWN_V1",
                mapping_version=self.mappings.version(),
                concept_version=self.concepts.version(),
                rule_version=self.rules.version(),
                category_mappings_hash=digest(mappings),
            )
            new_root = self.root / "windows" / window_id
            new_root.mkdir(parents=True, mode=0o700, exist_ok=False)
            private_write(
                new_root / "category_mappings.json", json.dumps(mappings, indent=2).encode()
            )
            new_events = (
                self.concepts.knowledge_events()
                + self.rules.knowledge_events()
                + mapping_events(mappings, now)
            )
            for card in batch["cards"]:
                if card.get("receipt_evidence"):
                    new_events.extend(
                        receipt_events(card["transaction"]["id"], card["receipt_evidence"])
                    )
            combined = save_bundle(
                new_root / "knowledge", replay_unknown(events + new_events, uncertainty)
            )
            batch["knowledge_hash"] = combined.events_hash
            batch.pop("batch_id", None)
            batch["batch_id"] = "QUEUE-" + digest(batch)[:16]
            private_write(
                new_root / "preview.json", json.dumps(batch, ensure_ascii=False, indent=2).encode()
            )
            private_write(
                new_root / "knowledge_diff.json",
                json.dumps({"new_events_hash": combined.events_hash}).encode(),
            )
            queue["windows"][window_id] = {
                "batch_id": batch["batch_id"],
                "batch_digest": digest(batch),
                "transaction_ids": [c["transaction"]["id"] for c in batch["cards"]],
            }
            queue["active"] = window_id
            self.save_manifest(queue)
            self._service = None
            return {"window_id": window_id, "batch_id": batch["batch_id"], "cards": size}
