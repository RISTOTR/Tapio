"""Offline failure UX; all model/registry responses below are synthetic."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from test_pilot import Model, Registry, ask, make_pilot, session
from test_pilot_diagnostics import record

from tapio.agent.mandatory import EvidenceView
from tapio.pilot.contracts import Feedback
from tapio.pilot.diagnostics import exception_detail
from tapio.pilot.failures import classify_failure, suggestions, unconstrained_overview
from tapio.pilot.presentation import unsupported


def test_healthy_broad_question_does_not_invoke_model_and_saves_feedback(tmp_path):
    pilot = make_pilot(tmp_path)
    response = ask(pilot, "Give me a complete overview of all my finances and taxes")
    assert response.failure_category == "QUESTION_TOO_BROAD"
    assert response.evidence_states == ["UNSUPPORTED", "NEEDS_NARROWING"]
    assert response.session.model_calls == 0
    assert len(response.suggestions) == 3
    assert "unavailable" not in response.answer
    d = record(pilot, response)["diagnostics"]
    assert d["database_available"] is True
    assert not d["planner_called"] and not d["retrieval_attempted"]
    for rating in ("GOOD", "INCOMPLETE", "WRONG_EVIDENCE", "UNCLEAR", "OTHER"):
        pilot.history.feedback(response.session.id, Feedback(rating=rating))
    assert (
        len(list((pilot.history.directory(response.session.id) / "feedback").glob("*.json"))) == 5
    )


@pytest.mark.parametrize(
    "question",
    [
        "How much forestry income did I receive in 2025?",
        "What were my main property expenses in 2026?",
        "How much did I pay Elenia in 2026?",
        "What is my overall bank income in 2026?",
    ],
)
def test_yearly_questions_keep_supported_path(tmp_path, question):
    assert not unconstrained_overview(question)
    pilot = make_pilot(tmp_path)
    if "Elenia" in question:
        from test_pilot_routing import resolved_fixture

        pilot.subject_loader = lambda q, sf: resolved_fixture(q)
    response = ask(pilot, question)
    assert response.failure_category is None
    assert response.session.model_calls == 2
    assert response.coverage.status == "DETERMINED"


def test_database_failure_has_its_own_badge(tmp_path):
    def refuse(*args):
        raise OperationalError("private sql", {}, Exception("connection refused"))

    pilot = make_pilot(tmp_path, check=refuse)
    response = ask(pilot)
    assert response.failure_category == "INFRASTRUCTURE_UNAVAILABLE"
    assert response.evidence_states == ["UNAVAILABLE"]
    assert "local database is offline" in response.answer
    assert record(pilot, response)["diagnostics"]["database_available"] is False


class PartialRegistry(Registry):
    async def call(self, name, args, **kwargs):
        if name == "list_documents":
            return {"ok": False, "tool": name, "error": {"code": "MISSING_REQUIRED_EVIDENCE"}}
        return await super().call(name, args, **kwargs)


def test_partial_retrieval_reports_coverage_without_releasing_unvalidated_facts(tmp_path):
    pilot = make_pilot(
        tmp_path, Model(views=["BANK_CASH_FLOW", "DOCUMENTS"]), registry=PartialRegistry()
    )
    response = ask(pilot, "Show bank and document evidence for 2026")
    assert response.failure_category == "EVIDENCE_INCOMPLETE"
    assert response.evidence_states == ["PARTIAL_COVERAGE", "HUMAN_REVIEW_REQUIRED"]
    assert "some relevant evidence" in response.answer
    assert "Incomplete evidence areas: documents" in response.coverage_note
    assert "bank cash flow" in response.coverage_note
    assert not response.evidence and not response.optional_details
    assert "unavailable" not in response.answer
    d = record(pilot, response)["diagnostics"]
    assert d["database_available"] is True and d["retrieval_attempted"]
    assert d["completeness_result"] == "EVIDENCE_INCOMPLETE"
    assert d["retrieval_calls"]


@pytest.mark.parametrize("provider_raises", [False, True])
def test_invalid_plan_is_private_and_needs_narrowing(tmp_path, provider_raises):
    class Invalid(Model):
        async def generate_coordinated(self, *args, **kwargs):
            if provider_raises:
                raise ValueError("INVALID_COORDINATED_PROVIDER_OUTPUT")
            return {"plan": {"secret": "private raw plan"}}

    pilot = make_pilot(tmp_path, Invalid())
    response = ask(pilot)
    assert response.failure_category == "PLAN_INVALID"
    assert response.suggestions
    assert "schema" not in response.answer.lower() and "JSON" not in response.answer
    assert "private raw plan" not in response.model_dump_json()
    assert record(pilot, response)["diagnostics"]["plan_validation"] == "INVALID"


def test_validated_multi_view_plan_limit_is_broad_without_keywords():
    views = ["BANK_CASH_FLOW", "DOCUMENTS", "REVIEW_COVERAGE"]
    coordinator = SimpleNamespace(
        requirements=[SimpleNamespace(view=EvidenceView(v)) for v in views],
        errors=[{"code": "MANDATORY_SOURCE_CALL_LIMIT"}],
        state=lambda: {"status": "EVIDENCE_INCOMPLETE"},
    )
    category = classify_failure(
        {"category": "EVIDENCE_INCOMPLETE", "stage": "FINAL_VALIDATION"},
        {"planner_called": True, "database_available": True},
        coordinator,
        {},
    )
    assert category == "QUESTION_TOO_BROAD"


@pytest.mark.parametrize(
    "category",
    [
        "QUESTION_TOO_BROAD",
        "UNSUPPORTED_SCOPE",
        "EVIDENCE_INCOMPLETE",
        "PLAN_INVALID",
        "AGENT_EXECUTION_ERROR",
        "VALIDATION_ERROR",
        "SAFETY_REJECTION",
    ],
)
def test_non_infrastructure_fallback_never_claims_offline(category):
    response = unsupported(session(), category, failure_code="PILOT_EVIDENCE_INCOMPLETE")
    assert response.failure_category != "INFRASTRUCTURE_UNAVAILABLE"
    assert "evidence source is unavailable" not in response.answer
    assert "database is offline" not in response.answer
    assert not response.evidence


def test_missing_final_handles_still_fail_closed(tmp_path):
    response = ask(make_pilot(tmp_path, Model(bad=True)))
    assert response.failure_category == "VALIDATION_ERROR"
    assert response.evidence_state == "UNSUPPORTED"
    assert not response.evidence


def test_suggestions_are_fixed_templates_not_model_prose():
    items = suggestions("private irrelevant text forestry 2025")
    assert items[0] == "What forestry income reached my bank account in 2025?"
    assert all("private irrelevant" not in s for s in items)
    assert len(items) == len(set(items)) == 3


def test_provider_outage_can_coexist_with_healthy_database(tmp_path):
    class Down(Model):
        async def generate_coordinated(self, *args, **kwargs):
            raise ValueError("LIVE_PROVIDER_HTTP_503")

    pilot = make_pilot(tmp_path, Down())
    response = ask(pilot)
    assert response.failure_category == "INFRASTRUCTURE_UNAVAILABLE"
    assert "model service" in response.answer and "database" not in response.answer
    assert record(pilot, response)["diagnostics"]["database_available"] is True


def test_unsupported_scope_does_not_claim_missing_infrastructure():
    detail = exception_detail(ValueError("UNSUPPORTED_QUESTION"), "QUESTION_PERIOD")
    response = unsupported(session(), detail["category"])
    assert response.failure_category == "UNSUPPORTED_SCOPE"
    assert "validated read-only evidence path" in response.answer
    assert response.suggestions


def test_database_statement_error_does_not_mean_database_offline():
    detail = exception_detail(
        OperationalError("private sql", {}, Exception("statement timeout")), "EVIDENCE_RETRIEVAL"
    )
    assert detail["category"] == "AGENT_EXECUTION_ERROR"


def test_empty_successful_result_does_not_claim_relevant_evidence():
    from tapio.pilot.failures import has_partial_evidence

    coordinator = SimpleNamespace(
        ledger=SimpleNamespace(results=[{"ok": True, "data": {"items": [], "truncated": False}}])
    )
    assert not has_partial_evidence(coordinator)
    response = unsupported(session(), "EVIDENCE_INCOMPLETE", partial_found=False)
    assert "found some relevant evidence" not in response.answer


def test_unexpected_retrieval_fault_remains_execution_error(tmp_path):
    class BrokenRegistry(Registry):
        async def call(self, name, args, **kwargs):
            raise RuntimeError("private failure details")

    pilot = make_pilot(tmp_path, registry=BrokenRegistry())
    response = ask(pilot)
    assert response.failure_category == "AGENT_EXECUTION_ERROR"
    assert "private failure details" not in response.answer
    assert record(pilot, response)["diagnostics"]["database_available"] is True
