"""Generic transaction search with synthetic provider responses and disposable DB fixtures."""

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from test_energy_load import factory as factory
from test_pilot import ask, make_pilot
from test_pilot_diagnostics import record

from apps.api.app.domain.models import ImportRun, Transaction, TransactionLabelReview
from tapio.pilot.config import MODEL
from tapio.pilot.search_planner import plan_search
from tapio.pilot.service import AcceptedModel
from tapio.pilot.transaction_search import (
    SearchPlan,
    matching_terms,
    normalize_text,
    requested_dates,
    retrieve_search,
    search_intent,
    validate_search_plan,
)

DENTAL_TERMS = ["dental", "dentista", "odontologo", "odontologia", "clinica dental"]


def plan(terms=None, dates=None):
    return SearchPlan(intent="TRANSACTION_SEARCH", terms=terms or DENTAL_TERMS, date_range=dates)


def native(value):
    return {
        "model": MODEL,
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "submit_transaction_search",
                                "arguments": json.dumps(value),
                            }
                        }
                    ]
                },
            }
        ],
    }


def search_pilot(tmp_path, terms=None, loader=None):
    pilot = make_pilot(tmp_path)

    def model_factory(path):
        def transport(payload):
            user = json.loads(payload["messages"][1]["content"])
            return native(plan(terms, user["date_range"]).model_dump(mode="json"))

        return AcceptedModel("synthetic", model=MODEL, transport=transport, protocol_dir=path)

    pilot.model_factory = model_factory
    if loader:
        pilot.search_loader = loader
    return pilot


@pytest.mark.parametrize(
    "question",
    [
        "Show me all transactions related to dental, including similar Spanish terms",
        "Find transactions mentioning dentist",
        "Show K-Rauta transactions",
        "Show fuel-related transactions in 2026",
        "Show pharmacy transactions",
        "Show me purchases from pharmacies",
        "Find transactions related to car repairs",
        "Find anything mentioning dentist",
        "Search for K-Rauta transactions",
        "No-such-term XYZ",
    ],
)
def test_generic_search_routing(question):
    assert search_intent(question)


@pytest.mark.parametrize(
    "question",
    [
        "Tell me everything important about my finances",
        "Give me a complete overview of everything",
        "Give me an overview of all my finances",
        "What transactions still need human review?",
        "How much did I pay Elenia in 2026?",
        "Can I deduct K-Rauta purchases?",
        "Compare my income between 2024 and 2026",
    ],
)
def test_existing_intents_not_stolen(question):
    assert not search_intent(question)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Odontólogo", "odontologo"),
        ("  CLÍNICA—DENTAL,  Madrid ", "clinica dental madrid"),
        ("Ｏｄｏｎｔｏｌｏｇíａ", "odontologia"),
    ],
)
def test_normalization(text, expected):
    assert normalize_text(text) == expected


def test_matching_is_phrase_based_and_provenance_is_explicit():
    fields = {"raw_description": "Clínica-dental / odontólogo", "normalized_merchant": "Dentista"}
    hits = matching_terms(fields, ["clinica dental", "odontologo", "dentista", "dent"])
    assert hits == [
        {"term": "clinica dental", "fields": ["raw_description"]},
        {"term": "odontologo", "fields": ["raw_description"]},
        {"term": "dentista", "fields": ["normalized_merchant"]},
    ]
    assert not matching_terms({"raw_description": "accidental"}, ["dental"])


@pytest.mark.parametrize(
    "terms", [[], ["de"], ["%"], ["all"], ["12345"], ["x" * 121], ["word"] * 11]
)
def test_invalid_terms_rejected(terms):
    with pytest.raises(ValueError):
        SearchPlan(intent="TRANSACTION_SEARCH", terms=terms, date_range=None)


@pytest.mark.parametrize(
    "question,start,end",
    [
        ("Show dental transactions", None, None),
        ("Show dental transactions in 2025", "2025-01-01", "2025-12-31"),
        ("Show dental transactions in March 2026", "2026-03-01", "2026-03-31"),
        ("Show dental transactions in February 2024", "2024-02-01", "2024-02-29"),
    ],
)
def test_optional_dates(question, start, end):
    dates = requested_dates(question)
    assert (dates.model_dump(mode="json") if dates else None) == (
        {"date_from": start, "date_to": end} if start else None
    )


def test_planner_cannot_add_hidden_date_scope():
    with pytest.raises(ValueError, match="SEARCH_DATE_SCOPE_MISMATCH"):
        validate_search_plan("Show dental transactions", plan(dates=requested_dates("in 2025")))
    with pytest.raises(ValueError):
        SearchPlan.model_validate(
            {
                "intent": "TRANSACTION_SEARCH",
                "terms": ["dental"],
                "date_range": None,
                "sql": "DELETE FROM transactions",
            }
        )


@pytest.mark.parametrize(
    "question",
    [
        "Show dental transactions last year",
        "Show dental transactions in March",
        "Show dental transactions between 2025 and 2026",
    ],
)
def test_unsupported_date_scope_is_not_silently_ignored(question):
    with pytest.raises(ValueError):
        requested_dates(question)


def test_provider_schema_and_private_raw_plan(tmp_path):
    payloads = []
    raw = native(plan().model_dump(mode="json"))
    model = AcceptedModel(
        "synthetic",
        model=MODEL,
        protocol_dir=tmp_path,
        transport=lambda payload: payloads.append(payload) or raw,
    )
    result = asyncio.run(
        plan_search(model, "Show dental transactions including similar Spanish terms")
    )
    assert result.terms == DENTAL_TERMS and result.date_range is None
    payload = payloads[0]
    assert payload["model"] == MODEL and payload["store"] is False
    assert "max_rounds" not in payload and payload["parallel_tool_calls"] is False
    function = payload["tools"][0]["function"]
    assert function["strict"] is True
    assert function["parameters"]["properties"]["terms"]["maxItems"] == 10
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["original_provider_output"] == raw
    assert saved["normalized_search_plan"]["terms"] == DENTAL_TERMS
    assert saved["validation"] == "VALID_SEARCH_PLAN"


@pytest.fixture(scope="module")
def bank(factory):
    with factory() as db, db.begin():
        run = ImportRun(
            source_type="synthetic",
            source_filename="synthetic",
            sha256="3" * 64,
            parser_version="test",
            status="COMPLETED",
        )
        db.add(run)
        db.flush()
        for index, (when, merchant, message, category, confirmed) in enumerate(
            [
                (date(2026, 1, 8), "Clínica Dental Ejemplo", "odontólogo", "TAX", True),
                (date(2025, 2, 19), "Synthetic Processor", "Visita dentista", "OTHER", False),
                (date(2026, 3, 2), "Farmacia Prueba", None, "OTHER", False),
                (date(2026, 3, 3), "Synthetic Station", None, "FUEL", False),
                (
                    date(2026, 3, 4),
                    "k-rauta viitasaari pielavesi",
                    "Synthetic purchase",
                    "OTHER",
                    False,
                ),
            ]
        ):
            row = Transaction(
                booking_date=when,
                amount=Decimal("-10.00"),
                currency="EUR",
                direction="outgoing",
                raw_counterparty=merchant,
                normalized_counterparty=merchant,
                message=message,
                category=category,
                business_context="forestry",
                payment_intermediary="Synthetic Processor" if index == 1 else None,
                ultimate_recipient="Synthetic Recipient" if index == 1 else None,
                raw_source={"not_a_description": "PrivateHiddenValue"},
                source_file="synthetic",
                import_run_id=run.id,
            )
            db.add(row)
            db.flush()
            if confirmed:
                db.add(
                    TransactionLabelReview(
                        transaction_id=row.id,
                        suggested_category_snapshot="TAX",
                        suggested_context_snapshot="FORESTRY",
                        confirmed_category="MAINTENANCE",
                        confirmed_business_context="PROPERTY",
                        review_status="REVIEWED",
                        reviewer="synthetic",
                        reviewed_at=datetime.now(UTC),
                        review_file_sha256="4" * 64,
                    )
                )
    return factory


def test_readonly_search_dates_labels_and_provenance(bank):
    data = retrieve_search(plan(), bank)
    assert len(data["items"]) == 2 and data["scanned_rows"] == 5 and data["complete"]
    reviewed = next(r for r in data["items"] if r["label_authority"] == "HUMAN_REVIEWED")
    assert reviewed["category"] == "MAINTENANCE" and reviewed["business_context"] == "PROPERTY"
    unresolved = next(r for r in data["items"] if r["label_authority"] == "UNREVIEWED")
    assert unresolved["category"] is None and unresolved["business_context"] is None
    assert reviewed["matched_terms"]
    dated = retrieve_search(plan(dates=requested_dates("in 2025")), bank)
    assert len(dated["items"]) == 1 and dated["items"][0]["booking_date"].startswith("2025")
    assert retrieve_search(plan(["PrivateHiddenValue"]), bank)["items"] == []


@pytest.mark.parametrize(
    "term,field",
    [
        ("FUEL", "suggested_category"),
        ("PROPERTY", "confirmed_context"),
        ("Synthetic Recipient", "recipient"),
        ("Synthetic Processor", "processor"),
        ("dentista", "raw_description"),
        ("Farmacia", "normalized_merchant"),
    ],
)
def test_all_searchable_fields_without_review_filter(bank, term, field):
    data = retrieve_search(plan([term]), bank)
    assert any(field in m["fields"] for r in data["items"] for m in r["matched_terms"])


def test_k_rauta_search_and_canonical_lookup_find_same_rows(bank):
    from tapio.pilot.named_subject import retrieve_subject

    a = retrieve_search(plan(["K-Rauta"]), bank)
    b = retrieve_subject("What evidence do we have for K-Rauta?", bank)
    assert {r["id"] for r in a["items"]} == {r["id"] for r in b["transactions"]}


def test_pilot_search_does_not_run_accepted_agent_or_return_unrelated_evidence(bank, tmp_path):
    pilot = search_pilot(tmp_path, loader=lambda p, sf: retrieve_search(p, bank))

    def forbidden(*args):
        pytest.fail("Search must not invoke unrelated registry or subject retrieval")

    pilot.registry_factory = forbidden
    pilot.subject_loader = forbidden
    response = ask(pilot, "Show all transactions related to dental, with similar Spanish terms")
    assert response.presentation_mode == "TRANSACTION_SEARCH"
    assert "2 matching" in response.direct_answer
    assert response.evidence_states == ["SUPPORTED", "HUMAN_REVIEW_REQUIRED"]
    assert response.session.model_calls == 1
    assert not response.coverage.bank and "documents" not in response.optional_details
    assert "PROPERTY" in response.model_dump_json() and "unresolved" in response.answer
    private = record(pilot, response)
    assert private["transaction_search"]["plan"]["terms"] == DENTAL_TERMS
    assert private["diagnostics"]["period"] is None
    assert not private["diagnostics"]["coordinator_called"]
    assert private["source_fingerprints_verified"]
    for row in private["transaction_search"]["items"]:
        assert row["id"] not in response.model_dump_json()


def test_no_match_is_supported(bank, tmp_path):
    pilot = search_pilot(tmp_path, ["No-such-term XYZ"], lambda p, sf: retrieve_search(p, bank))
    response = ask(pilot, "No-such-term XYZ")
    assert response.evidence_states == ["SUPPORTED", "NO_MATCH"]
    assert response.presentation_mode == "TRANSACTION_SEARCH"
    assert "No matching imported transactions" in response.answer
    assert "unavailable" not in response.answer


def test_limits_fail_closed(bank, tmp_path, monkeypatch):
    from tapio.pilot import transaction_search

    monkeypatch.setattr(transaction_search, "MAX_MATCHES", 1)
    pilot = search_pilot(tmp_path, loader=lambda p, sf: retrieve_search(p, bank))
    response = ask(pilot, "Show dental transactions")
    assert response.failure_category == "EVIDENCE_INCOMPLETE"
    assert "NO_MATCH" not in response.evidence_states and not response.evidence


def test_invalid_plan_does_not_retrieve(tmp_path):
    pilot = search_pilot(tmp_path)

    async def invalid(model, question):
        return {"intent": "TRANSACTION_SEARCH", "terms": ["de"], "date_range": None}

    pilot.search_planner = invalid
    pilot.search_loader = lambda *args: pytest.fail("Invalid plan must not retrieve")
    response = ask(pilot, "Show all transactions related to orthodontics")
    assert response.failure_category == "PLAN_INVALID"


@pytest.mark.parametrize("change", ["multiple_calls", "invented_date", "extra_field"])
def test_invalid_native_plan_retained_but_rejected(tmp_path, change):
    raw = native(plan().model_dump(mode="json"))
    f = raw["choices"][0]["message"]["tool_calls"][0]["function"]
    if change == "multiple_calls":
        raw["choices"][0]["message"]["tool_calls"] *= 2
    else:
        value = json.loads(f["arguments"])
        if change == "invented_date":
            value["date_range"] = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
        else:
            value["sql"] = "SELECT private"
        f["arguments"] = json.dumps(value)
    model = AcceptedModel("synthetic", model=MODEL, transport=lambda p: raw, protocol_dir=tmp_path)
    with pytest.raises(ValueError, match="INVALID_SEARCH_PLAN"):
        asyncio.run(plan_search(model, "Show dental transactions"))
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["validation"] == "INVALID_SEARCH_PLAN"
    assert saved["original_provider_output"] == raw


def test_human_labels_override_old_suggestions_in_label_matching(bank):
    assert not retrieve_search(plan(["TAX"]), bank)["items"]
    fuel = retrieve_search(plan(["FUEL"]), bank)["items"]
    assert fuel and all(r["category"] is None for r in fuel)


def test_scan_limit_cannot_be_reported_as_no_match(bank, monkeypatch):
    from tapio.pilot import transaction_search

    monkeypatch.setattr(transaction_search, "MAX_SCANNED", 1)
    with pytest.raises(ValueError, match="TRANSACTION_SEARCH_LIMIT"):
        retrieve_search(plan(["nonexistent unique value"]), bank)


def test_source_postflight_still_blocks_search_release(bank, tmp_path):
    checks = []

    def check(*args):
        checks.append(None)
        return {"source": len(checks)}

    pilot = search_pilot(tmp_path, loader=lambda p, sf: retrieve_search(p, bank))
    pilot.fingerprint_check = check
    response = ask(pilot, "Show dental transactions")
    assert response.failure_category == "SAFETY_REJECTION"
    assert not response.evidence and not response.optional_details


def test_human_confirmed_unknown_still_requires_review(bank):
    from test_pilot import session

    from tapio.pilot.transaction_search import search_response

    data = retrieve_search(plan(), bank)
    row = data["items"][0]
    row.update(label_authority="HUMAN_REVIEWED", category="UNKNOWN", business_context="UNKNOWN")
    data["items"] = [row]
    response = search_response(data, session())
    assert "HUMAN_REVIEW_REQUIRED" in response.evidence_states
    assert "human-reviewed: UNKNOWN / UNKNOWN; unresolved" in response.answer
