"""Shared identity across intent paths; synthetic evidence only, no model calls."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from test_energy_load import factory as factory

from apps.api.app.domain.models import (
    Document,
    ImportRun,
    Invoice,
    Transaction,
    TransactionLabelReview,
)
from tapio.pilot.named_subject import retrieve_subject, subject_cards
from tapio.pilot.subject_identity import extract_subject, normalize_subject, resolve_subject

NAMES = ["oikea konekaupp viitasaari", "Elenia Verkko Oyj", "k-rauta viitasaari pielavesi"]


@pytest.mark.parametrize(
    "subject,canonical",
    [
        ("Oikea Konekauppa", "Oikea Konekauppa"),
        ("Elenia", "Elenia Verkko Oyj"),
        ("K-Rauta", "K-Rauta"),
    ],
)
def test_cross_intent_identity(subject, canonical):
    questions = [
        f"What evidence do we have for {subject}?",
        f"Can I deduct {subject} purchases?",
        f"How much did I pay {subject} in 2026?",
        f"How much did I spend at {subject} in 2026?",
        f"What payments do we have for {subject}?",
        f"What do we know about {subject} purchases?",
        f"Show documents from {subject}",
        f"List {subject} invoices",
        f"Show reconciliation for {subject}",
        f"Reconcile {subject} payments",
    ]
    identities = [resolve_subject(extract_subject(q)["text"], NAMES)["identity"] for q in questions]
    assert all(i == identities[0] for i in identities)
    assert identities[0]["canonical_name"] == canonical


@pytest.mark.parametrize(
    "name", ["Elenia", "Elenia Verkko", "Elenia Verkko Oyj", "ELENIA VERKKO OY."]
)
def test_elenia_variants(name):
    assert resolve_subject(name, NAMES)["canonical_subject"] == "Elenia Verkko Oyj"


@pytest.mark.parametrize(
    "name", ["K-Rauta", "K RAUTA", "Krauta", "Ｋ－ＲＡＵＴＡ", "K–Rauta", " K—RAUTA ", "K.Rauta"]
)
def test_unicode_hyphen_and_punctuation(name):
    assert resolve_subject(name, NAMES)["canonical_subject"] == "K-Rauta"
    assert normalize_subject("  Ｋ－ＲＡＵＴＡ  ") == "k rauta"


@pytest.mark.parametrize(
    "name", ["Elenia Other", "K-Rauta Other Town", "Kone", "Completely Fake Merchant XYZ"]
)
def test_no_prefix_or_fuzzy_match(name):
    assert resolve_subject(name, NAMES)["status"] == "NO_MATCH"


def test_descriptor_provenance_and_ambiguous_legal_names():
    result = resolve_subject("K-Rauta Viitasaari PIELAVESI", NAMES)
    assert result["method"] == "BANK_DESCRIPTOR_ALIAS"
    assert result["source_match_methods"]["k-rauta viitasaari pielavesi"] == "BANK_DESCRIPTOR_ALIAS"
    assert "k rauta viitasaari pielavesi" in result["identity"]["normalized_aliases"]
    assert (
        resolve_subject("Synthetic", ["Synthetic Oy", "Synthetic Oyj"])["status"]
        == "AMBIGUOUS_IDENTITY"
    )


@pytest.fixture(scope="module")
def evidence(factory):
    with factory() as db, db.begin():
        run = ImportRun(
            source_type="synthetic",
            source_filename="synthetic",
            sha256="4" * 64,
            parser_version="test",
            status="completed",
        )
        db.add(run)
        db.flush()
        for name, year, debit, reviewed in [
            (NAMES[0], 2026, "-30", True),
            (NAMES[1], 2026, "-10", True),
            (NAMES[1], 2025, "-20", False),
            (NAMES[2], 2025, "-40", False),
            (NAMES[2], 2025, "-50", True),
        ]:
            t = Transaction(
                booking_date=date(year, 1, 2),
                amount=Decimal(debit),
                currency="EUR",
                direction="outgoing",
                normalized_counterparty=name,
                source_file="synthetic",
                import_run_id=run.id,
                category="TAX",
                business_context="forestry",
            )
            db.add(t)
            db.flush()
            if reviewed:
                db.add(
                    TransactionLabelReview(
                        transaction_id=t.id,
                        suggested_category_snapshot="TAX",
                        suggested_context_snapshot="FORESTRY",
                        confirmed_category="OTHER",
                        confirmed_business_context="PERSONAL",
                        review_status="REVIEWED",
                        reviewer="synthetic",
                        reviewed_at=datetime.now(UTC),
                        review_file_sha256="5" * 64,
                    )
                )
        doc = Document(
            document_type="invoice",
            source_filename="synthetic.pdf",
            sha256="6" * 64,
            import_run_id=run.id,
            document_date=date(2025, 1, 2),
            document_metadata={"vendor": NAMES[1], "parser_version": "test"},
        )
        db.add(doc)
        db.flush()
        db.add(
            Invoice(
                document_id=doc.id,
                vendor=NAMES[1],
                invoice_date=date(2025, 1, 2),
                total_eur=Decimal("20"),
            )
        )
    return factory


@pytest.mark.parametrize("subject", ["Oikea Konekauppa", "Elenia", "K-Rauta"])
def test_evidence_tax_payment_use_identical_identity_and_evidence(evidence, subject):
    results = [
        retrieve_subject(q, evidence)
        for q in [
            f"What evidence do we have for {subject}?",
            f"Can I deduct {subject} purchases?",
            f"How much did I spend at {subject}?",
            f"Show documents from {subject}",
            f"Show reconciliation for {subject}",
        ]
    ]
    for data in results:
        assert data["status"] == "MATCH_FOUND"
        assert data["trace"]["resolver"] == "tapio.pilot.subject_identity.resolve_subject"
        assert data["trace"]["bank_query_invoked"] and data["trace"]["document_query_invoked"]
        for key in ["identity", "transactions", "documents", "invoices", "totals", "filters"]:
            assert data[key] == results[0][key]
    tax = subject_cards(f"Can I deduct {subject} purchases?", results[1])
    normal = subject_cards(f"What evidence do we have for {subject}?", results[0])
    assert tax["presentation_mode"] == "TAX_BOUNDARY"
    assert normal["presentation_mode"] == "NAMED_SUBJECT"
    assert "does not decide tax deductibility" in tax["direct_answer"]
    assert "deduct" not in normal["direct_answer"]
    assert "CANONICAL_EXACT" not in str(normal["evidence_summary"])


def test_requested_period_and_independent_documents(evidence):
    q = "How much did I pay Elenia in 2026?"
    data = retrieve_subject(q, evidence)
    assert len(data["transactions"]) == 1 and not data["documents"]
    assert Decimal(data["totals"][0]["debit_total"]) == 10
    assert data["totals"][0]["payment_count"] == 1
    assert "2026" in subject_cards(q, data)["direct_answer"]
    all_dates = retrieve_subject("What evidence do we have for Elenia?", evidence)
    assert len(all_dates["transactions"]) == 2 and len(all_dates["documents"]) == 1
    assert all_dates["identity"]["matched_source_identifiers"]["documents"]
    legal = retrieve_subject("What evidence do we have for Elenia Verkko Oyj?", evidence)
    assert legal["identity"] == all_dates["identity"]


def test_no_current_year_guess_or_context_inference(evidence):
    data = retrieve_subject("What evidence do we have for K-Rauta?", evidence)
    assert len(data["transactions"]) == 2
    assert {r["business_context"] for r in data["transactions"]} == {None, "PERSONAL"}
    assert "FORESTRY" not in str(data["transactions"])
    card = subject_cards("What evidence do we have for K-Rauta?", data)
    assert "unresolved" in card["human_review_note"]
    dated = retrieve_subject("How much did I spend at K-Rauta in 2026?", evidence)
    assert dated["status"] == "NO_MATCH" and dated["canonical_subject"] == "K-Rauta"
    assert not dated["transactions"] and not dated["totals"]
    assert (
        "0 matching bank payments"
        in subject_cards("How much did I spend at K-Rauta in 2026?", dated)["direct_answer"]
    )


def test_unknown_merchant_does_not_manufacture_identity(evidence):
    data = retrieve_subject("What evidence do we have for Completely Fake Merchant XYZ?", evidence)
    assert data["status"] == "NO_MATCH" and data["identity"] is None
    assert not data["transactions"]


@pytest.mark.parametrize(
    "question,status,canonical",
    [
        ("What evidence do we have for Oikea Konekauppa?", "MATCH_FOUND", "Oikea Konekauppa"),
        ("Can I deduct Oikea Konekauppa purchases?", "MATCH_FOUND", "Oikea Konekauppa"),
        ("How much did I pay Elenia in 2026?", "MATCH_FOUND", "Elenia Verkko Oyj"),
        ("What evidence do we have for Elenia?", "MATCH_FOUND", "Elenia Verkko Oyj"),
        ("What evidence do we have for Elenia Verkko Oyj?", "MATCH_FOUND", "Elenia Verkko Oyj"),
        ("What evidence do we have for K-Rauta?", "MATCH_FOUND", "K-Rauta"),
        ("How much did I spend at K-Rauta in 2026?", "NO_MATCH", "K-Rauta"),
        ("Can I deduct K-Rauta purchases?", "MATCH_FOUND", "K-Rauta"),
        ("What evidence do we have for Completely Fake Merchant XYZ?", "NO_MATCH", None),
    ],
)
def test_pilot_end_to_end_intent_matrix(evidence, tmp_path, question, status, canonical):
    import json

    from test_pilot import ask, make_pilot

    pilot = make_pilot(tmp_path)
    pilot.subject_loader = lambda question, session_factory: retrieve_subject(question, evidence)
    public = ask(pilot, question)
    assert public.evidence_state != "UNSUPPORTED"
    assert public.optional_details["named_subject"]["status"] == status
    assert public.optional_details["named_subject"]["canonical_subject"] == canonical
    record = json.loads((pilot.history.directory(public.session.id) / "question.json").read_text())
    assert record["final_references"]["references"]
    assert record["source_fingerprints_verified"]
    assert record["named_subject"]["trace"]["resolver_version"] == "subject-identity-v2"
    for row in record["named_subject"]["transactions"]:
        assert row["id"] not in public.model_dump_json()
    if question.startswith("Can I deduct"):
        assert public.presentation_mode == "TAX_BOUNDARY"
    else:
        assert public.presentation_mode != "TAX_BOUNDARY"
    assert "subject_identity" not in str(public.evidence_summary)
