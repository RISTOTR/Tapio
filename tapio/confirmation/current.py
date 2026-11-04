"""Canonical current decisions, kept separate from immutable evidence and suggestions."""

from typing import Literal

from tapio.knowledge.models import Typed
from tapio.knowledge.uncertainty import FieldState, field_state


class CurrentField(Typed):
    value: str | None
    field_status: FieldState
    authority: Literal["HUMAN_CONFIRMED", "UNKNOWN"]


class CurrentReview(Typed):
    transaction_id: str
    card_id: str
    category: CurrentField
    context: CurrentField
    review_version: str
    audit_event_id: str | None


def project(card_id, transaction_id, state, version, last):
    return CurrentReview(
        transaction_id=transaction_id,
        card_id=card_id,
        category=CurrentField(
            value=state.get("category"),
            field_status=field_state(state, "category"),
            authority=state.get("authority", {}).get("category", "UNKNOWN"),
        ),
        context=CurrentField(
            value=state.get("context"),
            field_status=field_state(state, "context"),
            authority=state.get("authority", {}).get("context", "UNKNOWN"),
        ),
        review_version=version,
        audit_event_id=str(last.id) if last else None,
    ).model_dump(mode="json")
