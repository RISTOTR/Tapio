"""Synthetic presentation facts, including user-supplied regression totals; no live calls."""

from copy import deepcopy
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

import pytest
from test_pilot import REVIEW, session

from tapio.agent.render_bounded import render_answer
from tapio.pilot.answer_cards import mode_for
from tapio.pilot.presentation import present

A = "How much forestry income reached my bank account in 2025?"
B = "What forestry expenses did I pay in 2025?"
C = "What do we know about the €588.07 forestry payment?"
D = "What transactions still need human review?"


def group(context, category, debit, credit, count=1):
    return dict(
        business_context=context,
        category=category,
        currency="EUR",
        debit_total=debit,
        credit_total=credit,
        net_cash_flow="0",
        transaction_count=count,
        confirmed_count=count if context != "UNKNOWN" else 0,
        unresolved_count=count if context == "UNKNOWN" else 0,
    )


def bank(year=2025):
    return dict(
        date_from=f"{year}-01-01",
        date_to=f"{year}-12-31",
        context_filter=None,
        categories_filter=None,
        observed_first_date=f"{year}-01-02",
        observed_last_date=f"{year}-12-29" if year == 2025 else f"{year}-10-06",
        transaction_count=225 if year == 2025 else 170,
        confirmed_count=52 if year == 2025 else 75,
        unresolved_count=174 if year == 2025 else 95,
        excluded_unresolved_context_count=0,
        groups=[
            group("FORESTRY", "TIMBER_INCOME", "0", "6894.42"),
            group("FORESTRY", "TAX", "0", "163.44"),
            group("FORESTRY", "FORESTRY_SERVICE", "469.66", "0"),
            group("FORESTRY", "INSURANCE", "496.54", "0"),
            group("PROPERTY", "ELECTRICITY", "999.00", "0"),
        ],
        context_totals=[
            group("FORESTRY", "ALL_CATEGORIES", "966.20", "7057.86", 4),
            group("PROPERTY", "ALL_CATEGORIES", "999.00", "0"),
            group("UNKNOWN", "ALL_CATEGORIES", "5", "0", 174 if year == 2025 else 95),
        ],
    )


def rec(identity=100):
    return dict(
        invoice_id=str(UUID(int=identity)),
        state="AMBIGUOUS",
        confirmed_paid_eur="0",
        confirmed_refund_eur="0",
        confirmed_net_eur="0",
        human_review_required=True,
        candidate_debit_count=2,
        candidate_credit_count=1,
        candidate_net_outflow_eur="588.07",
        candidate_net_matches_invoice=True,
    )


def result(tool, data):
    return {"ok": True, "tool": tool, "data": data}


def evidence(year=2025):
    invoice = dict(
        id=str(UUID(int=100)),
        invoice_date=f"{year}-03-01",
        vendor="Synthetic Forestry",
        total_eur="588.07",
        reconciliation=rec(),
    )
    unrelated = dict(
        id=str(UUID(int=200)),
        invoice_date=f"{year}-03-02",
        vendor="Vattenfall",
        total_eur="999.00",
        reconciliation={**rec(200), "state": "PAID"},
    )
    return [
        result("summarize_finances", bank(year)),
        result("find_invoices", {"items": [invoice, unrelated], "truncated": False}),
        result("get_invoice_reconciliation", rec()),
        result("get_invoice_reconciliation", rec()),
    ]


def render(question, results, message="Evidence", named_subject=None):
    response = {
        "status": "COMPLETE",
        "results": results,
        "message": message,
        "answer": render_answer(results, message),
    }
    before = deepcopy(response)
    output = present(response, session(), REVIEW, question=question, named_subject=named_subject)
    assert response == before  # Evidence/provenance is not edited by the presentation projection.
    assert output.answer == present(response, session(), REVIEW).answer
    return output


def main_text(output):
    return "\n".join(
        [
            output.direct_answer,
            *output.relevant_breakdown,
            output.coverage_note,
            output.human_review_note,
            *output.evidence_summary,
            *output.optional_details["main_limitations"],
        ]
    )


def test_income_direct_answer_and_category_distinction():
    output = render(A, evidence())
    assert output.direct_answer.startswith("€6,894.42 of reviewed timber income")
    assert "€7,057.86" in output.direct_answer
    assert any("Tax" in s and "€163.44" in s for s in output.relevant_breakdown)
    assert "Vattenfall" not in main_text(output)
    assert "PROPERTY" not in main_text(output) and "PERSONAL" not in main_text(output)
    assert "no tax-deductibility" not in main_text(output)


def test_expenses_total_and_unknown_exclusions_once():
    output = render(B, evidence())
    assert "€966.20" in output.direct_answer
    assert any("€469.66" in s for s in output.relevant_breakdown)
    assert any("€496.54" in s for s in output.relevant_breakdown)
    assert main_text(output).count("174 unknown-context") == 1
    assert main_text(output).count("does not prove a complete") == 1
    assert "Vattenfall" not in main_text(output)
    assert "€999.00" not in main_text(output)


def test_ambiguity_leads_and_reconciliation_is_deduplicated():
    output = render(C, evidence())
    assert output.direct_answer.startswith("The €588.07 payment is not fully reconciled.")
    assert "2 possible debit" in output.direct_answer and "1 credit/refund" in output.direct_answer
    assert main_text(output).count("exact reversed debit") == 1
    assert "cannot be established" in output.direct_answer
    assert len(output.optional_details["reconciliation"]) == 2  # One ambiguous + unrelated paid.
    assert "Vattenfall" not in main_text(output)


def rows():
    return [
        dict(
            id=str(UUID(int=300 + i)),
            booking_date=str(date(2026, 1, 2) + timedelta(days=i)),
            counterparty=f"Synthetic shop {i}",
            amount="-1.00",
            currency="EUR",
            business_context=None,
            category=None,
            label_authority="UNREVIEWED",
        )
        for i in range(95)
    ]


def review_evidence():
    all_rows = rows()
    return evidence(2026) + [
        result("query_transactions", {"items": all_rows[:50], "truncated": False}),
        result("query_transactions", {"items": all_rows[50:], "truncated": False}),
    ]


def test_review_95_first_ten_and_all_rows_retained():
    source = review_evidence()
    before = deepcopy(source)
    output = render(D, source)
    assert output.direct_answer == "95 transactions still need human review."
    assert len([s for s in output.relevant_breakdown if "Synthetic shop" in s]) == 10
    assert "Additional transactions omitted" in output.relevant_breakdown[-1]
    assert len(output.optional_details["transactions"]) == 95
    assert source == before
    assert "2026-10-06" in output.coverage_note
    assert "Vattenfall" not in main_text(output) and "€966.20" not in main_text(output)
    assert main_text(output).count("95 transactions") == 1
    assert len(output.evidence_summary) == 1


def test_repeated_pages_do_not_duplicate_transactions():
    source = review_evidence()
    source.append(deepcopy(source[-1]))
    output = render(D, source)
    assert len(output.optional_details["transactions"]) == 95


def test_same_amount_distinct_invoice_ids_not_collapsed():
    source = evidence()
    source.append(result("get_invoice_reconciliation", rec(400)))
    output = render(C, source)
    assert output.direct_answer.startswith("2 payment evidence records remain ambiguous")
    assert len(output.optional_details["reconciliation"]) == 3


def test_scoped_exclusion_count_preserved():
    source = evidence()
    source[0]["data"]["context_filter"] = "FORESTRY"
    source[0]["data"]["excluded_unresolved_context_count"] = 174
    assert "174 unknown-context" in render(B, source).human_review_note


def test_no_financial_total_manufactured_from_transaction_page():
    output = render(B, [result("query_transactions", {"items": rows(), "truncated": True})])
    assert "does not supply a complete" in output.direct_answer
    assert "€95.00" not in output.direct_answer


def test_no_total_from_unreviewed_or_mixed_currency_aggregate():
    source = evidence()
    source[0]["data"]["context_totals"][0]["confirmed_count"] = 0
    assert "does not supply a complete" in render(B, source).direct_answer
    source = evidence()
    source[0]["data"]["context_totals"].append(
        {**source[0]["data"]["context_totals"][0], "currency": "USD"}
    )
    assert "does not supply a complete" in render(B, source).direct_answer


def test_comparison_shows_only_saved_result():
    source = evidence() + [
        result(
            "get_saved_energy_comparison",
            {
                "months": ["2026-04", "2026-05"],
                "coverage": "Accepted months only",
                "aggregate": {
                    "winner": "spot",
                    "fixed_minus_spot_eur": "12.34",
                    "net_fixed_household_total": "100.00",
                    "net_spot_household_total": "87.66",
                },
            },
        )
    ]
    output = render("Was fixed or spot cheaper?", source)
    assert output.direct_answer.startswith("Spot was cheaper by €12.34")
    assert "Vattenfall" not in main_text(output) and "forestry" not in main_text(output).lower()
    assert "2026-04" in output.coverage_note
    assert "unchanged-consumption" in main_text(output)


def test_coverage_is_prominent():
    output = render("How complete is 2026?", evidence(2026))
    assert "170 transactions" in output.direct_answer
    assert "75 human-reviewed" in output.direct_answer and "95 unresolved" in output.direct_answer
    assert "2026-10-06" in output.direct_answer


def test_tax_boundary_only_relevant_main_text():
    output = render("Can I deduct forestry purchases?", evidence(), "Tax treatment requires review")
    assert "does not decide tax deductibility" in output.direct_answer
    assert "tax deductibility" not in main_text(render(B, evidence()))


def test_lookup_uses_human_context_not_merchant_heuristic():
    from test_pilot_routing import resolved_fixture

    row = {
        **rows()[0],
        "counterparty": "Oikea Konekauppa Oy",
        "business_context": "PROPERTY",
        "category": "OTHER",
        "label_authority": "HUMAN_REVIEWED",
    }
    output = render(
        "What evidence do we have for Oikea Konekauppa?",
        [result("query_transactions", {"items": [row], "truncated": False})],
        named_subject=resolved_fixture("What evidence do we have for Oikea Konekauppa?", [row]),
    )
    assert "1 matching bank transaction" in output.direct_answer
    assert "PROPERTY" in main_text(output) and "FORESTRY" not in main_text(output)
    assert "does not prove no receipt exists" in main_text(output)


def test_new_details_do_not_expose_private_ids_or_raw_sources():
    source = review_evidence()
    source[-1]["data"]["items"][0]["raw_source"] = "private raw data"
    output = render(D, source)
    details = str(output.optional_details)
    assert str(UUID(int=100)) not in details and str(UUID(int=300)) not in details
    assert "private raw data" not in details


@pytest.mark.parametrize(
    "question,mode",
    [
        (A, "FINANCIAL_TOTAL"),
        (D, "TRANSACTION_REVIEW"),
        (C, "AMBIGUITY"),
        ("Was fixed or spot cheaper?", "COMPARISON"),
        ("What evidence is available?", "EVIDENCE_LOOKUP"),
        ("How complete is 2026?", "COVERAGE"),
        ("Can I deduct this?", "TAX_BOUNDARY"),
    ],
)
def test_modes_are_presentation_only(question, mode):
    assert mode_for(question, {}) == mode


def test_raw_json_and_legacy_answer_inside_closed_details():
    class Inspect(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.hidden_ids = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "details":
                assert "open" not in attrs
                self.depth += 1
            if self.depth and "id" in attrs:
                self.hidden_ids.add(attrs["id"])

        def handle_endtag(self, tag):
            if tag == "details":
                self.depth -= 1

    page = Path("tapio/pilot/page.html").read_text()
    parser = Inspect()
    parser.feed(page)
    assert {"coverage", "transactions", "validated-answer"} <= parser.hidden_ids
    assert "data.direct_answer||data.answer" in page
    assert "innerHTML" not in page
    for rating in ("GOOD", "INCOMPLETE", "WRONG_EVIDENCE", "UNCLEAR", "OTHER"):
        assert f"<option>{rating}</option>" in page


def test_document_catalog_and_invoice_merge_by_source_identity():
    source = evidence()
    source[1]["data"]["items"][0]["source_document_id"] = str(UUID(int=500))
    source.append(
        result(
            "list_documents",
            {
                "items": [
                    {
                        "id": str(UUID(int=500)),
                        "vendor": "Synthetic Forestry",
                        "document_type": "invoice",
                    }
                ],
                "truncated": False,
            },
        )
    )
    output = render(C, source)
    assert len(output.optional_details["documents"]) == 2
    assert len(output.optional_details["reconciliation"]) == 2


def test_category_restricted_aggregate_not_presented_as_all_expenses():
    source = evidence()
    source[0]["data"]["categories_filter"] = ["ELECTRICITY"]
    assert "does not supply a complete" in render(B, source).direct_answer


def test_legacy_backend_fields_and_feedback_session_unchanged():
    source = evidence()
    s = session()
    response = {
        "status": "COMPLETE",
        "results": source,
        "message": "Evidence",
        "answer": render_answer(source, "Evidence"),
    }
    before = present(response, s, REVIEW)
    after = present(response, s, REVIEW, question=B)
    for name in (
        "answer",
        "coverage",
        "evidence",
        "human_review",
        "limitations",
        "session",
        "evidence_state",
        "evidence_states",
    ):
        assert getattr(before, name) == getattr(after, name)


def test_ambiguity_amount_matches_database_decimal_scale():
    source = evidence()
    for item in source[1]["data"]["items"]:
        if item["reconciliation"]["state"] == "AMBIGUOUS":
            item["total_eur"] = "588.070000"
            item["reconciliation"]["candidate_net_outflow_eur"] = "588.070000"
    for item in source[2:]:
        item["data"]["candidate_net_outflow_eur"] = "588.070000"
    output = render(C, source)
    assert output.direct_answer.startswith("The €588.07 payment is not fully reconciled.")
    assert "2 possible debit candidates" in output.direct_answer


def test_context_specific_review_does_not_use_global_unresolved_count():
    output = render("What forestry transactions still need human review?", review_evidence())
    assert output.direct_answer == "0 transactions still need human review. Scope: FORESTRY."
    assert "95 transactions" not in main_text(output)
