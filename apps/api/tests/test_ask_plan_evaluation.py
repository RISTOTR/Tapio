"""Evaluation harness checks never call a live provider."""

import asyncio

import pytest

from scripts.evaluate_ask_plans import evaluate, mismatches
from tapio.pilot.query_plan import Constraint, QueryPlan, validate_plan


def test_exact_scope_rejects_extra_or_missing_filters():
    plan = QueryPlan(intent="TRANSACTION_SEARCH", contexts=["FORESTRY", "PERSONAL"])
    assert mismatches(plan, {"contexts": ["FORESTRY"]}) == ["contexts"]
    assert mismatches(plan, {"categories": ["TRAVEL"]}) == ["categories"]
    assert not mismatches(plan, {"contexts": ["PERSONAL", "FORESTRY"]})


def test_provider_failure_report_does_not_disclose_exception(capsys):
    class Model:
        def transport(self, payload):
            raise ValueError("synthetic-sensitive-provider-detail")

    result = asyncio.run(evaluate(Model(), [{"id": "failure", "question": "test", "expected": {}}]))
    assert result[0]["status"] == "ERROR"
    assert "synthetic-sensitive-provider-detail" not in capsys.readouterr().out


@pytest.mark.parametrize("span", ['"forestry"', "'forestry'", "“forestry”", "forestry"])
def test_verbatim_constraint_quote_wrappers_are_accepted(span):
    plan = QueryPlan(
        intent="TRANSACTION_SEARCH",
        contexts=["FORESTRY"],
        constraints=[Constraint(text=span, field="contexts")],
    )
    result = validate_plan("Forestry expenses in June 2026", plan)
    assert not result.clarification
    assert result.periods[0].date_from.isoformat() == "2026-06-01"


@pytest.mark.parametrize("span", ['"personal"', '""', '"forestry', '"forest ry"'])
def test_quote_handling_still_rejects_invented_constraints(span):
    plan = QueryPlan(
        intent="TRANSACTION_SEARCH",
        contexts=["FORESTRY"],
        constraints=[Constraint(text=span, field="contexts")],
    )
    with pytest.raises(ValueError, match="not present"):
        validate_plan("Forestry expenses in June 2026", plan)


def test_receipt_lookup_does_not_bypass_transaction_scope():
    plan = QueryPlan(
        intent="ATTACHMENT_ANALYSIS",
        action="ANALYZE_ATTACHMENTS",
        evidence_requirements=["ATTACHMENT", "RECEIPT"],
    )
    result = validate_plan("Find Gmail receipts for personal travel expenses in June 2026", plan)
    assert result.intent == "TRANSACTION_SEARCH" and result.action == "FIND_EVIDENCE"
    assert set(result.evidence_requirements) == {"EMAIL", "RECEIPT"}
    assert result.contexts == ["PERSONAL"] and result.categories == ["TRAVEL"]
    explicit = validate_plan("Analyze receipt PDF attachments for expenses in June 2026", plan)
    assert explicit.intent == "ATTACHMENT_ANALYSIS"
