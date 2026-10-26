"""Intent routing with synthetic evidence; no live models or source changes."""

from copy import deepcopy

import pytest
from test_pilot import Model, ask, make_pilot
from test_pilot_diagnostics import record
from test_pilot_presentation import evidence, render

from tapio.pilot.answer_cards import mode_for
from tapio.pilot.subject_identity import eligible_subject, extract_subject, resolve_subject


def resolved_fixture(question, rows=None):
    request = extract_subject(question)
    assert request is not None
    resolved = resolve_subject(request["text"], [request["text"]])
    return {
        **resolved,
        "request": request,
        "trace": {"inventory_queried": True},
        "transactions": rows or [],
        "documents": [],
        "invoices": [],
        "totals": [],
    }


@pytest.mark.parametrize(
    "question",
    [
        "Give me an overview of my finances in 2026.",
        "What are the most important things I should know about 2026 so far?",
        "What do we know about my property and forestry finances in 2026?",
        "What are the biggest unresolved issues in my imported data?",
    ],
)
def test_broad_questions_have_no_subject_and_safe_badges(tmp_path, question):
    assert extract_subject(question) is None
    pilot = make_pilot(tmp_path)
    response = ask(pilot, question)
    assert response.presentation_mode == "QUESTION_TOO_BROAD"
    assert response.failure_category == "QUESTION_TOO_BROAD"
    assert response.evidence_states == ["UNSUPPORTED", "NEEDS_NARROWING"]
    assert response.suggestions
    assert "named-subject" not in response.model_dump_json().lower()
    assert not response.evidence
    d = record(pilot, response)["diagnostics"]
    assert d["extracted_subject"] is None and d["resolved_subject"] is None
    assert d["presentation_failure_category"] == "QUESTION_TOO_BROAD"


@pytest.mark.parametrize(
    "question",
    [
        "Where is my financial data still incomplete?",
        "What parts of 2026 are incomplete?",
    ],
)
def test_coverage_intent_shows_coverage_not_subject(question):
    response = render(question, evidence(2026))
    assert response.presentation_mode == "COVERAGE"
    assert "Imported bank data" in response.direct_answer
    assert "human-reviewed" in response.direct_answer
    assert "unresolved" in response.direct_answer
    assert "document" in str(response.optional_details["main_limitations"]).lower()
    assert "named-subject" not in response.model_dump_json().lower()


def test_review_intent_without_merchant():
    response = render("What transactions still need human review?", evidence(2026))
    assert response.presentation_mode == "TRANSACTION_REVIEW"
    assert extract_subject("What transactions still need human review?") is None


@pytest.mark.parametrize(
    "question,mode",
    [
        ("What evidence do we have for Elenia?", "NAMED_SUBJECT"),
        ("How much did I pay Vattenfall in 2026?", "FINANCIAL_TOTAL"),
        ("What evidence do we have for K-Rauta?", "NAMED_SUBJECT"),
        ("Can I deduct K-Rauta purchases?", "TAX_BOUNDARY"),
    ],
)
def test_named_matrix_requires_real_resolution(tmp_path, question, mode):
    resolution = resolved_fixture(question)
    assert eligible_subject(question, resolution)
    pilot = make_pilot(tmp_path, Model())
    pilot.subject_loader = lambda q, sf: resolution
    response = ask(pilot, question)
    assert response.presentation_mode == mode
    assert response.failure_category is None
    if mode == "TAX_BOUNDARY":
        assert "does not decide tax deductibility" in response.direct_answer


@pytest.mark.parametrize(
    "subject",
    [
        "finances",
        "property",
        "forestry",
        "electricity",
        "transactions",
        "2026",
        "documents",
        "financial data",
        "imported records",
        "BANK_CASH_FLOW",
        "TIMBER_INCOME",
        "MAINTENANCE",
        "query_transactions",
        "get_invoice_reconciliation",
        "PROPERTY / FORESTRY",
    ],
)
def test_generic_phrases_cannot_be_entities(subject):
    from tapio.pilot.named_subject import retrieve_subject

    question = f"What evidence do we have for {subject}?"
    assert extract_subject(question) is None

    def forbidden():
        pytest.fail("Generic phrases must not start subject resolution or query the database")

    assert retrieve_subject(question, forbidden) is None


@pytest.mark.parametrize("mutation", ["missing", "different", "unfinished", "invalid_status"])
def test_subject_eligibility_rejects_missing_or_unrelated_resolution(mutation):
    question = "What evidence do we have for Elenia?"
    resolution = resolved_fixture(question)
    if mutation == "missing":
        resolution = None
    elif mutation == "different":
        resolution = resolved_fixture("What evidence do we have for K-Rauta?")
    elif mutation == "unfinished":
        resolution["trace"]["inventory_queried"] = False
    else:
        resolution["status"] = "INCOMPLETE"
    assert not eligible_subject(question, resolution)
    assert mode_for(question, {}, resolution) == "EVIDENCE_INCOMPLETE"


def test_unknown_explicit_entity_is_not_a_generic_noun():
    question = "What evidence do we have for Unseen Merchant XYZ?"
    data = resolved_fixture(question)
    data.update(resolve_subject(data["request"]["text"], []))
    assert data["canonical_subject"] is None
    assert eligible_subject(question, data)
    assert mode_for(question, {}, data) == "NAMED_SUBJECT"


def test_unrelated_subject_result_cannot_override_broad_intent():
    data = resolved_fixture("What evidence do we have for Elenia?")
    before = deepcopy(data)
    assert mode_for("Give me an overview of my finances in 2026.", {}, data) == "QUESTION_TOO_BROAD"
    assert data == before


def test_planner_intent_used_when_question_has_no_specific_display_words():
    assert (
        mode_for("What remains?", {"EFFECTIVE_PLAN": {"question_type": "coverage"}}) == "COVERAGE"
    )
    assert (
        mode_for("What remains?", {"EFFECTIVE_PLAN": {"question_type": "review"}})
        == "TRANSACTION_REVIEW"
    )


def test_ambiguous_identity_badge_requires_actual_ambiguous_resolution(tmp_path):
    q = "What evidence do we have for Example?"
    resolution = resolved_fixture(q)
    resolution.update(status="AMBIGUOUS_IDENTITY", canonical_subject=None, identity=None)
    pilot = make_pilot(tmp_path)
    pilot.subject_loader = lambda question, sf: resolution
    response = ask(pilot, q)
    assert response.presentation_mode == "NAMED_SUBJECT"
    assert response.evidence_states == ["AMBIGUOUS", "HUMAN_REVIEW_REQUIRED"]


@pytest.mark.parametrize("kind", ["provider", "plan", "retrieval"])
def test_failures_precede_subject_presentation(tmp_path, kind):
    from test_pilot import Registry

    class BrokenModel(Model):
        async def generate_coordinated(self, *args, **kwargs):
            if kind == "provider":
                raise ValueError("LIVE_PROVIDER_UNAVAILABLE")
            if kind == "plan":
                return {"plan": {}}
            return await super().generate_coordinated(*args, **kwargs)

    class BrokenRegistry(Registry):
        async def call(self, name, args, **kwargs):
            raise RuntimeError("synthetic execution failure")

    pilot = make_pilot(
        tmp_path, BrokenModel(), registry=BrokenRegistry() if kind == "retrieval" else None
    )

    def forbidden(*args):
        pytest.fail("A failed accepted path must not enter subject retrieval")

    pilot.subject_loader = forbidden
    response = ask(pilot, "What evidence do we have for Elenia?")
    assert (
        response.failure_category
        == {
            "provider": "INFRASTRUCTURE_UNAVAILABLE",
            "plan": "PLAN_INVALID",
            "retrieval": "AGENT_EXECUTION_ERROR",
        }[kind]
    )
    assert response.presentation_mode != "NAMED_SUBJECT"
