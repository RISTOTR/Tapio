"""Deterministic subject resolution and read-only evidence; synthetic bank fixtures."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from test_energy_load import factory as factory

from apps.api.app.domain.enums import ImportStatus
from apps.api.app.domain.models import ImportRun, Transaction, TransactionLabelReview
from tapio.pilot.answer_cards import mode_for
from tapio.pilot.named_subject import (
    bounded,
    extract_subject,
    resolve_subject,
    retrieve_subject,
    subject_cards,
)


@pytest.mark.parametrize(
    "question,text,year",
    [
        ("How much did I pay Vattenfall in 2026?", "Vattenfall", "2026"),
        ("What evidence do we have for Oikea Konekauppa?", "Oikea Konekauppa", None),
        ("Can I deduct Oikea Konekauppa purchases?", "Oikea Konekauppa", None),
        ("Can I deduct the Oikea Konekauppa purchases?", "Oikea Konekauppa", None),
        ("What evidence do we have for Vattenfall?", "Vattenfall", None),
    ],
)
def test_explicit_subject(question, text, year):
    assert extract_subject(question) == {
        "text": text,
        "normalized": text.casefold(),
        "year": year,
        "type": "NAMED_ENTITY",
    }


@pytest.mark.parametrize(
    "query,names,status,method",
    [
        ("VATTENFALL OY.", ["Vattenfall Oy"], "MATCH_FOUND", "CANONICAL_EXACT"),
        ("Vattenfall", ["Vattenfall Oy"], "MATCH_FOUND", "LEGAL_SUFFIX_NORMALIZED"),
        ("Oikea Konekauppa", ["oikea konekaupp viitasaari"], "MATCH_FOUND", "CANONICAL_EXACT"),
        ("Elenia Verkko Oy", ["Elenia Verkko Oyj"], "MATCH_FOUND", "ALIAS_EXACT"),
        (
            "Synthetic",
            ["Synthetic Oy", "Synthetic Oyj"],
            "AMBIGUOUS_IDENTITY",
            "AMBIGUOUS_IDENTITY",
        ),
        ("Unseen Merchant", ["Vattenfall Oy"], "NO_MATCH", "NO_MATCH"),
        ("Vatten", ["Vattenfall Oy"], "NO_MATCH", "NO_MATCH"),
        ("Vattenfall", ["Vattenfall Services Oy"], "NO_MATCH", "NO_MATCH"),
    ],
)
def test_identity_matching(query, names, status, method):
    result = resolve_subject(query, names)
    assert (result["status"], result["method"]) == (status, method)


def test_broad_question_is_not_subject():
    assert extract_subject("What forestry expenses did I pay in 2025?") is None
    assert extract_subject("What evidence do we have for Example and Another?") is None


def test_tax_presentation_requires_tax_intent():
    from test_pilot_routing import resolved_fixture

    response = {"message": "Tax treatment requires human review."}
    q = "What evidence do we have for Vattenfall?"
    assert mode_for(q, response, resolved_fixture(q)) == "NAMED_SUBJECT"
    q = "How much did I pay Vattenfall in 2026?"
    assert mode_for(q, response, resolved_fixture(q)) == "FINANCIAL_TOTAL"
    assert mode_for("Can I deduct Oikea Konekauppa purchases?", response) == "TAX_BOUNDARY"


def test_truncated_evidence_cannot_supply_total():
    with pytest.raises(ValueError, match="NAMED_SUBJECT_EVIDENCE_LIMIT"):
        bounded(range(1001))


@pytest.fixture(scope="module")
def subjects(factory):
    with factory() as db, db.begin():
        run = ImportRun(
            source_type="synthetic",
            source_filename="synthetic",
            sha256="0" * 64,
            parser_version="test",
            status=ImportStatus.COMPLETED,
        )
        db.add(run)
        db.flush()
        for year, name, recipient, amount, reviewed in [
            (2026, "Vattenfall Oy", None, "-10", True),
            (2025, "Vattenfall Oy", None, "-20", False),
            (2026, "oikea konekaupp viitasaari", None, "-30", False),
            (2025, "oikea konekaupp viitasaari", None, "-40", True),
            (2026, "Paytrail Oyj", "Synthetic Recipient", "-50", False),
        ]:
            row = Transaction(
                booking_date=date(year, 1, 2),
                amount=Decimal(amount),
                currency="EUR",
                direction="outgoing",
                normalized_counterparty=name,
                ultimate_recipient=recipient,
                payment_intermediary="Paytrail Oyj" if recipient else None,
                source_file="synthetic",
                import_run_id=run.id,
                category="TAX",
                business_context="forestry",
            )
            db.add(row)
            db.flush()
            if reviewed:
                db.add(
                    TransactionLabelReview(
                        transaction_id=row.id,
                        suggested_category_snapshot="TAX",
                        suggested_context_snapshot="FORESTRY",
                        confirmed_category="MAINTENANCE",
                        confirmed_business_context="PERSONAL",
                        review_status="REVIEWED",
                        reviewer="synthetic",
                        reviewed_at=datetime.now(UTC),
                        review_file_sha256="1" * 64,
                    )
                )
    return factory


def test_vattenfall_payments_without_documents(subjects):
    q = "How much did I pay Vattenfall in 2026?"
    data = retrieve_subject(q, subjects)
    assert data["status"] == "MATCH_FOUND"
    assert len(data["transactions"]) == 1 and not data["documents"]
    assert Decimal(data["totals"][0]["debit_total"]) == 10
    assert data["totals"][0]["payment_count"] == 1
    assert data["filters"]["context"] is None
    card = subject_cards(q, data)
    assert "€10.00" in card["direct_answer"]
    assert card["presentation_mode"] == "FINANCIAL_TOTAL"
    assert "tax" not in card["direct_answer"].lower()


def test_ambiguous_merchant_labels_and_all_dates(subjects):
    q = "What evidence do we have for Oikea Konekauppa?"
    data = retrieve_subject(q, subjects)
    assert data["status"] == "MATCH_FOUND" and len(data["transactions"]) == 2
    assert data["transactions"][0]["business_context"] == "PERSONAL"
    assert data["transactions"][1]["business_context"] is None
    assert data["transactions"][1]["category"] is None
    card = subject_cards(q, data)
    assert "unresolved" in card["human_review_note"]
    assert "FORESTRY" not in str(card)
    assert "PERSONAL" in str(card)
    assert card["presentation_mode"] == "NAMED_SUBJECT"


def test_tax_uses_same_identity_without_tax_inference(subjects):
    q = "Can I deduct Oikea Konekauppa purchases?"
    data = retrieve_subject(q, subjects)
    card = subject_cards(q, data)
    assert len(data["transactions"]) == 2
    assert card["presentation_mode"] == "TAX_BOUNDARY"
    assert "does not decide tax deductibility" in card["direct_answer"]


def test_provider_evidence_is_not_tax(subjects):
    q = "What evidence do we have for Vattenfall?"
    data = retrieve_subject(q, subjects)
    assert len(data["transactions"]) == 2
    assert subject_cards(q, data)["presentation_mode"] == "NAMED_SUBJECT"


def test_unknown_merchant_safe_no_match(subjects):
    data = retrieve_subject("What evidence do we have for Unseen Merchant?", subjects)
    assert data["status"] == "NO_MATCH"
    assert not data["transactions"] and not data["totals"]


def test_recipient_separate_from_processor(subjects):
    data = retrieve_subject("What evidence do we have for Synthetic Recipient?", subjects)
    assert data["status"] == "MATCH_FOUND" and len(data["transactions"]) == 1
    assert data["canonical_subject"] == "Synthetic Recipient"
    assert data["transactions"][0]["business_context"] is None


def test_pilot_integration_preserves_accepted_validation(subjects, tmp_path, monkeypatch):
    import json

    from test_pilot import Model, ask, make_pilot

    from tapio.pilot import service

    monkeypatch.setattr(service, "readonly_session", lambda engine: subjects())
    q = "How much did I pay Vattenfall in 2026?"
    pilot = make_pilot(tmp_path, Model())
    pilot.subject_loader = retrieve_subject
    public = ask(pilot, q)
    assert public.evidence_state != "UNSUPPORTED"
    assert "€10.00" in public.direct_answer
    assert public.optional_details["named_subject"]["status"] == "MATCH_FOUND"
    record = json.loads((pilot.history.directory(public.session.id) / "question.json").read_text())
    assert record["named_subject"]["transactions"][0]["id"] not in public.model_dump_json()
    assert record["final_references"]["references"]
    assert record["source_fingerprints_verified"]
    stages = record["diagnostics"]["stages"]
    assert (
        stages.index("FINAL_VALIDATION")
        < stages.index("NAMED_SUBJECT_RETRIEVAL")
        < stages.index("SOURCE_POSTFLIGHT")
    )
    bad = make_pilot(tmp_path / "bad", Model(bad=True))
    bad.subject_loader = retrieve_subject
    rejected = ask(bad, q)
    assert rejected.evidence_state == "UNSUPPORTED"
    record = json.loads((bad.history.directory(rejected.session.id) / "question.json").read_text())
    assert record["named_subject"] is None


def test_document_only_match_and_reconciliation(factory):
    from apps.api.app.domain.models import Document, Invoice

    with factory() as db, db.begin():
        run = ImportRun(
            source_type="synthetic",
            source_filename="synthetic",
            sha256="2" * 64,
            parser_version="test",
            status=ImportStatus.COMPLETED,
        )
        db.add(run)
        db.flush()
        doc = Document(
            document_type="invoice",
            source_filename="synthetic.pdf",
            sha256="3" * 64,
            import_run_id=run.id,
            document_date=date(2026, 1, 2),
            document_metadata={"vendor": "Synthetic Document Oy", "parser_version": "test"},
        )
        db.add(doc)
        db.flush()
        db.add(
            Invoice(
                document_id=doc.id,
                vendor="Synthetic Document Oy",
                total_eur=Decimal("10"),
                invoice_date=date(2026, 1, 2),
            )
        )
    data = retrieve_subject("What evidence do we have for Synthetic Document?", factory)
    assert data["status"] == "MATCH_FOUND"
    assert not data["transactions"]
    assert len(data["documents"]) == len(data["invoices"]) == 1
    card = subject_cards("What evidence do we have for Synthetic Document?", data)
    assert len(card["optional_details"]["documents"]) == 1
    assert len(card["optional_details"]["reconciliation"]) == 1


def test_unknown_merchant_completed_lookup_has_no_match_badges(subjects, tmp_path, monkeypatch):
    from test_pilot import ask, make_pilot

    from tapio.pilot import service

    monkeypatch.setattr(service, "readonly_session", lambda engine: subjects())
    pilot = make_pilot(tmp_path)
    pilot.subject_loader = retrieve_subject
    response = ask(pilot, "What evidence do we have for Completely Fake Merchant XYZ?")
    assert response.failure_category == "NO_MATCH"
    assert response.evidence_states == ["SUPPORTED", "NO_MATCH"]
    assert "unavailable" not in response.direct_answer
