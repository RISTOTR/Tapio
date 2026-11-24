"""Synthetic reproductions of exact-date, merchant and scope feedback."""

import asyncio
from datetime import date

import pytest

from tapio.pilot import planned_answers as answers
from tapio.pilot.planned_retrieval import aliases, included
from tapio.pilot.query_plan import Constraint, QueryPlan, explicit_periods, interpret, validate_plan
from tapio.pilot.transaction_search import matching_terms


@pytest.mark.parametrize("text", ["22/05/2026", "22.05.2026", "22nd of May 2026", "22 May 2026"])
def test_exact_day_is_never_broadened_to_month(text):
    periods = explicit_periods("Find a transaction " + text, date(2026, 11, 18))
    assert len(periods) == 1
    assert periods[0].date_from == periods[0].date_to == date(2026, 5, 22)


def test_invented_context_and_direction_removed():
    p = validate_plan(
        "Find a transaction 22/05/2026 for Example Shop",
        QueryPlan(
            intent="TRANSACTION_SEARCH",
            contexts=["FORESTRY"],
            metric="OUTFLOW",
            merchants=["Example Shop"],
        ),
    )
    assert p.contexts == [] and p.metric == "TRANSACTIONS"
    assert not p.clarification


def test_merchant_search_all_imported_dates_and_company_suffixes():
    p = validate_plan(
        "Find a transaction for Example Shop Oy",
        QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Example Shop Oy"]),
    )
    assert not p.clarification and not p.periods
    assert included(
        dict(
            booking_date="2020-01-01", business_context="PERSONAL", category="OTHER", amount="-10"
        ),
        p,
    )
    for spelling in ["EXAMPLE SHOP", "Example Shop Oy", "example shop oyj"]:
        assert matching_terms({"merchant": spelling}, aliases("Example Shop Oy"))
    assert not matching_terms({"merchant": "Example Shopper"}, aliases("Example Shop Oy"))


def test_new_question_does_not_send_previous_scope():
    class Model:
        usage = []

        def transport(self, payload):
            import json

            assert json.loads(payload["messages"][1]["content"])["previous"] is None
            p = QueryPlan(intent="TRANSACTION_SEARCH")
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_query_plan",
                                        "arguments": p.model_dump_json(),
                                    }
                                }
                            ]
                        },
                    }
                ]
            }

    asyncio.run(
        interpret(
            Model(),
            "Find a transaction 22/05/2026",
            previous={"question": "Forestry expenses in 2026"},
        )
    )


def test_expense_view_excludes_tax_without_reclassifying():
    p = validate_plan(
        "What were my forestry expenses in 2026?",
        QueryPlan(intent="TRANSACTION_SEARCH", metric="OUTFLOW"),
    )
    row = dict(booking_date="2026-05-22", category="TAX", business_context="FORESTRY", amount="-10")
    assert not included(row, p)
    p = validate_plan(
        "Show forestry tax payments in 2026",
        QueryPlan(intent="TRANSACTION_SEARCH", categories=["TAX"]),
    )
    assert included(row, p)


def test_electricity_contract_is_document_subject_not_transaction_category():
    p = validate_plan(
        "When does my electricity contract end?",
        QueryPlan(
            intent="DOCUMENT_LOOKUP",
            contexts=["PROPERTY"],
            categories=["ELECTRICITY"],
            evidence_requirements=["CONTRACT"],
            constraints=[Constraint(field="categories", text="electricity contract")],
        ),
    )
    assert not p.contexts and not p.categories and not p.clarification


def test_gmail_is_source_not_location_and_day_receipt_search(monkeypatch, tmp_path):
    p = validate_plan(
        "Find a transaction receipt in 22/05/2026 in gmail",
        QueryPlan(
            intent="TRANSACTION_SEARCH",
            locations=["gmail"],
            constraints=[Constraint(field="locations", text='"in gmail"')],
        ),
    )
    assert not p.locations and not p.clarification

    async def lookup(search, directory):
        assert "after:2026/05/22" in search.query and "before:2026/05/23" in search.query
        assert "from:Example" in search.query
        return [], False

    monkeypatch.setattr(answers, "gmail_lookup", lookup)
    records, limits, sources = asyncio.run(answers.supporting_mail(None, p, [], [], tmp_path))
    assert "merchant or email sender" in limits[0]
    asyncio.run(answers.supporting_mail(None, p, [{"counterparty": "Example Shop"}], [], tmp_path))


def test_undated_general_search_uses_all_history():
    p = validate_plan(
        "Show forestry transactions",
        QueryPlan(intent="TRANSACTION_SEARCH", clarification="Which year?"),
    )
    assert not p.periods and not p.clarification
    assert included(
        dict(
            booking_date="2019-01-01", category="OTHER", business_context="FORESTRY", amount="-10"
        ),
        p,
    )


def test_travel_evidence_does_not_replace_current_other_filter():
    p = validate_plan(
        "Find any transaction that looks like travel but is currently "
        "classified as OTHER 2025 and 2026",
        QueryPlan(intent="TRANSACTION_SEARCH", categories=["TRAVEL"]),
    )
    assert p.categories == ["OTHER"] and p.concepts == ["travel"]
    assert included(
        dict(
            booking_date="2025-01-01", category="OTHER", business_context="PERSONAL", amount="-10"
        ),
        p,
    )
    assert not included(
        dict(
            booking_date="2025-01-01", category="TRAVEL", business_context="PERSONAL", amount="-10"
        ),
        p,
    )


def test_supplier_share_keeps_denominator_and_year_to_date():
    p = validate_plan(
        "How much did I spend on electricity and grid charges in 2026 so far, "
        "and what percentage came from Elenia?",
        QueryPlan(
            intent="TRANSACTION_SEARCH",
            metric="OUTFLOW",
            categories=["ELECTRICITY"],
            merchants=["Elenia"],
        ),
        today=date(2026, 11, 19),
    )
    assert not p.merchants and p.share_merchants == ["Elenia"]
    assert set(p.categories) == {"ELECTRICITY", "GRID_DISTRIBUTION"}
    assert p.periods[0].date_to == date(2026, 11, 19)
    rows = [
        dict(
            booking_date="2026-01-01",
            amount=amount,
            currency="EUR",
            category=category,
            counterparty=merchant,
        )
        for amount, category, merchant in [
            ("-75", "ELECTRICITY", "Supplier"),
            ("-25", "GRID_DISTRIBUTION", "Elenia Oy"),
        ]
    ]
    result = answers.transaction_answer(p, rows, [])
    assert any("25.00 of 100.00 EUR, 25.0%" in line for line in result.relevant_breakdown)
    assert any("Energy supplier: 75.00 EUR" in line for line in result.relevant_breakdown)
    assert any("Grid distribution: 25.00 EUR" in line for line in result.relevant_breakdown)


@pytest.mark.parametrize("missing", [False, True])
def test_solar_consumption_ratio_requires_complete_coverage(monkeypatch, tmp_path, missing):
    p = validate_plan(
        "July 2025 solar output relative to consumption",
        QueryPlan(
            intent="ENERGY", metric="SOLAR_PRODUCTION", clarification="This is a comparison."
        ),
    )
    assert p.clarification is None

    def load(plan):
        return (
            [
                dict(
                    date_from="2025-07-01",
                    date_to="2025-07-31",
                    total=("200" if plan.metric == "CONSUMPTION" else "50"),
                )
            ],
            ["2025-07-01 to 2025-07-31"] if missing else [],
        )

    monkeypatch.setattr(answers, "load_energy", load)
    result = asyncio.run(answers.execute(None, p, "solar relative to consumption", None, tmp_path))
    assert any("25.0%" in line for line in result.relevant_breakdown) is not missing
    assert any("Total panel production" in line for line in result.limitations)
