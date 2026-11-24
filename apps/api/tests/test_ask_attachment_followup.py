"""Selected PDF follow-ups cannot become a new transaction or mailbox search."""

import asyncio

from tapio.pilot import planned_answers as answers
from tapio.pilot.query_plan import QueryPlan, interpret, validate_plan
from tapio.pilot.workspace_answers import response


class NoPlanner:
    def transport(self, payload):
        raise AssertionError("Selected PDFs are a saved-evidence action")


def previous():
    plan = validate_plan(
        "Why two Example Grid transactions in January 2025?",
        QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Example Grid"]),
    )
    return dict(
        question="Why two Example Grid transactions in January 2025?",
        plan=plan.model_dump(mode="json"),
        records=[
            dict(source="Gmail read-only", reference="abc123", requested_sender="Example Grid"),
            dict(source="Local bank transaction", transaction_id="tx1"),
        ],
    )


def test_selected_pdf_preserves_merchant_period_and_message_ids(monkeypatch, tmp_path):
    saved = previous()
    question = "Analyze the PDF attachments from these emails"
    plan = asyncio.run(interpret(NoPlanner(), question, previous=saved))
    assert plan.intent == "ATTACHMENT_ANALYSIS"
    assert plan.merchants == ["Example Grid"]
    assert str(plan.periods[0].date_to) == "2025-01-31"

    async def analyze(pilot, question, selected):
        assert [r["reference"] for r in selected] == ["abc123"]
        return response("PDF inspected", records=[dict(source="PDF", filename="invoice.pdf")])

    async def forbidden(*args):
        raise AssertionError("No new mailbox search")

    monkeypatch.setattr(answers, "analyze_attachments", analyze)
    monkeypatch.setattr(answers, "supporting_mail", forbidden)
    monkeypatch.setattr(
        answers, "load_transactions", lambda p: (_ for _ in ()).throw(AssertionError())
    )
    result = asyncio.run(answers.execute(None, plan, question, saved, tmp_path))
    assert result.answer == "PDF inspected"
    assert any(r.get("reference") == "abc123" for r in result.supporting_records)


def test_no_saved_selection_fails_without_broader_search(monkeypatch, tmp_path):
    question = "Check the PDF attachments from these emails"
    plan = asyncio.run(interpret(NoPlanner(), question))

    async def forbidden(*args):
        raise AssertionError("Missing selection cannot trigger mailbox search")

    monkeypatch.setattr(answers, "supporting_mail", forbidden)
    result = asyncio.run(answers.execute(None, plan, question, None, tmp_path))
    assert "no saved emails" in result.answer


def test_payment_inspection_keeps_pdf_findings(monkeypatch, tmp_path):
    plan = validate_plan(
        "Why two Example Grid transactions in January 2025? Check attachments",
        QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Example Grid"]),
    )
    row = dict(
        transaction_id="tx1",
        booking_date="2025-01-05",
        amount="-20",
        currency="EUR",
        counterparty="Example Grid",
        category="GRID_DISTRIBUTION",
        supporting_evidence=[],
    )
    monkeypatch.setattr(answers, "load_transactions", lambda p: ([row], []))

    async def mail(*args):
        return [dict(source="Gmail read-only", reference="abc123")], [], []

    async def analyze(*args):
        return response(
            "One PDF",
            records=[dict(source="PDF", filename="bill.pdf")],
            breakdown=["Invoice billing period: December 2024"],
            limits=["Payment association unconfirmed"],
        )

    monkeypatch.setattr(answers, "supporting_mail", mail)
    monkeypatch.setattr(answers, "analyze_attachments", analyze)
    result = asyncio.run(answers.execute(None, plan, "Why two payments?", None, tmp_path))
    assert any(r.get("filename") == "bill.pdf" for r in result.supporting_records)
    assert "Invoice billing period: December 2024" in result.relevant_breakdown
    assert "Payment association unconfirmed" in result.limitations
    assert any(r.get("transaction_id") == "tx1" for r in result.supporting_records)
