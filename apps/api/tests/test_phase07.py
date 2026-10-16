"""Synthetic Phase 07 contracts; no live provider or holdout question exposure."""

import asyncio
import hashlib
import inspect
import json
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from apps.api.app.services.financial_summary import authoritative_label
from data_pipeline.labels.contracts import review_facts
from tapio.agent.acceptance.audit import coverage_status, filename_interval, priority
from tapio.agent.acceptance.evaluate import (
    CONFIGS,
    DATA,
    decision,
    load_cases,
    meets_development_gate,
)
from tapio.agent.acceptance.planning import (
    EvidencePlan,
    PlanningModel,
    infer_requirements,
    missing_requirements,
    selected_views,
)
from tapio.agent.evaluation import CASES
from tapio.agent.model import ModelTurn
from tapio.agent.providers.openai import OpenAIModel


def test_bank_filename_interval_is_only_claim():
    assert filename_interval("tapahtumat20260101-20261007.csv") == ["2026-01-01", "2026-10-07"]
    assert filename_interval("unknown.csv") is None


@pytest.mark.parametrize("interval", [None, ["2026-01-01", "2026-12-31"]])
def test_unknown_coverage_not_promoted(interval):
    assert coverage_status(interval) == "UNKNOWN_COVERAGE"


@pytest.mark.parametrize(
    "amount,category,context,links,pairs,expected",
    [
        ("-700", "UNKNOWN", None, [], [], "P1"),
        ("10", "UNKNOWN", None, [], [], "P1"),
        ("-10", "UNKNOWN", None, [{}], [], "P1"),
        ("-10", "UNKNOWN", None, [], [{}], "P1"),
        ("-10", "FUEL", None, [], [], "P3"),
        ("-10", "TRANSFER", None, [], [], "P1"),
        ("-10", "OTHER", "FORESTRY", [], [], "P1"),
    ],
)
def test_review_priority(amount, category, context, links, pairs, expected):
    t = NS(
        amount=Decimal(amount),
        category=category,
        business_context=NS(value=context) if context else None,
        normalized_counterparty="Synthetic",
    )
    assert priority(t, links, pairs)[0] == expected


def test_human_authority():
    assert authoritative_label(NS(review_status="UNREVIEWED", confirmed_category="TAX")) == (
        "UNKNOWN",
        "UNKNOWN",
        False,
    )


def test_review_privacy_projection():
    from datetime import date
    from uuid import uuid4

    t = NS(
        id=uuid4(),
        booking_date=date(2026, 1, 1),
        amount=Decimal("-1"),
        direction=NS(value="outgoing"),
        normalized_counterparty="Synthetic",
        ultimate_recipient=None,
        message="ARCHIVE-SECRET",
        transaction_type_code="1",
        raw_source={"Arkistointitunnus": "ARCHIVE-SECRET"},
    )
    assert "ARCHIVE-SECRET" not in json.dumps(review_facts(t))
    assert "raw_source" not in review_facts(t)


def valid_plan():
    return dict(
        question_type="domain_cost",
        required_views=["BANK_CASH_FLOW"],
        required_contexts=["PROPERTY"],
        needs_coverage_check=True,
        needs_tax_boundary=False,
    )


@pytest.mark.parametrize(
    "extra", [{"amount": 100}, {"answer": "made up"}, {"question_type": "arithmetic"}]
)
def test_evidence_plan_forbids_facts(extra):
    with pytest.raises(ValidationError):
        EvidencePlan(**{**valid_plan(), **extra})


@pytest.mark.parametrize(
    "question,required",
    [
        (
            "Forestry financial performance",
            {"BANK_CASH_FLOW", "DOCUMENTS", "RECONCILIATION", "FORESTRY_SALE"},
        ),
        ("Property costs", {"BANK_CASH_FLOW", "COVERAGE"}),
        ("Ambiguous payment", {"DOCUMENTS", "RECONCILIATION"}),
        ("Can I deduct expenses?", {"BANK_CASH_FLOW", "COVERAGE"}),
        ("Estimate missing months", {"COVERAGE"}),
        ("Property electricity costs", {"BANK_CASH_FLOW", "ENERGY"}),
    ],
)
def test_general_required_evidence(question, required):
    assert required <= set(infer_requirements(question)["required_views"])


def test_no_question_specific_runtime_lookup():
    from tapio.agent.acceptance import planning

    source = inspect.getsource(planning)
    assert "588.07" not in source and "Oikea" not in source and "datasets" not in source


def test_empty_invoice_is_source_absence_not_missing_view():
    assert {"DOCUMENTS", "RECONCILIATION"} <= selected_views(
        [dict(tool="find_invoices", ok=True, data={"items": []})]
    )


def test_missing_reconciliation_fails():
    req = infer_requirements("ambiguous refund")
    assert "DIRECT_RECONCILIATION" in missing_requirements(req, [], [])


def test_phase06_questions_unchanged():
    dev = load_cases("development")
    assert [
        (c["id"], c["question"], c["required_tools"], c["message_key"]) for c in dev[:14]
    ] == CASES


def test_holdout_sealed_without_loading_expectations():
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert hashlib.sha256((DATA / "holdout.json").read_bytes()).hexdigest() == manifest["holdout"]
    assert "holdout" not in inspect.getsource(PlanningModel)


def test_config_isolation():
    assert CONFIGS["A"][0] != CONFIGS["B"][0] == CONFIGS["C"][0]


def test_stronger_adapter_preserves_native_tool_conversion():
    captured = []

    def transport(payload):
        captured.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "finish_evidence_answer",
                                    "arguments": '{"references":[],"message_key":"unsupported"}',
                                }
                            }
                        ]
                    },
                }
            ]
        }

    model = OpenAIModel("synthetic", model=CONFIGS["B"][0], transport=transport)
    asyncio.run(model.generate_with_tools([{"role": "system", "content": "policy"}], []))
    assert captured[0]["model"] == CONFIGS["B"][0] and captured[0]["store"] is False
    assert captured[0]["max_completion_tokens"] == 3000


def test_no_arithmetic_model_fields():
    with pytest.raises(ValidationError):
        ModelTurn(amount="123.45")


def test_audit_has_no_source_mutation():
    from tapio.agent.acceptance import audit

    source = inspect.getsource(audit.build_audit)
    assert "s.add(" not in source and "s.commit(" not in source and "s.delete(" not in source


def test_acceptance_cannot_ignore_critical_failure():
    rows = [
        {"acceptance": {"EVIDENCE_COMPLETE": True, "critical": False, "unsupported_claims": False}}
        for _ in range(20)
    ]
    rows[0] = {
        "acceptance": {"EVIDENCE_COMPLETE": False, "critical": True, "unsupported_claims": False}
    }
    assert not meets_development_gate(rows)
    assert decision(rows, []) == "NOT_READY"


def test_holdout_required_even_after_development_pass():
    rows = [
        {"acceptance": {"EVIDENCE_COMPLETE": True, "critical": True, "unsupported_claims": False}}
        for _ in range(20)
    ]
    assert meets_development_gate(rows)
    assert decision(rows, []) == "NOT_READY"


def test_empty_answer_has_no_supported_evidence_state():
    from tapio.agent.acceptance.planning import evidence_states

    assert "SUPPORTED" not in evidence_states({"status": "COMPLETE", "results": []})


def test_wrong_bank_context_is_incomplete():
    req = infer_requirements("Property costs")
    result = {
        "tool": "summarize_finances",
        "ok": True,
        "data": {"context_filter": "PERSONAL", "bank_source_coverage": {"status": "UNKNOWN"}},
    }
    assert "REQUIRED_BANK_CONTEXT" in missing_requirements(req, [result], [])
