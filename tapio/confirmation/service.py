"""Atomic append-only confirmation limited to a fixed allowlisted preview batch."""

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Transaction, TransactionLabelReview
from data_pipeline.labels.contracts import CATEGORIES, CONTEXTS
from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance, Typed, canonical, digest
from tapio.pilot.history import private_text


class Selection(Typed):
    card_id: str
    action: Literal["CONFIRM", "CHANGE", "SKIP"]
    fields: dict[Literal["category", "context"], str] = Field(default_factory=dict)
    correction_reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid(self):
        if (self.action == "SKIP") != (not self.fields):
            raise ValueError("SELECT_FIELDS_OR_SKIP")
        for field, value in self.fields.items():
            if value not in (CATEGORIES if field == "category" else CONTEXTS):
                raise ValueError("INVALID_LABEL")
        return self


class Commit(Typed):
    token: str = Field(max_length=20000)
    explicit_click: Literal["APPLY_DISPLAYED_CHANGES"]


def row_data(row):
    return json.loads(
        json.dumps({c.name: getattr(row, c.name) for c in row.__table__.columns}, default=str)
    )


def review_state(db, tx):
    legacy = db.scalar(
        select(TransactionLabelReview).where(TransactionLabelReview.transaction_id == tx.id)
    )
    latest = db.scalar(
        select(ConfirmationRevision)
        .where(ConfirmationRevision.transaction_id == tx.id)
        .order_by(ConfirmationRevision.sequence.desc())
        .limit(1)
    )
    confirmed = legacy is not None and legacy.review_status == "REVIEWED"
    state = {
        "category": legacy.confirmed_category if confirmed else None,
        "context": legacy.confirmed_business_context if confirmed else None,
        "authority": {
            "category": "HUMAN_CONFIRMED" if confirmed else "UNKNOWN",
            "context": "HUMAN_CONFIRMED" if confirmed else "UNKNOWN",
        },
    }
    if latest:
        if latest.audit.get("legacy_review_hash") != digest(row_data(legacy) if legacy else None):
            raise ValueError("LEGACY_REVIEW_CHANGED_REQUIRES_RECONCILIATION")
        state = latest.state
    version = digest(
        {
            "transaction": row_data(tx),
            "legacy_review": row_data(legacy) if legacy else None,
            "latest_revision": str(latest.id) if latest else None,
            "state": state,
        }
    )
    return state, version, latest


class ConfirmationService:
    def __init__(self, session_factory, batch, *, signing_key=None, enabled=None):
        general = batch.get("version") == "GENERAL_CONFIRMATION_V1"
        if not ((15 <= len(batch["cards"]) <= 25) if general else (1 <= len(batch["cards"]) <= 5)):
            raise ValueError("PREVIEW_BATCH_LIMIT")
        if digest(batch["cards"]) != batch["cards_hash"]:
            raise ValueError("PREVIEW_BATCH_HASH")
        if len({c["transaction"]["id"] for c in batch["cards"]}) != len(batch["cards"]):
            raise ValueError("DUPLICATE_TRANSACTION")
        for card in batch["cards"]:
            if general:
                if (
                    not card.get("source_stable_id")
                    or abs(Decimal(card["transaction"]["amount"])) == Decimal("588.07")
                    or any(card["current_state"][f] is not None for f in ("category", "context"))
                    or (card.get("multi_context") and card["suggestion"]["context"] is not None)
                    or (
                        card.get("paytrail_purpose") == "STILL_OPAQUE"
                        and any(card["suggestion"][f] for f in ("category", "context"))
                    )
                ):
                    raise ValueError("UNSAFE_GENERAL_ALLOWLIST")
                continue
            if (
                ambiguous_merchant(card["transaction"]["merchant"])
                or card["transaction"]["merchant"] == "Paytrail Oyj"
                or card.get("priority") == "AMBIGUOUS_REVIEW"
                or card.get("conflicting_knowledge")
            ):
                raise ValueError("UNSAFE_PREVIEW_ALLOWLIST")
        self.factory = session_factory
        self.batch = batch
        self.cards = {c["card_id"]: c for c in batch["cards"]}
        if len(self.cards) != len(batch["cards"]):
            raise ValueError("DUPLICATE_CARD")
        self.key = signing_key or secrets.token_bytes(32)
        self.enabled = enabled or (
            lambda: os.getenv("TAPIO_CONFIRMATION_WRITES", "false").lower() == "true"
        )

    @classmethod
    def local(cls, factory):
        profile = os.getenv("TAPIO_CONFIRMATION_BATCH", "FIXED_FIVE")
        if profile not in {"FIXED_FIVE", "GENERAL_V1"}:
            raise ValueError("UNSUPPORTED_CONFIRMATION_BATCH")
        general = profile == "GENERAL_V1"
        root = Path(
            "data/interim/general_confirmation" if general else "data/interim/full_csv_confirmation"
        )
        monitor_root = Path(
            "data/interim/general_confirmation"
            if general
            else "data/interim/controlled_confirmation"
        )
        batch = json.loads((root / "preview.json").read_text())

        def enabled():
            if (monitor_root / "blocked.json").exists():
                return False
            if os.getenv("TAPIO_CONFIRMATION_WRITES", "false").lower() != "true":
                return False
            try:
                seal = json.loads((monitor_root / "verified.json").read_text())
                return (
                    seal["batch_hash"] == batch["cards_hash"]
                    and (not general or seal.get("batch_digest") == digest(batch))
                    and seal["verified"] is True
                    and all(
                        hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                        for p, h in seal["implementation_hashes"].items()
                    )
                )
            except (OSError, ValueError, KeyError):
                return False

        instance = cls(factory, batch, enabled=enabled)
        from tapio.confirmation.controlled import ControlledPilot

        instance.monitor = ControlledPilot(instance, monitor_root, root)
        return instance

    def card_status(self, card_id):
        c = self.card(card_id)
        with self.factory() as db:
            tx = db.get(Transaction, UUID(c["transaction"]["id"]))
            try:
                state, version, last = review_state(db, tx)
            except ValueError:
                return {"write_state": "STALE", "current_state": c["current_state"]}
            stale = digest(row_data(tx)) != c["source_hash"] or (
                not last and version != c["initial_state_hash"]
            )
            status = (
                "STALE"
                if stale
                else (
                    ("CONFIRMED" if last.action == "CONFIRM" else "CHANGED")
                    if last
                    else ("READY_TO_CONFIRM" if self.enabled() else "READ_ONLY")
                )
            )
        monitor = getattr(self, "monitor", None)
        if not last and not stale and monitor and monitor.skipped(card_id):
            status = "SKIPPED"
        return {"write_state": status, "current_state": state}

    def card(self, card_id):
        if card_id not in self.cards:
            raise ValueError("CARD_NOT_ALLOWLISTED")
        return self.cards[card_id]

    def sign(self, payload):
        raw = canonical(payload)
        return json.dumps(
            {
                "payload": payload,
                "signature": hmac.new(self.key, raw.encode(), hashlib.sha256).hexdigest(),
            }
        )

    def verify(self, token, browser_session):
        try:
            t = json.loads(token)
            p = t["payload"]
            signature = hmac.new(self.key, canonical(p).encode(), hashlib.sha256).hexdigest()
            if (
                not hmac.compare_digest(signature, t["signature"])
                or p["expires"] < time.time()
                or p["browser_session"] != browser_session
                or p["batch_hash"] != self.batch["cards_hash"]
            ):
                raise ValueError()
            return p
        except (KeyError, ValueError, TypeError):
            raise ValueError("INVALID_OR_EXPIRED_PREVIEW") from None

    def preview(self, selection, browser_session):
        selection = Selection.model_validate(selection)
        c = self.card(selection.card_id)
        with self.factory() as db:
            tx = db.get(Transaction, UUID(c["transaction"]["id"]))
            state, version, last = review_state(db, tx)
            # Initial cards must match; corrections require a fresh preview.
            if not last and version != c["initial_state_hash"]:
                raise ValueError("STALE_CARD_REFRESH_REQUIRED")
            if digest(row_data(tx)) != c["source_hash"]:
                raise ValueError("SOURCE_CHANGED_REFRESH_REQUIRED")
        if selection.action == "CONFIRM" and any(
            c["suggestion"].get(f) != v or c["suggestion"].get(f) is None
            for f, v in selection.fields.items()
        ):
            raise ValueError("CONFIRM_REQUIRES_SHOWN_SUGGESTION")
        if last and selection.fields and not selection.correction_reason.strip():
            raise ValueError("CORRECTION_REASON_REQUIRED")
        payload = {
            "selection": selection.model_dump(),
            "state_hash": version,
            "browser_session": browser_session,
            "expires": time.time() + 900,
            "batch_hash": self.batch["cards_hash"],
            "nonce": secrets.token_hex(24),
            "card_hash": digest(c),
        }
        return {
            "mode": "DRY_RUN",
            "writes_enabled": self.enabled(),
            "persisted": False,
            "transaction": {k: v for k, v in c["transaction"].items() if k != "id"},
            "source_messages": c["source_messages"],
            "current": state,
            "suggested": c["suggestion"],
            "would_change": {f: {"old": state[f], "new": v} for f, v in selection.fields.items()},
            "untouched_fields": sorted({"category", "context"} - set(selection.fields)),
            "action": selection.action,
            "token": self.sign(payload),
            "event_preview": {
                "type": "HUMAN_REVIEW_CONFIRMED",
                "fields": selection.fields,
                "transaction_scoped": True,
            }
            if selection.fields
            else None,
            "audit_preview": {
                "old_values": state,
                "selected_values": selection.fields,
                "card_id": c["card_id"],
                "card_version": c["rule_version"],
                "suggestion_snapshot": c["suggestion"],
                "evidence": c["evidence"],
                "previous_revision": str(last.id) if last else None,
            },
        }

    def commit(self, request, browser_session):
        monitor = getattr(self, "monitor", None)
        # Serialize the bounded local workflow, including post-commit verification.
        if monitor:
            with monitor.lock:
                monitor.preflight()
                try:
                    result = self._commit(request, browser_session)
                except ValueError as exc:
                    if "STALE" in str(exc):
                        monitor.record_stale()
                    raise
                try:
                    return monitor.after(request, browser_session, result)
                except Exception:
                    monitor.block()
                    raise ValueError("WRITE_RECORDED_VERIFICATION_PENDING_DO_NOT_REAPPLY") from None
        return self._commit(request, browser_session)

    def _commit(self, request, browser_session):
        request = Commit.model_validate(request)
        if not self.enabled():
            raise ValueError("CONFIRMATION_WRITES_DISABLED")
        p = self.verify(request.token, browser_session)
        selected = Selection.model_validate(p["selection"])
        c = self.card(selected.card_id)
        if digest(c) != p["card_hash"]:
            raise ValueError("CARD_CHANGED")
        if selected.action == "SKIP":
            return {"status": "SKIPPED", "classification_written": False}
        with self.factory.begin() as db:
            tx = db.scalar(
                select(Transaction)
                .where(Transaction.id == UUID(c["transaction"]["id"]))
                .with_for_update()
            )
            existing = db.scalar(
                select(ConfirmationRevision).where(
                    ConfirmationRevision.idempotency_key == p["nonce"]
                )
            )
            if existing:
                return {"status": "ALREADY_APPLIED", "revision_id": str(existing.id)}
            state, version, last = review_state(db, tx)
            if version != p["state_hash"] or digest(row_data(tx)) != c["source_hash"]:
                raise ValueError("STALE_STATE_REFRESH_REQUIRED")
            now = datetime.now(UTC)
            rid = uuid4()
            new = {**state, "authority": dict(state["authority"])}
            for field, value in selected.fields.items():
                new[field] = value
                new["authority"][field] = "HUMAN_CONFIRMED"
            audit = {
                "transaction_id": str(tx.id),
                "old_values": state,
                "new_values": new,
                "action": selected.action,
                "timestamp": now.isoformat(),
                "user_selected_values": selected.fields,
                "card_id": c["card_id"],
                "card_version": c["rule_version"],
                "suggestion_snapshot": c["suggestion"],
                "evidence_shown": c["evidence"],
                "source_messages_shown": c["source_messages"],
                "batch_hash": self.batch["cards_hash"],
                "batch_id": self.batch.get("batch_id", "FIXED_FIVE"),
                "reason_codes": c["reasons"],
                "document_evidence_shown": c.get("document_evidence", []),
                "knowledge_used": c["knowledge_used"],
                "correction_reason": private_text(selected.correction_reason),
                "previous_revision": str(last.id) if last else None,
                "preview_hash": digest(p),
            }
            legacy = db.scalar(
                select(TransactionLabelReview).where(TransactionLabelReview.transaction_id == tx.id)
            )
            audit["legacy_review_hash"] = digest(row_data(legacy) if legacy else None)
            claims = []
            for field, value in selected.fields.items():
                claims.append(
                    Claim(
                        kind="RELATIONSHIP",
                        subject=str(tx.id),
                        predicate="confirmed_category"
                        if field == "category"
                        else "confirmed_business_context",
                        value=value,
                        authority="HUMAN_CONFIRMED",
                        relationship_status="CONFIRMED",
                        single_valued=True,
                        provenance=Provenance(
                            source_type="confirmation_revisions",
                            source_id=str(rid),
                            source_hash=digest(audit),
                            originating_field="fields." + field,
                            observed_at=now,
                            extraction_method="explicit-human-confirmation-v1",
                            confirmation_id=str(rid),
                        ),
                    )
                )
            event = KnowledgeEvent(event_type="HUMAN_REVIEW_CONFIRMED", claims=tuple(claims))
            event_id = digest(event)
            audit["knowledge_event_ids"] = [event_id]
            db.add(
                ConfirmationRevision(
                    id=rid,
                    transaction_id=tx.id,
                    sequence=last.sequence + 1 if last else 1,
                    previous_id=last.id if last else None,
                    idempotency_key=p["nonce"],
                    action=selected.action,
                    fields=selected.fields,
                    state=new,
                    audit=audit,
                    knowledge_event=event.model_dump(mode="json"),
                )
            )
            db.flush()
            return {
                "status": "APPLIED",
                "revision_id": str(rid),
                "knowledge_event_id": event_id,
                "state": new,
                "source_transaction_changed": False,
                "legacy_review_changed": False,
            }
