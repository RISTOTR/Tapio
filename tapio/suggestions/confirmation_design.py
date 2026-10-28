"""Executable design fixtures only. Pure dry-run values; no routes, database or event writes."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from data_pipeline.labels.contracts import CATEGORIES, CONTEXTS
from tapio.knowledge.models import Typed, digest
from tapio.suggestions.models import Card


class ReviewChoice(Typed):
    action: Literal["CONFIRM", "CHANGE", "SKIP"]
    fields: dict[Literal["category", "context"], str] = Field(default_factory=dict)
    expected_state_hash: str
    user_timestamp: datetime
    correction_reason: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.user_timestamp.tzinfo is None:
            raise ValueError("TIMEZONE_REQUIRED")
        if (self.action == "SKIP") != (not self.fields):
            raise ValueError("SKIP_HAS_NO_FIELDS_OTHER_ACTIONS_REQUIRE_FIELDS")
        for field, value in self.fields.items():
            if value not in (CATEGORIES if field == "category" else CONTEXTS):
                raise ValueError("INVALID_REVIEW_VALUE")
        return self


def preview(card: Card, current: dict, choice: ReviewChoice, *, previous_review_id=None):
    """No authority is granted by calling this function; it only describes a future write."""
    if set(current) != {"category", "context"}:
        raise ValueError("EXACT_CURRENT_FIELDS_REQUIRED")
    if (
        digest(
            {
                "transaction_id": card.transaction.id,
                "current": current,
                "previous_review_id": previous_review_id,
            }
        )
        != choice.expected_state_hash
    ):
        raise ValueError("STALE_REVIEW_STATE")
    if choice.action == "CONFIRM" and any(
        getattr(card.suggestion, field) is None or getattr(card.suggestion, field) != value
        for field, value in choice.fields.items()
    ):
        raise ValueError("CONFIRM_ONLY_EXPLICIT_SUGGESTED_FIELDS")
    if previous_review_id and choice.fields and not choice.correction_reason:
        raise ValueError("CORRECTION_REASON_REQUIRED")
    changes = {
        field: {"old": current[field], "new": value}
        for field, value in choice.fields.items()
        if current[field] != value
    }
    return {
        "mode": "DRY_RUN",
        "writes_enabled": False,
        "persisted": False,
        "transaction": card.transaction.model_dump(mode="json"),
        "current": dict(current),
        "changes": changes,
        "unchanged_fields": sorted(set(current) - set(changes)),
        "action": choice.action,
        "audit_preview": {
            "transaction_id": card.transaction.id,
            "old_values": dict(current),
            "new_values": {**current, **choice.fields},
            "explicit_fields": sorted(choice.fields),
            "action": choice.action,
            "user_timestamp": choice.user_timestamp.isoformat(),
            "card_id": card.card_id,
            "suggestion_snapshot": card.suggestion.model_dump(),
            "evidence_shown": [e.model_dump(mode="json") for e in card.evidence],
            "supersedes_review_id": previous_review_id,
            "correction_reason": choice.correction_reason,
        },
        "event_preview": (
            {
                "event_type": "HUMAN_REVIEW_CONFIRMED",
                "preview_only": True,
                "transaction_id": card.transaction.id,
                "explicit_fields": dict(choice.fields),
                "target_authority_after_explicit_commit": "HUMAN_CONFIRMED",
                "merchant_rule_created": False,
                "supersedes_review_id": previous_review_id,
            }
            if choice.fields
            else None
        ),
        "commit_preconditions": [
            "Separately authorized write implementation and explicit final user click.",
            "Server-side authenticated local human intent; feedback choice is not authority.",
            "Recheck card/evidence and review version in one atomic transaction.",
            "Append review revision, audit and transactional event outbox; never rewrite history.",
            "Idempotency key prevents duplicate review and knowledge observations.",
            "Multi-context policy and tax-review boundary remain unchanged.",
        ],
    }
