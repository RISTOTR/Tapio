"""Small feedback-derived acceptance set; synthetic data, no model/network/private data.

Each case specifies a question, expected current-state IDs and deterministic total.
The proposed plan is fixed: this tests scope repair/retrieval/answer routing, not live
LLM interpretation accuracy. Add a failing case before fixing each new feedback item.
"""

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tapio.pilot import planned_answers as answers
from tapio.pilot import planned_retrieval as retrieval
from tapio.pilot.query_plan import QueryPlan, validate_plan

TODAY = date(2026, 11, 18)
CASES = [
    (
        "cross-account-travel",
        "Forestry travel expenses in June 2026",
        ["FORESTRY"],
        ["TRAVEL"],
        "OUTFLOW",
        "TOTAL",
        ["bank", "sampo"],
        "42.35",
    ),
    (
        "personal-stays-separate",
        "Personal travel expenses in June 2026",
        ["PERSONAL"],
        ["TRAVEL"],
        "OUTFLOW",
        "TOTAL",
        ["personal"],
        "90.00",
    ),
    (
        "category-stays-separate",
        "Forestry maintenance expenses in June 2026",
        ["FORESTRY"],
        ["MAINTENANCE"],
        "OUTFLOW",
        "TOTAL",
        ["maintenance"],
        "50.00",
    ),
    (
        "tax-traceable",
        "Forestry travel tax deduction suggestions in June 2026",
        ["FORESTRY"],
        ["TRAVEL"],
        "OUTFLOW",
        "TAX_SUGGESTION",
        ["bank", "sampo"],
        "42.35",
    ),
    (
        "net-includes-refund",
        "Net forestry travel cash flow in June 2026",
        ["FORESTRY"],
        ["TRAVEL"],
        "NET",
        "TOTAL",
        ["bank", "sampo", "refund"],
        "-37.35",
    ),
    (
        "empty-does-not-broaden",
        "Property travel expenses in June 2026",
        ["PROPERTY"],
        ["TRAVEL"],
        "OUTFLOW",
        "TOTAL",
        [],
        None,
    ),
]


def pair(identity, amount, context="FORESTRY", category="TRAVEL", day="2026-06-01", reviewed=True):
    tx = SimpleNamespace(
        id=identity,
        booking_date=date.fromisoformat(day),
        amount=Decimal(amount),
        currency="EUR",
        ultimate_recipient=None,
        normalized_counterparty="Example transport",
        raw_counterparty="Example transport",
        source_file=identity + ".csv",
        message="Synthetic travel payment",
        reference=None,
        source_namespace="sampo_csv:synthetic" if identity == "sampo" else "bank:synthetic",
    )
    review = (
        SimpleNamespace(
            id="review-" + identity,
            review_status="REVIEWED",
            confirmed_category=category,
            confirmed_business_context=context,
        )
        if reviewed
        else None
    )
    return tx, review


@pytest.mark.parametrize(
    "case_id,question,contexts,categories,metric,action,expected_ids,total",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_feedback_acceptance_case(
    monkeypatch,
    tmp_path,
    case_id,
    question,
    contexts,
    categories,
    metric,
    action,
    expected_ids,
    total,
):
    pairs = [
        pair("bank", "-12.10"),
        pair("sampo", "-30.25", day="2026-06-30"),
        pair("personal", "-90.00", context="PERSONAL"),
        pair("maintenance", "-50.00", category="MAINTENANCE"),
        pair("refund", "5.00"),
        pair("before", "-100", day="2026-05-31"),
        pair("after", "-100", day="2026-07-01"),
        pair("unreviewed", "-200", reviewed=False),
    ]
    monkeypatch.setattr(retrieval, "current_classified_transactions", lambda db, periods: pairs)
    monkeypatch.setattr(retrieval, "source_text_fields", lambda tx: {"message": tx.message})
    db = SimpleNamespace(execute=lambda query: [])
    monkeypatch.setattr(answers, "load_transactions", lambda p: retrieval.transactions(db, p))

    async def forbidden(*args, **kwargs):
        pytest.fail("Local structured question must not invoke Gmail")

    monkeypatch.setattr(answers, "gmail_lookup", forbidden)
    proposed = QueryPlan(
        intent="TRANSACTION_SEARCH",
        contexts=contexts,
        categories=categories,
        metric=metric,
        action=action,
    )
    plan = validate_plan(question, proposed, TODAY)
    assert not plan.clarification
    assert [(p.date_from, p.date_to) for p in plan.periods] == [
        (date(2026, 6, 1), date(2026, 6, 30))
    ]
    result = asyncio.run(answers.execute(None, plan, question, None, tmp_path))
    records = result.supporting_records
    assert [r["transaction_id"] for r in records] == expected_ids
    if total is not None:
        assert any(total + " EUR" in line for line in result.relevant_breakdown)
    else:
        assert "No transactions satisfy all requested filters" in result.answer
    assert not result.limitations
    for r in records:
        assert r["category"] in categories and r["business_context"] in contexts
        assert r["classification_provenance"] == "review-" + r["transaction_id"]
        assert r["source_file"] == r["transaction_id"] + ".csv"
        assert r["booking_date"] and r["amount"] and r["counterparty"] and r["reason"]
        assert r["tax_treatment"] is None
    if action == "TAX_SUGGESTION":
        assert all(r["suggestion"] == "Tax review candidate" for r in records)
        assert "disclaimer" not in result.answer.lower()
        assert "consult" not in result.answer.lower()
