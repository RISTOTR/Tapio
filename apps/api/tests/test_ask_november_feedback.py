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
