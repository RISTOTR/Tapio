from typing import Literal

from pydantic import Field, model_validator

from tapio.knowledge.models import Authority, Provenance, Typed


class TransactionView(Typed):
    id: str
    date: str
    amount: str
    currency: str
    merchant: str
    description: str | None


class CurrentState(Typed):
    category: str | None
    context: str | None
    review_status: str


class Suggestion(Typed):
    category: str | None = None
    context: str | None = None
    authority: Literal["SUGGESTED"] = "SUGGESTED"


class EvidenceInput(Typed):
    id: str
    authority: Authority
    summary: str
    provenance: tuple[Provenance, ...] = Field(min_length=1)


class Reason(Typed):
    code: str
    explanation: str
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class Card(Typed):
    card_id: str
    transaction: TransactionView
    current_state: CurrentState
    suggestion: Suggestion
    reasons: tuple[Reason, ...] = Field(min_length=1)
    evidence: tuple[EvidenceInput, ...] = Field(min_length=1)
    knowledge_used: tuple[str, ...]
    warnings: tuple[str, ...]
    priority: Literal[
        "HIGH_REVIEW_VALUE", "MEDIUM_REVIEW_VALUE", "LOW_REVIEW_VALUE", "AMBIGUOUS_REVIEW"
    ]
    suggestion_status: Literal["READ_ONLY"] = "READ_ONLY"
    rule_version: Literal["DETERMINISTIC_CARDS_V1", "FULL_CSV_CARDS_V2"] = "DETERMINISTIC_CARDS_V1"
    conflicting_knowledge: bool
    selection_tags: tuple[str, ...]

    @model_validator(mode="after")
    def boundaries(self):
        refs = {e.id for e in self.evidence}
        if any(not set(r.evidence_refs) <= refs for r in self.reasons):
            raise ValueError("REASON_WITHOUT_EVIDENCE")
        if not set(self.knowledge_used) <= refs:
            raise ValueError("KNOWLEDGE_WITHOUT_PROVENANCE")
        c = self.current_state
        if c.review_status == "REVIEWED":
            if c.category not in (None, "UNKNOWN") and self.suggestion.category is not None:
                raise ValueError("CONFIRMED_CATEGORY_IS_AUTHORITATIVE")
            if c.context not in (None, "UNKNOWN") and self.suggestion.context is not None:
                raise ValueError("CONFIRMED_CONTEXT_IS_AUTHORITATIVE")
            if c.category not in (None, "UNKNOWN") and c.context not in (None, "UNKNOWN"):
                raise ValueError("FULLY_REVIEWED_TRANSACTION_INELIGIBLE")
        return self


FeedbackChoice = Literal["CORRECT", "PARTIALLY_USEFUL", "WRONG", "INSUFFICIENT_EVIDENCE", "SKIP"]


class FeedbackInput(Typed):
    choice: FeedbackChoice
    note: str = Field(default="", max_length=1000)
