"""Nov 20 feedback: negative scope, evidence gaps, and unavailable Gmail."""

import asyncio

from tapio.pilot import planned_answers as answers
from tapio.pilot.planned_retrieval import included
from tapio.pilot.query_plan import QueryPlan, validate_plan


def row(category="OTHER", context="FORESTRY"):
    return dict(
        transaction_id="synthetic",
        booking_date="2026-01-10",
        amount="-25",
        currency="EUR",
        category=category,
        business_context=context,
        counterparty="Example",
        supporting_evidence=[],
        payment_reference="",
    )


def test_tax_exclusions_are_negative_and_context_is_independent():
    plan = validate_plan(
        "Which 2026 forestry expenses look potentially relevant for tax, "
        "but don’t include electricity, groceries, or property maintenance?",
        QueryPlan(
            intent="TRANSACTION_SEARCH",
            metric="OUTFLOW",
            concepts=["tax"],
            categories=["ELECTRICITY", "GROCERIES", "MAINTENANCE"],
            contexts=["FORESTRY", "PROPERTY"],
        ),
    )
    assert plan.action == "TAX_SUGGESTION"
    assert plan.contexts == ["FORESTRY"] and not plan.categories and not plan.concepts
    assert included(row("MAINTENANCE"), plan)
    assert not included(row("ELECTRICITY"), plan)
    assert not included(row("GROCERIES"), plan)
    assert not included(row("MAINTENANCE", "PROPERTY"), plan)
    assert not included({**row(), "amount": "25"}, plan)


def test_excluded_personal_context_is_not_positive_filter():
    plan = validate_plan(
        "Show forestry travel expenses May to June 2026, "
        "but exclude anything paid during the trip that was clearly personal.",
        QueryPlan(intent="TRANSACTION_SEARCH"),
    )
    assert plan.contexts == ["FORESTRY"]
    assert plan.exclusions[0].context == "PERSONAL"


def test_missing_evidence_returns_candidates_without_gmail(monkeypatch, tmp_path):
    plan = validate_plan(
        "Find transactions related to my forestry planting trip "
        "and tell me which ones still have weak or missing evidence.",
        QueryPlan(intent="TRANSACTION_SEARCH", evidence_requirements=["RECEIPT"]),
    )
    monkeypatch.setattr(answers, "load_transactions", lambda p: ([row("TRAVEL")], []))

    async def unexpected(*args):
        raise AssertionError("Gaps inspect local links first")

    monkeypatch.setattr(answers, "supporting_mail", unexpected)
    result = asyncio.run(answers.execute(None, plan, "forestry planting trip", None, tmp_path))
    assert result.answer.startswith("1 candidate")
    assert result.supporting_records[0]["check_next"]
    assert any("not established" in s for s in result.limitations)


def test_inspection_keeps_payments_when_gmail_needs_auth(monkeypatch, tmp_path):
    plan = validate_plan(
        "Inspect why there are two Example transactions in January 2026. "
        "Search in Gmail if necessary",
        QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Example"]),
    )
    monkeypatch.setattr(
        answers, "load_transactions", lambda p: ([row(), {**row(), "transaction_id": "second"}], [])
    )

    async def auth(*args):
        raise ExceptionGroup("hidden", [ValueError("AUTHENTICATION_REQUIRED")])

    monkeypatch.setattr(answers, "gmail_lookup", auth)
    result = asyncio.run(answers.execute(None, plan, "Inspect why", None, tmp_path))
    assert result.answer == "2 matching transactions."
    assert len(result.supporting_records) == 2
    assert any("authorization needs reconnecting" in s for s in result.limitations)
    assert any(s["status"] == "authentication required" for s in result.sources)
    assert any("billing periods" in s for s in result.limitations)


def test_generic_missing_evidence_constraint_does_not_require_document_type():
    from tapio.pilot.query_plan import Constraint

    plan = validate_plan(
        "Show forestry transactions with missing evidence",
        QueryPlan(
            intent="TRANSACTION_SEARCH",
            constraints=[Constraint(field="evidence_requirements", text="missing evidence")],
        ),
    )
    assert plan.evidence_mode == "GAPS" and not plan.clarification


def test_found_emails_without_payment_link_are_not_reported_as_missing_transactions(
    monkeypatch, tmp_path
):
    p = validate_plan(
        "Find Gmail receipts from Example in January 2026",
        QueryPlan(intent="TRANSACTION_SEARCH", action="FIND_EVIDENCE", merchants=["Example"]),
    )
    monkeypatch.setattr(answers, "load_transactions", lambda plan: ([row()], []))

    async def mail(*args):
        return (
            [dict(source="Gmail read-only", reference="synthetic-message", excerpt="Receipt")],
            [],
            [],
        )

    monkeypatch.setattr(answers, "supporting_mail", mail)
    result = asyncio.run(answers.execute(None, p, "Find Gmail receipts", None, tmp_path))
    assert result.answer.startswith("1 payments found; 0 have linked evidence.")
    assert "1 candidate emails retrieved" in result.answer
    assert "No transactions" not in result.answer


def test_receipt_search_uses_sender_domain_and_payment_window(monkeypatch, tmp_path):
    p = validate_plan("Travel receipts 2026", QueryPlan(intent="TRANSACTION_SEARCH"))
    captured = []

    async def lookup(search, directory):
        captured.append(search.query)
        return [], False

    monkeypatch.setattr(answers, "gmail_lookup", lookup)
    rows = [
        {**row(), "counterparty": "vr", "booking_date": "2026-05-20"},
        {**row(), "counterparty": "onnibuscom oy", "booking_date": "2026-05-22"},
    ]
    asyncio.run(answers.supporting_mail(None, p, rows, [], tmp_path))
    assert "from:vr.fi after:2026/05/13 before:2026/05/28" in captured
    assert "from:onnibus.com after:2026/05/15 before:2026/05/30" in captured


def test_matched_invoice_comparison_updates_frozen_response(monkeypatch, tmp_path):
    records = [row(), {**row(), "transaction_id": "second"}]
    monkeypatch.setattr(answers, "load_transactions", lambda p: (records, []))

    async def mail(*args):
        return [], [], []

    monkeypatch.setattr(answers, "supporting_mail", mail)
    monkeypatch.setattr(
        answers,
        "compare_invoices",
        lambda *args: (["Two invoices match by reference and amount."], {"synthetic", "second"}),
    )
    p = QueryPlan(intent="TRANSACTION_SEARCH", action="FIND_EVIDENCE", evidence_mode="INSPECT")
    result = asyncio.run(answers.execute(None, p, "Why two payments?", None, tmp_path))
    assert "match separate invoices" in result.answer
    assert not any(s.startswith("The bank payments exist") for s in result.limitations)
