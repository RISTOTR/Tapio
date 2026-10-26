from typing import Literal

from pydantic import Field, JsonValue

from tapio.tools.schemas import Schema

State = Literal[
    "SUPPORTED",
    "PARTIAL_COVERAGE",
    "HUMAN_REVIEW_REQUIRED",
    "AMBIGUOUS",
    "UNSUPPORTED",
    "NEEDS_NARROWING",
    "UNAVAILABLE",
    "NO_MATCH",
]
FeedbackKind = Literal["GOOD", "INCOMPLETE", "WRONG_EVIDENCE", "UNCLEAR", "OTHER"]


class Ask(Schema):
    question: str = Field(min_length=1, max_length=7600)


class Feedback(Schema):
    rating: FeedbackKind
    note: str = Field(default="", max_length=1000)


class Evidence(Schema):
    kind: str
    summary: str
    records: int


class Review(Schema):
    type: str
    summary: str
    action: str = "Human review required; no source changes are made here."


class BankCoverage(Schema):
    requested_from: str
    requested_to: str
    observed_from: str | None
    observed_to: str | None
    context: str | None
    selected_rows: int
    human_reviewed: int
    unresolved: int
    excluded_unknown_context_rows: int
    completeness: str = "IMPORTED_ROWS_ONLY_NOT_COMPLETE_BANK_STATEMENT"


class ReviewCoverage(Schema):
    year: int
    total: int
    human_reviewed: int
    unresolved: int


class EnergyCoverage(Schema):
    supported_months: list[str]
    basis: str = "Saved retrospective unchanged-load comparison; not a realized supplier switch."
    provenance_basis: str = (
        "Accepted source-review evidence backs the saved result; "
        "this is not a fresh document-parser result."
    )


class Coverage(Schema):
    status: Literal["DETERMINED", "UNAVAILABLE"]
    bank: list[BankCoverage] = Field(default_factory=list)
    snapshot_review: ReviewCoverage | None = None
    energy: list[EnergyCoverage] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)


class Session(Schema):
    id: str
    timestamp: str
    model_calls: int
    usage_complete: bool = True
    rounds: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    latency_seconds: float
    estimated_cost_usd: str
    cost_basis: str = "Estimate using frozen USD rates; not a bill."


class PilotResponse(Schema):
    answer: str
    failure_category: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    presentation_mode: Literal[
        "TRANSACTION_SEARCH",
        "NAMED_SUBJECT",
        "QUESTION_TOO_BROAD",
        "UNSUPPORTED_SCOPE",
        "EVIDENCE_INCOMPLETE",
        "EXECUTION_ERROR",
        "PLAN_INVALID",
        "INFRASTRUCTURE_UNAVAILABLE",
        "FINANCIAL_TOTAL",
        "TRANSACTION_REVIEW",
        "AMBIGUITY",
        "COMPARISON",
        "EVIDENCE_LOOKUP",
        "COVERAGE",
        "TAX_BOUNDARY",
    ] = "EVIDENCE_LOOKUP"
    direct_answer: str = ""
    relevant_breakdown: list[str] = Field(default_factory=list)
    coverage_note: str = ""
    human_review_note: str = ""
    evidence_summary: list[str] = Field(default_factory=list)
    optional_details: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_state: State
    evidence_states: list[State]
    coverage: Coverage
    evidence: list[Evidence]
    human_review: list[Review]
    limitations: list[str]
    session: Session
