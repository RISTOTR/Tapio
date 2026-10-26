"""Generic literal and period operations, synthetic sources and blocked providers."""

from datetime import date
from decimal import Decimal

import pytest
from test_pilot import ask
from test_pilot_transaction_search import bank, factory, search_pilot  # noqa: F401

from tapio.pilot.literal_search import literal_plan
from tapio.pilot.period_comparison import comparison_plan, retrieve_comparison
from tapio.pilot.transaction_search import retrieve_search


@pytest.mark.parametrize(
    "q",
    [
        "talletuskorko",
        "Find transactions containing talletuskorko",
        "Find talletuskorko transactions",
        "Show anything mentioning talletuskorko",
        "Search the bank data for talletuskorko.",
        "Do I have anything mentioning talletuskorko?",
    ],
)
def test_literal_paraphrases(q):
    assert literal_plan(q).terms == ["talletuskorko"]


@pytest.mark.parametrize(
    "term, count", [("odontólogo", 1), ("Synthetic Processor", 1), ("nonsensexyz", 0)]
)
def test_unseen_literal_route(term, count, tmp_path, bank):  # noqa: F811
    pilot = search_pilot(tmp_path, loader=lambda p, _: retrieve_search(p, bank))
    pilot.model_factory = lambda *args: pytest.fail("Literal route must not call a model")
    response = ask(pilot, f"Find transactions containing {term}")
    assert response.presentation_mode == "TRANSACTION_SEARCH"
    assert response.session.model_calls == 0
    assert len(response.optional_details["transactions"]) == count
    assert not response.optional_details.get("documents")
    if not count:
        assert response.evidence_states == ["SUPPORTED", "NO_MATCH"]


@pytest.mark.parametrize(
    "q",
    [
        "Compare my Vattenfall transactions in September 2025 with September 2026",
        "Compare Vattenfall September 2025 and September 2026",
        "How much more did I pay Vattenfall in Sep 2026 than Sep 2025?",
        "Compare September Vattenfall payments for 2025 and 2026.",
        "Did Vattenfall cost me more last September than the September before?",
    ],
)
def test_comparison_paraphrases(q):
    p = comparison_plan(q, today=date(2026, 10, 26))
    assert p.subject == "vattenfall"
    assert p.metric == "BANK_OUTFLOW"
    assert p.period_a.date_from == date(2025, 9, 1)
    assert p.period_b.date_to == date(2026, 9, 30)


@pytest.mark.parametrize("subject", ["Elenia", "Unseen Merchant"])
def test_no_subject_specific_parser(subject):
    assert comparison_plan(f"Compare {subject} 2025 and 2026").subject == subject.casefold()


def test_arithmetic_and_resolver_reuse(bank, monkeypatch):  # noqa: F811
    import tapio.pilot.period_comparison as module

    original = module.resolve_subject
    calls = []

    def resolve(subject, names):
        calls.append(subject)
        return original(subject, names)

    monkeypatch.setattr(module, "resolve_subject", resolve)
    p = comparison_plan("Compare Synthetic Processor 2025 and 2026")
    e = retrieve_comparison(p, bank)
    assert calls == ["synthetic processor"]
    assert e["resolution"]["status"] == "MATCH_FOUND"
    assert e["sides"][0]["transaction_count"] == 1
    assert e["sides"][1]["transaction_count"] == 0
    assert Decimal(e["difference_b_minus_a"]["EUR"]) == Decimal("-10")


@pytest.mark.parametrize(
    "phrase, metric",
    [
        ("bank inflow", "BANK_INFLOW"),
        ("net cash flow", "NET_CASH_FLOW"),
        ("transaction count", "TRANSACTION_COUNT"),
        ("bank outflow", "BANK_OUTFLOW"),
    ],
)
def test_metrics(phrase, metric):
    p = comparison_plan(f"Compare Example {phrase} 2025 and 2026")
    assert p.metric == metric


def test_explicit_context_filter():
    p = comparison_plan("Compare forestry bank inflow 2025 and 2026")
    assert p.filter_kind == "CONFIRMED_CONTEXT"
    assert p.subject == "FORESTRY"


def test_existing_comparison_without_periods_not_intercepted():
    assert comparison_plan("Compare fixed and spot electricity") is None


def test_empty_side_presentation(bank):  # noqa: F811
    from tapio.pilot.contracts import Session
    from tapio.pilot.period_comparison import comparison_response

    p = comparison_plan("Compare Synthetic Processor 2025 and 2026")
    evidence = retrieve_comparison(p, bank)
    session = Session(
        id="offline",
        timestamp="offline",
        model_calls=0,
        rounds=0,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        latency_seconds=0,
        estimated_cost_usd="0",
    )
    response = comparison_response(evidence, session)
    assert "-10.00 EUR" in response.direct_answer
    assert "does not establish zero spending" in response.answer
    assert "complete bank-statement coverage" in response.coverage_note
    assert response.presentation_mode == "COMPARISON"
    assert not response.optional_details.get("documents")
    assert not response.optional_details.get("bank_aggregates")


@pytest.mark.parametrize(
    "metric, expected",
    [
        ("BANK_OUTFLOW", "-10.000000"),
        ("BANK_INFLOW", "0"),
        ("NET_CASH_FLOW", "10.000000"),
        ("TRANSACTION_COUNT", "-1"),
    ],
)
def test_signed_metrics(bank, metric, expected):  # noqa: F811
    p = comparison_plan("Compare Synthetic Processor 2025 and 2026").model_copy(
        update={"metric": metric}
    )
    e = retrieve_comparison(p, bank)
    assert Decimal(next(iter(e["difference_b_minus_a"].values()))) == Decimal(expected)


def test_weak_context_not_promoted(bank):  # noqa: F811
    p = comparison_plan("Compare forestry bank inflow 2025 and 2026")
    e = retrieve_comparison(p, bank)
    assert all(s["transaction_count"] == 0 for s in e["sides"])
    p = comparison_plan("Compare property bank outflow 2025 and 2026")
    assert retrieve_comparison(p, bank)["sides"][1]["transaction_count"] == 1


def test_fuel_months_typed_filter(bank):  # noqa: F811
    from tapio.pilot.period_comparison import ComparisonPlan, period

    p = ComparisonPlan(
        subject="FUEL",
        filter_kind="CONFIRMED_CATEGORY",
        metric="BANK_OUTFLOW",
        period_a=period(2026, 1),
        period_b=period(2026, 2),
    )
    # Synthetic fuel label is weak, so it must not become confirmed category evidence.
    assert all(s["transaction_count"] == 0 for s in retrieve_comparison(p, bank)["sides"])


def test_imported_description_whitelist(bank):  # noqa: F811
    from sqlalchemy import select

    from apps.api.app.domain.models import Transaction

    with bank() as db, db.begin():
        tx = db.scalars(select(Transaction).order_by(Transaction.id)).first()
        tx_id, original = tx.id, tx.raw_source
        tx.raw_source = {"Selitys": "TALLETUSKORKO", "PrivateAccountField": "privatehiddenxyz"}
    try:
        e = retrieve_search(literal_plan("talletuskorko"), bank)
        assert len(e["items"]) == 1
        assert e["items"][0]["matched_terms"] == [
            {"term": "talletuskorko", "fields": ["raw_source.Selitys"]}
        ]
        assert not retrieve_search(literal_plan("privatehiddenxyz"), bank)["items"]
    finally:
        with bank() as db, db.begin():
            db.get(Transaction, tx_id).raw_source = original
