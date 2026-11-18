"""Feedback regression groups: scope loss, routing, current authority, and evidence coverage."""

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tapio.pilot import planned_answers as answers
from tapio.pilot import planned_retrieval as retrieval
from tapio.pilot.query_plan import QueryPlan, explicit_periods, interpret, validate_plan

TODAY = date(2026, 11, 11)


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "How much solar output did I have in July 2026 and July 2025?",
            [(2026, 7, 7), (2025, 7, 7)],
        ),
        ("Solar production last July and this July", [(2025, 7, 7), (2026, 7, 7)]),
        ("Compare solar production from May through August 2026", [(2026, 5, 8)]),
        ("What forestry travel expenses did I have in May and June 2026?", [(2026, 5, 6)]),
        (
            "comparison of solarpanel output in may - august 2025 vs. may - august 2026",
            [(2025, 5, 8), (2026, 5, 8)],
        ),
        ("Elenia 10/2025", [(2025, 10, 10)]),
        ("May-August 2025 vs 2026", [(2025, 5, 8), (2026, 5, 8)]),
    ],
)
def test_explicit_period_constraints(question, expected):
    periods = explicit_periods(question, TODAY)
    assert [(p.date_from.year, p.date_from.month, p.date_to.month) for p in periods] == expected


@pytest.mark.parametrize(
    "question",
    [
        "Which forestry journeys to Finland in 2026 might be tax deductible?",
        "Find transaction of my forest tax deductible journey to Finland in 2026",
    ],
)
def test_tax_travel_scope_repaired_without_broadening(question):
    p = validate_plan(
        question, QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Finland"]), TODAY
    )
    assert p.contexts == ["FORESTRY"] and p.categories == ["TRAVEL"]
    assert p.locations == ["Finland"] and not p.merchants
    assert p.action == "TAX_SUGGESTION"
    assert p.periods[0].date_from == date(2026, 1, 1)


def test_forestry_journey_without_year_asks_one_clarification():
    p = validate_plan("Forestry journey to Finland", QueryPlan(intent="TRANSACTION_SEARCH"), TODAY)
    assert p.clarification and p.contexts == ["FORESTRY"] and p.categories == ["TRAVEL"]


def test_missing_year_not_silently_invented():
    with pytest.raises(ValueError, match="Which year"):
        explicit_periods("Compare solar production from May through August", TODAY)


def test_generic_tax_request_does_not_include_all_contexts():
    p = validate_plan(
        "Give me tax deduction suggestions for 2026", QueryPlan(intent="TRANSACTION_SEARCH"), TODAY
    )
    assert p.clarification and not p.contexts


def plan():
    return validate_plan(
        "Give me possible forestry deductions for 2026",
        QueryPlan(intent="TRANSACTION_SEARCH"),
        TODAY,
    )


def row(**kw):
    return {
        "transaction_id": "synthetic-id",
        "booking_date": "2026-06-01",
        "amount": "-10.00",
        "currency": "EUR",
        "business_context": "FORESTRY",
        "category": "TRAVEL",
        **kw,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"business_context": "PERSONAL"},
        {"business_context": "PROPERTY"},
        {"booking_date": "2025-06-01"},
        {"amount": "10"},
    ],
)
def test_negative_scope_assertions(change):
    assert not retrieval.included(row(**change), plan())


def test_travel_category_not_dropped():
    p = plan().model_copy(update={"categories": ["TRAVEL"]})
    assert not retrieval.included(row(category="MAINTENANCE"), p)


def test_tax_answer_traceable_no_boilerplate():
    result = answers.transaction_answer(plan(), [row()], [])
    assert result.supporting_records[0]["transaction_id"] == "synthetic-id"
    assert "10.00 EUR" in result.relevant_breakdown[0]
    assert not result.limitations
    assert "disclaimer" not in result.answer and "does not decide" not in result.answer


def test_missing_months_are_explicit_and_period_preserved(monkeypatch):
    p = QueryPlan(
        intent="ENERGY", metric="SOLAR_EXPORT", periods=explicit_periods("May-August 2026", TODAY)
    )
    from tapio.tools.errors import ErrorCode, ToolFailure

    class Queries:
        def __init__(self, **kw):
            pass

        def energy(self, q):
            if q.date_from.month != 8:
                raise ToolFailure(ErrorCode.INCOMPLETE_COVERAGE)
            return SimpleNamespace(
                date_from=q.date_from,
                date_to=q.date_to,
                model_dump=lambda **kw: {
                    "date_from": str(q.date_from),
                    "date_to": str(q.date_to),
                    "total": "12.50",
                    "metric": q.metric,
                },
            )

    monkeypatch.setattr(retrieval, "Queries", Queries)
    records, missing = retrieval.energy(p, None)
    result = answers.energy_answer(p, records, missing)
    assert result.failure_category == "PARTIAL_PERIOD_COVERAGE"
    assert len(missing) == 3 and "2026-05-01" in result.limitations[0]
    assert "2026-08-31" in result.answer and "available months only" in result.answer


def test_two_periods_imply_comparison_without_keyword():
    p = validate_plan(
        "July 2026 and July 2025 solar output",
        QueryPlan(intent="ENERGY", metric="SOLAR_EXPORT"),
        TODAY,
    )
    assert p.intent == "PERIOD_COMPARISON" and len(p.periods) == 2


def test_llm_interprets_code_repairs_dates():
    proposed = QueryPlan(
        intent="ENERGY", metric="SOLAR_EXPORT", periods=explicit_periods("August 2026", TODAY)
    )

    class Model:
        usage = []

        def transport(self, payload):
            assert payload["tool_choice"]["function"]["name"] == "submit_query_plan"
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_query_plan",
                                        "arguments": proposed.model_dump_json(),
                                    }
                                }
                            ]
                        },
                    }
                ]
            }

    p = asyncio.run(interpret(Model(), "solar output May through August 2026", today=TODAY))
    assert p.periods[0].date_from.month == 5


def test_tax_local_evidence_never_searches_gmail(monkeypatch, tmp_path):
    monkeypatch.setattr(answers, "load_transactions", lambda p: ([row()], []))

    async def forbidden(*args):
        pytest.fail("Unnecessary Gmail search")

    monkeypatch.setattr(answers, "gmail_lookup", forbidden)
    result = asyncio.run(answers.execute(None, plan(), "forestry deductions 2026", None, tmp_path))
    assert result.supporting_records == [row()]


def test_explicit_gmail_is_bounded_and_provenance_visible(monkeypatch, tmp_path):
    p = plan().model_copy(
        update={"evidence_requirements": ["EMAIL", "RECEIPT"], "merchants": ["Shop"]}
    )
    monkeypatch.setattr(answers, "load_transactions", lambda p: ([row()], []))

    async def lookup(search, directory):
        assert "from:Shop" in search.query and "before:2027/01/01" in search.query
        return [
            {"source": "Gmail read-only", "reference": "message-1", "subject": "Receipt"}
        ], False

    monkeypatch.setattr(answers, "gmail_lookup", lookup)
    result = asyncio.run(
        answers.execute(
            None, p, "Which forestry expenses have receipts/invoices in Gmail?", None, tmp_path
        )
    )
    assert any(s["label"] == "Gmail read-only" for s in result.sources)
    assert result.supporting_records[0]["business_context"] == "FORESTRY"
    assert "not confirmed" in result.supporting_records[-1]["evidence_status"]


def test_attachment_failure_does_not_dump_text(monkeypatch, tmp_path):
    async def analyze(*args):
        return answers.response(
            "Read PDF",
            records=[
                {
                    "source": "Email PDF attachment",
                    "filename": "receipt.pdf",
                    "reference": "message-1",
                    "excerpt": "PRIVATE FULL TEXT",
                }
            ],
        )

    monkeypatch.setattr(answers, "analyze_attachments", analyze)
    p = QueryPlan(intent="ATTACHMENT_ANALYSIS", action="ANALYZE_ATTACHMENTS")
    result = asyncio.run(
        answers.execute(
            None,
            p,
            "Read these attachments",
            {"records": [{"source": "Gmail read-only", "reference": "message-1"}]},
            tmp_path,
        )
    )
    assert result.failure_category == "ATTACHMENT_EVIDENCE_INSUFFICIENT"
    assert "PRIVATE FULL TEXT" not in result.model_dump_json()


def test_retrieval_enforces_every_filter_and_explains_inclusion(monkeypatch):
    from uuid import uuid4

    from apps.api.app.domain.models import Transaction

    txs = [
        Transaction(
            id=uuid4(),
            booking_date=date(2026, 6, 9),
            amount=Decimal("-20"),
            currency="EUR",
            normalized_counterparty="Finnair",
            message="Flight to Finland",
            source_file="synthetic.csv",
        )
        for _ in range(4)
    ]
    reviews = [
        SimpleNamespace(
            id=uuid4(),
            review_status="REVIEWED",
            confirmed_category=cat,
            confirmed_business_context=ctx,
        )
        for cat, ctx in [
            ("TRAVEL", "FORESTRY"),
            ("TRAVEL", "PERSONAL"),
            ("TRAVEL", "PROPERTY"),
            ("MAINTENANCE", "FORESTRY"),
        ]
    ]
    monkeypatch.setattr(
        retrieval,
        "current_classified_transactions",
        lambda *a: list(zip(txs, reviews, strict=True)),
    )
    db = SimpleNamespace(execute=lambda *a: [])
    p = validate_plan(
        "Which forestry journeys to Finland in 2026 might be tax deductible?",
        QueryPlan(intent="TRANSACTION_SEARCH"),
        TODAY,
    )
    rows, missing = retrieval.transactions(db, p)
    assert len(rows) == 1 and not missing
    assert rows[0]["transaction_id"] == str(txs[0].id)
    assert rows[0]["classification_provenance"] == str(reviews[0].id)
    assert rows[0]["tax_treatment"] is None and "FORESTRY" in rows[0]["reason"]


def test_unsupported_location_not_silently_dropped(monkeypatch):
    from uuid import uuid4

    from apps.api.app.domain.models import Transaction

    tx = Transaction(
        id=uuid4(),
        booking_date=date(2026, 6, 9),
        amount=Decimal("-20"),
        currency="EUR",
        normalized_counterparty="Paytrail",
        message="Payment",
        source_file="synthetic.csv",
    )
    review = SimpleNamespace(
        id=uuid4(),
        review_status="REVIEWED",
        confirmed_category="TRAVEL",
        confirmed_business_context="FORESTRY",
    )
    monkeypatch.setattr(retrieval, "current_classified_transactions", lambda *a: [(tx, review)])
    p = validate_plan(
        "forestry journey to Finland 2026", QueryPlan(intent="TRANSACTION_SEARCH"), TODAY
    )
    rows, missing = retrieval.transactions(SimpleNamespace(execute=lambda *a: []), p)
    assert not rows and missing[0]["missing"] == "Destination is not evidenced: Finland"
    result = answers.transaction_answer(p, rows, missing)
    assert result.failure_category == "MATCHING_RECORDS_INSUFFICIENT_EVIDENCE"


def test_gmail_sender_match_alone_does_not_establish_receipt_coverage(monkeypatch, tmp_path):
    p = plan().model_copy(
        update={
            "action": "FIND_EVIDENCE",
            "evidence_requirements": ["EMAIL", "RECEIPT"],
            "merchants": ["Shop"],
        }
    )
    monkeypatch.setattr(answers, "load_transactions", lambda p: ([row()], []))

    async def lookup(*args):
        return [
            {"source": "Gmail read-only", "reference": "message-1", "excerpt": "Unrelated receipt"}
        ], False

    monkeypatch.setattr(answers, "gmail_lookup", lookup)
    result = asyncio.run(
        answers.execute(None, p, "forestry receipts in Gmail 2026", None, tmp_path)
    )
    assert not any(r.get("transaction_id") for r in result.supporting_records)
    assert result.failure_category == "MATCHING_RECORDS_INSUFFICIENT_EVIDENCE"


def test_missing_energy_period_is_not_reported_as_zero():
    p = QueryPlan(
        intent="ENERGY", metric="SOLAR_EXPORT", periods=explicit_periods("July 2026", TODAY)
    )
    result = answers.energy_answer(p, [], ["2026-07-01 to 2026-07-31"])
    assert "0.000" not in result.answer
    assert "no measured coverage" in result.answer


def test_transport_modes_preserved_as_constraints():
    p = validate_plan(
        "Find my trip to Finland in May-June 2026. Flight, train and bus",
        QueryPlan(intent="TRANSACTION_SEARCH"),
        TODAY,
    )
    assert p.categories == ["TRAVEL"] and p.concepts == ["flight", "train", "bus"]
    assert p.locations == ["Finland"]
