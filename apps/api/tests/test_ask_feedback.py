import asyncio
from decimal import Decimal

import pytest

from apps.api.app.services.tool_queries import Queries
from apps.api.tests.test_confirmation_workflow import apply
from apps.api.tests.test_confirmation_workflow import setup as setup
from apps.api.tests.test_energy_load import factory as factory
from apps.api.tests.test_workspace import fake_pilot
from tapio.pilot import workspace_answers as answers
from tapio.pilot.concepts import catalog_query
from tapio.pilot.period_comparison import comparison_plan
from tapio.tools.finance_schemas import FinanceQuery


def test_finance_uses_current_review_independent_fields_and_correction(setup, factory):
    service, card, _ = setup
    queries = Queries(session_factory=factory)
    args = FinanceQuery(date_from="2025-01-01", date_to="2025-12-31", business_context="property")
    assert queries.summarize_finances(args).transaction_count == 0
    apply(
        service,
        card,
        action="CHANGE",
        fields={"context": "PROPERTY"},
        reason="Synthetic current context",
    )
    value = queries.summarize_finances(args)
    assert value.transaction_count == 1 and value.context_totals[0].debit_total == Decimal("123.45")
    assert value.groups[0].category == "UNKNOWN"
    apply(
        service,
        card,
        action="CHANGE",
        fields={"context": "FORESTRY", "category": "TAX"},
        reason="Synthetic correction",
    )
    assert queries.summarize_finances(args).transaction_count == 0
    value = queries.summarize_finances(args.model_copy(update={"business_context": None}))
    assert any(g.business_context == "FORESTRY" and g.category == "TAX" for g in value.groups)


def test_bounded_followup_carries_scope_not_answer_numbers():
    assert (
        answers.followup_question(
            "Show those tax payments", "What forestry expenses did I pay in 2026?"
        )
        == "Show forestry tax payments in 2026"
    )
    assert answers.followup_question("Show those tax payments", "Compare 2025 and 2026") is None
    assert (
        answers.followup_question("Find Paytrail transactions in 2025", "forestry expenses in 2026")
        == "Find Paytrail transactions in 2025"
    )


def test_followup_reads_saved_session_and_displays_scope(tmp_path, monkeypatch):
    pilot = fake_pilot(tmp_path)
    previous = answers.session()
    pilot.history.save(previous.id, {"question": "What forestry expenses did I pay in 2026?"})

    def details(q):
        assert q == "Show forestry tax payments in 2026"
        return answers.response(
            "Synthetic tax evidence", sources=[{"label": "Local data", "status": "used"}]
        )

    monkeypatch.setattr(answers, "tax_details", details)
    result = asyncio.run(answers.answer_workspace(pilot, "Show those tax payments", previous.id))
    assert result.relevant_breakdown == ["Follow-up scope: Show forestry tax payments in 2026"]


@pytest.mark.parametrize(
    "question",
    [
        "How much was the solarpanel output during 2025 vs 2026?",
        "How much were the electricity bills October 2025 vs October 2026?",
    ],
)
def test_energy_not_bank_merchant_comparison(question):
    with pytest.raises(ValueError):
        comparison_plan(question)
    assert len(answers.energy_periods(question)) == 2


def test_missing_energy_routes_to_bounded_email_evidence(tmp_path, monkeypatch):
    pilot = fake_pilot(tmp_path)
    calls = []
    monkeypatch.setattr(
        answers, "local_energy", lambda q, p: ([], [], [(b, "Vattenfall") for b in p])
    )

    async def lookup(p, q):
        calls.append(q)
        return answers.response(
            "Candidate",
            records=[{"source": "Gmail read-only", "reference": "synthetic"}],
            sources=[{"label": "Gmail read-only", "status": "used"}],
        )

    monkeypatch.setattr(answers, "answer_question", lookup)
    result = asyncio.run(
        answers.answer_workspace(pilot, "How much was solarpanel output during 2025 vs 2026?")
    )
    assert calls == [
        "Find email receipts from Vattenfall in 2025",
        "Find email receipts from Vattenfall in 2026",
    ]
    assert any("not total panel production" in v for v in result.limitations)
    assert "complete comparison is not established" in result.direct_answer
    assert any(s["label"] == "Gmail read-only" for s in result.sources)


def test_complete_local_energy_never_calls_email(tmp_path, monkeypatch):
    monkeypatch.setattr(
        answers,
        "local_energy",
        lambda q, p: (
            [{"source": "Local energy", "total": "12.50"}],
            ["Synthetic solar export 12.50 kWh"],
            [],
        ),
    )

    async def forbidden(*a):
        pytest.fail("Sufficient local energy must not use Gmail")

    monkeypatch.setattr(answers, "answer_question", forbidden)
    result = asyncio.run(answers.answer_workspace(fake_pilot(tmp_path), "Solar export in 2025"))
    assert result.relevant_breakdown[0] == "Synthetic solar export 12.50 kWh"


@pytest.mark.parametrize(
    "question,concept",
    [
        ("Näytä kaikki tiemaksut", "road fees"),
        ("Find transactions related to restaurants", "restaurant"),
        ("Show me all transactions related to pharmacies or medication", "pharmacy"),
        (
            "Show me purchases related to hardware or building materials",
            "hardware/building supplies",
        ),
    ],
)
def test_feedback_multilingual_search_catalog(question, concept):
    assert catalog_query(question)[0] == concept


@pytest.mark.parametrize(
    "question,term",
    [
        ("DNA maksut 2026", "dna"),
        ("yksityistie transactions 2026", "yksityistie"),
        ("maksut arto seppälä", "arto seppala"),
        ("mitä maksuja olen tehnyt abc:llä", "abc"),
        ("kuinka paljon olen maksanut dna:lle", "dna"),
        ('find tranactions with "talletuskorko"', "talletuskorko"),
    ],
)
def test_finnish_query_grammar_is_not_evidence(question, term):
    from tapio.pilot.literal_search import literal_plan

    assert literal_plan(question).terms == [term]


def test_finnish_comparison_preserves_subject():
    assert comparison_plan("DNA maksut 2026 vs 2025").subject == "dna"


def test_two_suppliers_keep_separate_local_queries(tmp_path, monkeypatch):
    calls = []

    async def local(pilot, question):
        calls.append(question)
        return answers.response("Synthetic deterministic supplier total")

    monkeypatch.setattr(answers, "answer_question", local)
    result = asyncio.run(
        answers.answer_workspace(
            fake_pilot(tmp_path),
            "HOW MUCH was my elenia and vattenfall transactions in October 2025",
        )
    )
    assert calls == [
        "Find Elenia transactions in October 2025",
        "Find Vattenfall transactions in October 2025",
    ]
    assert len(result.relevant_breakdown) == 2


@pytest.mark.parametrize("noun", ["transactions", "expenses", "payments", "maksut"])
def test_fuel_comparison_feedback_removes_question_grammar(noun):
    plan = comparison_plan(f"how much were my fuel {noun} 2025 vs 2026")
    assert plan.subject == "FUEL"
    assert plan.filter_kind == "CONFIRMED_CATEGORY"
    assert plan.metric == "BANK_OUTFLOW"


def test_two_provider_email_query_needs_no_exact_sender_address():
    from tapio.pilot.evidence_routing import gmail_query, match

    q = "Find Elenia and Vattenfall transactions of November 2026 in email"
    assert gmail_query(q, []).query == (
        "from:(Elenia OR Vattenfall) after:2026/11/01 before:2026/12/01"
    )
    assert match("Elenia Verkko Oyj", q)
    assert match("Vattenfall Oy", q)
    assert not match("Unrelated transaction from November 2026", q)
    assert gmail_query("Find Vattenfall Oy emails in November 2026", []).query.startswith(
        "from:Vattenfall "
    )


def test_explicit_dual_email_excludes_unrelated_history_and_reports_scope(tmp_path):
    from tapio.pilot.evidence_routing import answer_question

    calls = []

    async def email(search, directory):
        calls.append(search.query)
        return [
            {"source": "Gmail read-only", "subject": "Synthetic bill", "reference": "mail1"}
        ], False

    result = asyncio.run(
        answer_question(
            fake_pilot(tmp_path),
            "Find Elenia and Vattenfall transactions of November 2026 in email",
            local_loader=lambda q: (
                [{"source": "Persistent knowledge", "subject": "Old unrelated fact"}],
                [],
            ),
            email_loader=email,
        )
    )
    assert len(calls) == 1
    assert "1 candidate email" in result.direct_answer
    assert "2026-11-01 to 2026-11-30" in result.direct_answer
    assert all(r["source"] == "Gmail read-only" for r in result.supporting_records)
    assert result.sources[-1]["status"] == "used"


def test_email_auth_failure_explains_reconnection(tmp_path):
    from tapio.pilot.evidence_routing import answer_question

    async def unavailable(*args):
        raise ExceptionGroup("MCP context", [ValueError("AUTHENTICATION_REQUIRED")])

    result = asyncio.run(
        answer_question(
            fake_pilot(tmp_path),
            "Find Elenia and Vattenfall email in November 2026",
            local_loader=lambda q: ([], []),
            email_loader=unavailable,
        )
    )
    assert "Gmail needs authorization" in result.direct_answer
    assert result.sources[-1]["status"] == "authentication required"
    assert result.evidence_state != "NO_MATCH"


def test_tax_candidates_exclude_other_contexts_and_inflows():
    from types import SimpleNamespace

    from tapio.pilot.tax_suggestions import candidate

    tx = SimpleNamespace(
        id="synthetic",
        amount=Decimal("-123.45"),
        booking_date="2026-04-01",
        normalized_counterparty="Synthetic forestry shop",
        raw_counterparty=None,
        currency="EUR",
        source_file="synthetic.csv",
    )
    review = SimpleNamespace(
        review_status="REVIEWED", confirmed_category="FUEL", confirmed_business_context="FORESTRY"
    )
    row = candidate(tx, review)
    assert row["suggestion"] == "Possible forestry expense deduction"
    assert "Not calculated" in row["vat_status"]
    for context in ("PERSONAL", "PROPERTY", "UNKNOWN", None):
        review.confirmed_business_context = context
        assert candidate(tx, review) is None
    review.confirmed_business_context = "FORESTRY"
    tx.amount = Decimal("123.45")
    assert candidate(tx, review) is None


def test_tax_question_returns_only_scoped_suggestions(tmp_path, monkeypatch):
    from tapio.pilot import tax_suggestions

    monkeypatch.setattr(
        tax_suggestions,
        "forestry_candidates",
        lambda q: (
            [
                {
                    "source": "Local bank transaction",
                    "business_context": "FORESTRY",
                    "suggestion": "Review tax treatment separately",
                    "amount": "-12.50",
                }
            ],
            [],
        ),
    )
    result = asyncio.run(
        answers.answer_workspace(
            fake_pilot(tmp_path),
            "Show my expenses marked as forestry which I could use for tax deduction "
            "and IVA calculations (VAT)",
        )
    )
    assert "1 confirmed forestry expenses" in result.direct_answer
    assert not result.optional_details.get("documents")
    assert "not tax decisions" in result.limitations[0]


def test_energy_comparison_preserves_month_range():
    periods = answers.energy_periods(
        "compare solarpanel output January - October 2025 vs 2026 from vattenfall transactions"
    )
    assert [(str(p.date_from), str(p.date_to)) for p in periods] == [
        ("2025-01-01", "2025-10-31"),
        ("2026-01-01", "2026-10-31"),
    ]


def test_selected_email_attachments_followup_keeps_records(tmp_path, monkeypatch):
    from tapio.pilot import attachment_answers

    async def analyze(pilot, question, selected):
        assert selected[0]["reference"] == "synthetic"
        return answers.response("Analyzed selected emails", records=selected)

    monkeypatch.setattr(attachment_answers, "analyze_attachments", analyze)
    pilot = fake_pilot(tmp_path)
    previous = answers.session()
    pilot.history.save(
        previous.id,
        {
            "question": "Find Vattenfall email November 2026",
            "response": {
                "supporting_records": [{"source": "Gmail read-only", "reference": "synthetic"}]
            },
        },
    )
    result = asyncio.run(
        answers.answer_workspace(
            pilot, "those are the ones. Open attached files and analyze them", previous.id
        )
    )
    assert "selected emails" in result.direct_answer
    assert result.supporting_records[0]["reference"] == "synthetic"
