"""Whole conversation regression: four records must not become all history."""

import asyncio
import json
from types import SimpleNamespace

from tapio.pilot import planned_answers as answers
from tapio.pilot.conversation import load_previous
from tapio.pilot.query_plan import QueryPlan, validate_plan


class History:
    def __init__(self, root):
        self.root = root

    def directory(self, key):
        p = self.root / key
        p.mkdir(exist_ok=True)
        return p

    def save(self, key, data):
        (self.directory(key) / "question.json").write_text(json.dumps(data))


def test_receipts_failure_cards_and_missing_keep_original_selection(monkeypatch, tmp_path):
    history = History(tmp_path)
    pilot = SimpleNamespace(history=history, model_factory=lambda p: SimpleNamespace(usage=[]))
    rows = [
        dict(
            transaction_id=str(i),
            booking_date="2026-05-01",
            currency="EUR",
            amount="-10",
            category="TRAVEL",
            business_context="FORESTRY",
            counterparty="Example",
            source_system="SAMPO" if i == 0 else None,
            supporting_evidence=[],
        )
        for i in range(5)
    ]
    plan = validate_plan("Forestry travel expenses in 2026", QueryPlan(intent="TRANSACTION_SEARCH"))

    async def planner(*args, **kwargs):
        return plan

    monkeypatch.setattr(answers, "load_transactions", lambda p: (rows[:4], []))
    first = asyncio.run(
        answers.answer_planned(pilot, "Forestry travel expenses in 2026", planner=planner)
    )
    # A new matching import must not silently join the previously selected four.
    monkeypatch.setattr(answers, "load_transactions", lambda p: (rows, []))

    async def mail(*args):
        return [], ["No selected receipt link."], []

    monkeypatch.setattr(answers, "supporting_mail", mail)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Known follow-up must use server-owned focus")

    current = first
    for question in [
        "Which of those have supporting receipts or invoices?",
        "What are these?",
        "Which ones were paid from a non-Finnish account or card?",
        "Which ones are still missing evidence?",
    ]:
        current = asyncio.run(
            answers.answer_planned(pilot, question, current.session.id, planner=forbidden)
        )
        saved = load_previous(history, current.session.id)
        assert len(saved["focus"]["records"]) == 4
    assert len(current.supporting_records) == 4
    assert current.answer.startswith("4 candidate")
    assert {r["transaction_id"] for r in current.supporting_records} == {"0", "1", "2", "3"}


def test_customer_followup_uses_selected_pdf_without_search(monkeypatch, tmp_path):
    previous = dict(
        records=[
            dict(source="Email PDF attachment", filename="a.pdf", customer="Estate"),
            dict(source="Email PDF attachment", filename="b.pdf", customer="Owner"),
        ]
    )
    plan = QueryPlan(intent="DOCUMENT_LOOKUP")
    result = asyncio.run(
        answers.execute(None, plan, "Who was the customer on each invoice?", previous, tmp_path)
    )
    assert result.answer == "a.pdf: Estate. b.pdf: Owner."


def test_no_context_followup_cannot_search_all_history(tmp_path):
    from tapio.pilot.conversation import followup_plan

    p = followup_plan("Which ones are still missing evidence?", None)
    assert p.clarification and p.intent == "UNSUPPORTED"


def test_same_merchant_month_inherits_one_year_but_unrelated_merchant_does_not():
    from tapio.pilot.conversation import followup_plan

    p = validate_plan(
        "Example Grid January to March 2025",
        QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Example Grid"]),
    )
    previous = {"focus": {"plan": p.model_dump(mode="json"), "records": []}}
    result = followup_plan("Why two Example Grid transactions in January", previous)
    assert str(result.periods[0].date_from) == "2025-01-01"
    assert str(result.periods[0].date_to) == "2025-01-31"
    assert result.evidence_mode == "INSPECT"
    assert followup_plan("Why two Different Shop transactions in January", previous).clarification


def test_grid_and_same_period_change_subject_not_original_ids(monkeypatch, tmp_path):
    history = History(tmp_path)
    pilot = SimpleNamespace(history=history, model_factory=lambda p: SimpleNamespace(usage=[]))

    async def planner(model, question, **kwargs):
        assert "focus" not in (kwargs.get("previous") or {})
        if "same period" in question:
            raise AssertionError("Resolve dates before planner")
        return validate_plan(
            question, QueryPlan(intent="TRANSACTION_SEARCH", categories=["ELECTRICITY"])
        )

    def load(p):
        return (
            [
                dict(
                    transaction_id=category,
                    booking_date="2025-01-10",
                    currency="EUR",
                    amount="-10",
                    category=category,
                    counterparty="Example",
                )
                for category in p.categories
            ],
            [],
        )

    monkeypatch.setattr(answers, "load_transactions", load)
    a = asyncio.run(
        answers.answer_planned(
            pilot, "Show electricity and electricity grid transactions 2025", planner=planner
        )
    )
    assert len(a.supporting_records) == 2
    b = asyncio.run(
        answers.answer_planned(
            pilot,
            "And electricity grid transactions for the same period",
            a.session.id,
            planner=planner,
        )
    )
    assert [r["category"] for r in b.supporting_records] == ["GRID_DISTRIBUTION"]
    saved = load_previous(history, b.session.id)
    assert saved["focus"]["plan"]["categories"] == ["GRID_DISTRIBUTION"]
    assert saved["focus"]["plan"]["periods"][0]["date_from"] == "2025-01-01"


def test_omitted_year_with_question_mark():
    from tapio.pilot.conversation import followup_plan

    p = validate_plan(
        "Elenia in 2025", QueryPlan(intent="TRANSACTION_SEARCH", merchants=["Elenia"])
    )
    result = followup_plan(
        "Why did I pay Elenia twice during january?", {"focus": {"plan": p.model_dump(mode="json")}}
    )
    assert not result.clarification
    assert str(result.periods[0].date_to) == "2025-01-31"


def test_exclusions_refine_and_persist_selection(monkeypatch, tmp_path):
    from tapio.pilot.planned_retrieval import included

    history = History(tmp_path)
    pilot = SimpleNamespace(history=history, model_factory=lambda p: SimpleNamespace(usage=[]))
    rows = [
        dict(
            transaction_id=str(i),
            booking_date="2026-05-01",
            currency="EUR",
            amount="-10",
            category=category,
            business_context=context,
            counterparty=merchant,
            supporting_evidence=[],
        )
        for i, (category, context, merchant) in enumerate(
            [
                ("ELECTRICITY", "FORESTRY", "Supplier"),
                ("OTHER", "FORESTRY", "Verohallinto"),
                ("OTHER", "FORESTRY", "Shop"),
                ("OTHER", "PROPERTY", "Property shop"),
            ]
        )
    ]
    plan = validate_plan(
        "What forestry expenses from 2026 look relevant for tax?",
        QueryPlan(intent="TRANSACTION_SEARCH", contexts=["FORESTRY"]),
    )
    monkeypatch.setattr(
        answers, "load_transactions", lambda p: ([r for r in rows if included(r, p)], [])
    )

    async def planner(*args, **kwargs):
        return plan

    first = asyncio.run(
        answers.answer_planned(
            pilot, "What forestry expenses from 2026 look relevant for tax?", planner=planner
        )
    )
    second = asyncio.run(
        answers.answer_planned(pilot, "Exclude electricity and property costs.", first.session.id)
    )
    third = asyncio.run(
        answers.answer_planned(
            pilot, "Exclude Verohalllinto from those expenses", second.session.id
        )
    )
    assert not second.failure_category and not third.failure_category
    assert {r["counterparty"] for r in third.supporting_records} == {"Shop"}
    focus = load_previous(history, third.session.id)["focus"]
    assert focus["plan"]["contexts"] == ["FORESTRY"]
    assert focus["plan"]["periods"][0]["date_from"] == "2026-01-01"
    assert len(focus["records"]) == 1
    failed = asyncio.run(
        answers.answer_planned(pilot, "Exclude an unknown merchant", third.session.id)
    )
    assert failed.failure_category == "INTERPRETATION_FAILED"
    assert load_previous(history, failed.session.id)["focus"] == focus


def test_contract_pronoun_uses_saved_terms_not_previous_contract_expiry(monkeypatch, tmp_path):
    history = History(tmp_path)
    pilot = SimpleNamespace(history=history, model_factory=lambda p: SimpleNamespace(usage=[]))
    records = [
        dict(
            source="Stored email evidence",
            classification="ORDER_CONFIRMATION",
            accepted_fields={
                "new_contract.start_date": "2025-12-01",
                "new_contract.duration_months": "24",
                "new_contract.contract_type": "FIXED_TERM",
            },
        ),
        dict(
            source="Stored email evidence",
            classification="EXPIRY_NOTICE_EXPIRY_ONLY",
            accepted_fields={"previous_contract.end_date": "2025-11-30"},
        ),
    ]
    plan = QueryPlan(
        intent="DOCUMENT_LOOKUP", merchants=["Vattenfall"], evidence_requirements=["CONTRACT"]
    )
    history.save(
        "root",
        dict(
            question="Find the Vattenfall contract.",
            query_plan=plan.model_dump(mode="json"),
            response={"supporting_records": records},
        ),
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError("Must use saved contract evidence")

    result = asyncio.run(
        answers.answer_planned(pilot, "When does it end?", "root", planner=forbidden)
    )
    assert not result.failure_category
    assert "2027-11-30" in result.answer and "calculated" in result.answer
    assert "2025-11-30" not in result.answer
    assert load_previous(history, result.session.id)["focus"]["plan"]["merchants"] == ["Vattenfall"]
