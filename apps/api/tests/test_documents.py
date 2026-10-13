"""Synthetic PDF, parser, arithmetic, provenance and immutable-import tests."""

import copy
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from apps.api.app.domain.models import (
    Document,
    ForestrySale,
    ForestrySaleLine,
    ImportRun,
    Invoice,
    InvoiceLine,
)
from apps.api.tests.document_fixtures import contract, elenia, mhy, pdf, sale, vattenfall
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.documents.base import DocumentError, Line
from data_pipeline.documents.detect import parser_for
from data_pipeline.ingest.documents import extract
from data_pipeline.ingest.documents.loader import import_document


def parse(pages):
    return parser_for(pages).parse(pages)


@pytest.mark.parametrize("fixture", [mhy, elenia, vattenfall, sale, contract])
def test_synthetic_pdf_text_roundtrip(fixture):
    obj = parse(extract(pdf(fixture())))
    assert obj.page_count == len(fixture())


@pytest.mark.parametrize("variant", [1, 2])
def test_mhy_headers_quantity_vat(variant):
    bill = parse(mhy(variant=variant)).bill
    assert bill.invoice_number == "9001" and bill.customer == "Synthetic Customer"
    assert bill.invoice_date.isoformat() == "2026-02-01"
    assert bill.due_date.isoformat() == "2026-02-15"
    assert bill.lines[0].quantity == Decimal("10" if variant == 1 else "2")
    assert bill.lines[0].unit == ("m3" if variant == 1 else "ha")
    assert bill.lines[0].unit_price_eur == Decimal("2" if variant == 1 else "10")
    assert bill.lines[0].vat_rate == Decimal("25.5")
    assert bill.subtotal_eur == 20 and bill.vat_eur == Decimal("5.10")
    assert bill.total_eur == Decimal("25.10")


def test_vattenfall_consumption_export_separate():
    bill = parse(vattenfall()).bill
    assert bill.invoice_number == "80001" and bill.total_eur == Decimal("13.81")
    assert bill.customer == "Synthetic Customer"
    assert len(bill.lines) == 4 and len(bill.energy) == 2
    consumption, export = bill.energy
    assert consumption.consumption_kwh == 100 and consumption.solar_export_kwh is None
    assert consumption.base_fee_eur == Decimal("2.51")
    assert consumption.energy_price_eur_per_kwh == Decimal(".1255")
    assert export.solar_export_kwh == 10 and export.consumption_kwh is None
    assert export.export_price_eur_per_kwh == Decimal("-.13")
    assert export.export_margin_eur_per_kwh == Decimal(".005")
    assert consumption.usage_point != export.usage_point
    assert [line.page for line in bill.lines] == [3, 3, 5, 5]


def test_elenia_all_six_billed_lines():
    bill = parse(elenia()).bill
    assert len(bill.lines) == 6
    assert [line.gross_amount_eur for line in bill.lines] == list(
        map(Decimal, ["12.55", "1.26", "1.25", "2.51", "0", "0"])
    )
    assert bill.lines[1].description == "Talviarkipäiväsiirto"
    assert bill.lines[2].description == "Muun ajan siirto"
    assert bill.lines[3].quantity == 200
    assert bill.energy[0].product == "Vuodenaikasiirto 3x25 A"
    assert bill.energy[0].fuse_size == "3x25 A"
    assert bill.energy[0].consumption_kwh == 200
    assert bill.energy[1].solar_export_kwh == 12
    assert bill.lines[0].usage_point != bill.lines[-1].usage_point


@pytest.mark.parametrize("production", [False, True])
def test_contract_metadata(production):
    facts = parse(contract(production)).contract
    assert facts["effective_date"] == "2026-01-01"
    assert facts["price_sheet_effective_dates"] == ["2026-01-01"]
    assert facts["contract_number"] == "900000"
    if production:
        assert facts["production_fee_rule"]["exempt_below_kva"] == "50"
    else:
        assert facts["tariff"]["winter_weekday_time_rule"] == "ma-la klo 07-22"
        assert facts["tariff"]["winter_gross_snt_per_kwh"] == "2.51"
        assert facts["tariff"]["base_gross_eur_per_month"] == "12.55"


def test_forestry_sale_metadata_missing_planned_and_totals():
    obj = parse(sale()).sale
    assert obj.buyer == "Synthetic Buyer" and obj.total_area_ha == 2
    assert len(obj.lines) == 2 and obj.lines[1].estimated_volume_m3 is None
    assert obj.estimated_value_eur == 200 and obj.actual_value_eur == 250
    assert all(Decimal(v) == 0 for v in obj.differences.values())


def test_sale_mismatch_reported_never_forced():
    pages = [
        sale()[0].replace(
            "Puukauppa yhteensä 10,00 200,00 14,00 250,00",
            "Puukauppa yhteensä 10,00 200,00 15,00 260,00",
        )
    ]
    obj = parse(pages)
    assert obj.sale.actual_value_eur == 260
    assert Decimal(obj.sale.differences["actual_value_eur"]) == -10
    assert obj.warnings == ["sale_totals_differ"]


@pytest.mark.parametrize(
    "fixture,old,new",
    [
        (mhy, "25,10 €", "25,11 €"),
        (vattenfall, "13,81 eur", "13,82 eur"),
        (elenia, "Euro 17,57", "Euro 17,58"),
    ],
)
def test_invoice_total_mismatch_rejected(fixture, old, new):
    with pytest.raises((ValidationError, DocumentError)):
        parse([p.replace(old, new) for p in fixture()])


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", "-1"),
        ("vat_rate", "101"),
        ("unit_price_eur", "NaN"),
        ("page", 0),
        ("usage_point", "abc"),
    ],
)
def test_invalid_canonical_line_rejected(field, value):
    data = {
        "description": "Synthetic",
        "quantity": "1",
        "unit_price_eur": "10",
        "net_amount_eur": "10",
        "vat_amount_eur": "0",
        "gross_amount_eur": "10",
        "page": 1,
    }
    data[field] = value
    with pytest.raises(ValidationError):
        Line(**data)


def test_unsupported_and_image_only():
    with pytest.raises(DocumentError, match="unsupported_document_layout"):
        parse(["Unknown synthetic document"])
    with pytest.raises(DocumentError, match="invalid_pdf"):
        extract(b"not pdf")
    with pytest.raises(DocumentError, match="image_only_or_empty_page"):
        extract(pdf([""]))


def counts(session):
    return [
        session.scalar(select(func.count()).select_from(model))
        for model in (Document, Invoice, InvoiceLine, ForestrySale, ForestrySaleLine)
    ]


def test_import_hash_provenance_idempotency(factory):
    raw = pdf(mhy(number=str(uuid4().int)))
    result = import_document(raw, filename="/private/synthetic.pdf", session_factory=factory)
    assert result["status"] == "imported" and result["invoice_lines"] == 1
    with factory() as session:
        before = counts(session)
        doc = session.scalar(select(Document).where(Document.sha256 == sha256(raw).hexdigest()))
        assert doc.source_filename == "synthetic.pdf"
        assert doc.document_metadata["page_count"] == 1
        run = session.get(ImportRun, doc.import_run_id)
        assert run.parser_version == "mhy-invoice-1" and run.completed_at
    again = import_document(raw, filename="renamed.pdf", session_factory=factory)
    assert again["status"] == "already_imported"
    with factory() as session:
        assert counts(session) == before


def test_parser_revision_never_duplicates_facts(factory):
    pages = mhy(number=str(uuid4().int))
    raw = pdf(pages)
    assert (
        import_document(raw, filename="synthetic.pdf", session_factory=factory)["status"]
        == "imported"
    )
    obj = parse(pages)
    obj.parser_version = "synthetic-v2"
    override = SimpleNamespace(VERSION="synthetic-v2", parse=lambda _: obj)
    result = import_document(
        raw, filename="synthetic.pdf", session_factory=factory, parser_override=override
    )
    assert result["error_code"] == "parser_revision_requires_explicit_review"


def test_rollback_leaves_failure_audit(factory, monkeypatch):
    from data_pipeline.ingest.documents import loader

    original = loader.persist

    def fail(*args):
        original(*args)
        raise DocumentError("synthetic_failure")

    monkeypatch.setattr(loader, "persist", fail)
    with factory() as session:
        before = counts(session)
    raw = pdf(mhy(number=str(uuid4().int)))
    result = import_document(raw, filename="synthetic.pdf", session_factory=factory)
    assert result["error_code"] == "synthetic_failure"
    with factory() as session:
        assert counts(session) == before
        run = session.scalar(select(ImportRun).where(ImportRun.sha256 == sha256(raw).hexdigest()))
        assert run.status.name == "FAILED"


def test_different_bytes_same_invoice_requires_review(factory):
    pages = mhy(number=str(uuid4().int))
    assert (
        import_document(pdf(pages), filename="synthetic.pdf", session_factory=factory)["status"]
        == "imported"
    )
    changed = copy.deepcopy(pages)
    changed[0] += "\nSynthetic footer"
    result = import_document(pdf(changed), filename="different.pdf", session_factory=factory)
    assert result["error_code"] == "invoice_identity_conflict"


def test_vattenfall_alternate_customer_header():
    pages = vattenfall()
    pages[0] = pages[0].replace("Puh. 020 722 9000", "Avoinna arkisin klo 8-17")
    assert parse(pages).bill.customer == "Synthetic Customer"


def test_unreasonable_printed_rate_difference_rejected():
    with pytest.raises(ValidationError, match="line_printed_rate_outside_rounding_tolerance"):
        Line(
            description="Synthetic",
            quantity="100",
            unit_price_eur=".01",
            gross_amount_eur="50",
            price_basis="gross",
            printed_price_quantum=".0001",
            page=1,
        )


def test_concurrent_exact_import_inserts_once(factory):
    from concurrent.futures import ThreadPoolExecutor

    raw = pdf(mhy(number=str(uuid4().int)))

    def run(_):
        return import_document(raw, filename="synthetic.pdf", session_factory=factory)["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ["already_imported", "imported"]


def test_unsupported_pdf_failure_is_audited(factory):
    raw = pdf(["Synthetic unsupported document " + uuid4().hex])
    result = import_document(raw, filename="synthetic.pdf", session_factory=factory)
    assert result["error_code"] == "unsupported_document_layout"
    with factory() as session:
        run = session.scalar(select(ImportRun).where(ImportRun.sha256 == sha256(raw).hexdigest()))
        assert run.status.name == "FAILED" and run.row_count == 0
        assert (
            session.scalar(select(Document.id).where(Document.sha256 == sha256(raw).hexdigest()))
            is None
        )


def test_new_source_paths_are_private_by_default():
    import subprocess

    for path in [
        "data/interim/documents/extracted.txt",
        "data/processed/documents/report.json",
        "private-source.pdf",
    ]:
        result = subprocess.run(["git", "check-ignore", path], capture_output=True)
        assert result.returncode == 0


def test_same_version_changed_interpretation_is_not_silently_accepted(factory):
    pages = mhy(number=str(uuid4().int))
    raw = pdf(pages)
    assert (
        import_document(raw, filename="synthetic.pdf", session_factory=factory)["status"]
        == "imported"
    )
    obj = parse(pages)
    obj.bill.customer = "Another synthetic customer"
    override = SimpleNamespace(VERSION=obj.parser_version, parse=lambda _: obj)
    result = import_document(
        raw, filename="synthetic.pdf", session_factory=factory, parser_override=override
    )
    assert result["error_code"] == "same_version_output_conflict"


def test_first_vattenfall_customer_line_is_preserved():
    pages = vattenfall()
    pages[0] = pages[0].replace(
        "Puh. 020 722 9000", "Puh. 020 722 9000\nSynthetic estate       Avoinna arkisin klo 8-17"
    )
    assert parse(pages).bill.customer == "Synthetic Customer"
