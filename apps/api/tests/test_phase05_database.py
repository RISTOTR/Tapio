"""Real PostgreSQL tool/handoff tests in disposable migrated schemas."""

import asyncio
import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.domain.enums import ImportStatus, TransactionDirection
from apps.api.app.domain.models import (
    Document,
    EnergyReading,
    ImportRun,
    MeteringPoint,
    Transaction,
    TransactionLabelReview,
)
from apps.api.app.services.tool_queries import Queries
from apps.api.tests.document_fixtures import contract, pdf, sale, vattenfall
from apps.api.tests.gmail_fixtures import FakeGmail
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.energy_cost.types import hours
from data_pipeline.ingest.documents.loader import import_document
from integrations.gmail.auth import GmailSettings
from integrations.gmail.client import GmailClient
from integrations.gmail.evidence import accept_evidence
from tapio.agent.loop import run_agent
from tapio.agent.model import CallableModel
from tapio.tools import schemas as S
from tapio.tools.internal import internal_registry


@pytest.fixture(scope="module")
def seeded(factory):
    for fixture in (contract, vattenfall, sale):
        assert (
            import_document(pdf(fixture()), filename="synthetic.pdf", session_factory=factory)[
                "status"
            ]
            == "imported"
        )
    with factory() as s, s.begin():
        run = ImportRun(
            source_type="synthetic",
            source_filename="synthetic",
            sha256="0" * 64,
            parser_version="test",
            status=ImportStatus.COMPLETED,
        )
        s.add(run)
        s.flush()
        meter = s.scalar(
            select(MeteringPoint).where(MeteringPoint.external_code == "111111111111111111")
        )
        s.add_all(
            [
                EnergyReading(
                    metering_point_id=meter.id,
                    timestamp=t,
                    consumption_kwh=Decimal("1"),
                    solar_export_kwh=Decimal("0"),
                    source_grain="hourly",
                    import_run_id=run.id,
                )
                for t in hours(date(2026, 1, 1), date(2026, 1, 31))
            ]
        )
        for i in range(2):
            t = Transaction(
                booking_date=date(2026, 1, 1),
                amount=Decimal("-10"),
                currency="EUR",
                direction=TransactionDirection.OUTGOING,
                normalized_counterparty="Synthetic FI0012345678901234",
                category="TAX",
                raw_source={"IBAN": "SYNTHETIC-SECRET"},
                source_transaction_id="SYNTHETIC-ARCHIVE",
                source_file="synthetic",
                import_run_id=run.id,
            )
            s.add(t)
            s.flush()
            if i == 0:
                s.add(
                    TransactionLabelReview(
                        transaction_id=t.id,
                        suggested_category_snapshot="TAX",
                        suggested_context_snapshot="FORESTRY",
                        confirmed_category="ELECTRICITY",
                        confirmed_business_context="PROPERTY",
                        review_status="REVIEWED",
                        reviewer="synthetic",
                        reviewed_at=datetime.now(UTC),
                        review_file_sha256="1" * 64,
                    )
                )
    return Queries(factory)


def test_transaction_privacy_and_reviewed_labels(seeded):
    result = seeded.transactions(S.TransactionQuery())
    assert len(result.items) == 2
    payload = result.model_dump_json()
    assert "SYNTHETIC-SECRET" not in payload and "SYNTHETIC-ARCHIVE" not in payload
    assert "FI0012345678901234" not in payload
    assert "TAX" not in payload and "FORESTRY" not in payload
    assert {x.category for x in result.items} == {None, "ELECTRICITY"}
    assert len(seeded.transactions(S.TransactionQuery(category="ELECTRICITY")).items) == 1
    assert not seeded.transactions(S.TransactionQuery(category="TAX")).items


def test_energy_tool_complete_coverage(seeded):
    r = seeded.energy(
        S.EnergyQuery(date_from="2026-01-01", date_to="2026-01-31", metric="consumption_kwh")
    )
    assert r.total == 744 and r.hours == 744


def test_cost_service_reused(seeded):
    r = seeded.cost(S.CostQuery(date_from="2026-01-01", date_to="2026-01-31"))
    assert r.mode == "ACTUAL_RECONSTRUCTION"
    assert r.monthly[0].supplier_energy_cost == Decimal("93.37")
    assert r.provenance[0].source_document_id


def test_scenario_tool_preserves_measurements(seeded):
    from data_pipeline.energy_cost.scenarios import ElectricityScenario

    args = S.ScenarioQuery(
        date_from="2026-01-01",
        date_to="2026-01-31",
        scenario=ElectricityScenario(
            name="synthetic",
            import_pricing_type="fixed",
            fixed_import_price="0.10",
            supplier_monthly_fee="5",
            price_basis="GROSS",
            vat_rate="25.5",
        ),
    )
    result = seeded.scenario(args)
    assert result.mode == "SCENARIO" and result.result.monthly[0].supplier_energy_cost == Decimal(
        "74.40"
    )
    assert (
        seeded.energy(
            S.EnergyQuery(date_from="2026-01-01", date_to="2026-01-31", metric="consumption_kwh")
        ).total
        == 744
    )


def test_document_projection_no_full_text(seeded):
    result = seeded.documents(S.DocumentQuery())
    assert len(result.items) == 3
    for row in result.items:
        assert seeded.document_summary(S.DocumentID(document_id=row.id)) == row
        assert "usage_point" not in row.model_dump_json()
        assert not hasattr(row, "document_metadata")


def test_invoice_and_reconciliation_tools(seeded):
    items = seeded.invoices(S.InvoiceQuery(status="UNMATCHED")).items
    assert len(items) == 1
    result = seeded.invoice(S.InvoiceID(invoice_id=items[0].id))
    assert result.total_eur == Decimal("13.81")
    assert result.source_document_id and result.parser_version
    assert seeded.invoice_reconciliation(S.InvoiceID(invoice_id=result.id)).state == "UNMATCHED"


def test_forestry_tools(seeded):
    rows = seeded.forestry_sales(S.ForestryQuery()).items
    assert rows[0].actual_value_eur == 250
    assert seeded.forestry_sale(S.ForestryID(sale_id=rows[0].id)) == rows[0]
    assert not hasattr(rows[0], "contract_number")


def test_no_orm_leak_and_output_validation(seeded, tmp_path):
    registry = internal_registry(seeded, audit_path=tmp_path / "audit")
    result = asyncio.run(registry.call("query_transactions", {}))
    assert result["ok"]
    assert isinstance(result["data"]["items"][0]["amount"], str)
    assert isinstance(result["data"]["items"][0]["id"], str)


def test_database_readonly_enforced(seeded):
    with pytest.raises(DBAPIError), seeded.session() as s:
        s.execute(text("UPDATE transactions SET category='OTHER'"))


@pytest.mark.parametrize(
    "tool,args",
    [
        (
            "query_energy",
            {"date_from": "2026-01-01", "date_to": "2026-01-31", "metric": "consumption_kwh"},
        ),
        (
            "calculate_energy_cost",
            {"date_from": "2026-01-01", "date_to": "2026-01-31", "scope": "grid"},
        ),
        (
            "simulate_energy_scenario",
            {
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
                "scenario": {
                    "name": "Synthetic",
                    "import_pricing_type": "fixed",
                    "fixed_import_price": "0.10",
                    "supplier_monthly_fee": "5",
                    "price_basis": "GROSS",
                    "vat_rate": "25.5",
                },
            },
        ),
    ],
)
def test_agent_answers_only_deterministic_service_results(seeded, tmp_path, tool, args):
    turns = [{"call": {"name": tool, "arguments": args}}, {"references": [{"call_index": 0}]}]

    async def generate(messages, tools):
        return turns.pop(0)

    result = asyncio.run(
        run_agent(
            "Synthetic project question",
            CallableModel(generate),
            internal_registry(seeded, audit_path=tmp_path / "audit"),
        )
    )
    assert result["status"] == "COMPLETE" and result["results"][0]["ok"]
    assert result["results"][0]["tool"] == tool


def test_pdf_handoff_idempotency_provenance(factory, tmp_path):
    c = GmailClient(
        FakeGmail(), GmailSettings(cache=tmp_path / "cache", evidence=tmp_path / "evidence")
    )
    m = c.get_message("msg1")
    d = c.download_attachment("msg1", "attachment1")
    first = accept_evidence(
        m, c.settings, human_confirmed=True, download=d, session_factory=factory
    )
    second = accept_evidence(
        m, c.settings, human_confirmed=True, download=d, session_factory=factory
    )
    assert first.import_status == "imported" and second.import_status == "already_imported"
    assert first.document_sha256 == first.download_hash == d.sha256
    assert first.source_document_id == second.source_document_id
    assert first.attachment_id == "attachment1" and first.external_message_id == "msg1"
    with factory() as s:
        assert len(list(s.scalars(select(Document).where(Document.sha256 == d.sha256)))) == 1


def test_unsupported_handoff_preserves_cache_and_no_document(factory, tmp_path):
    fake = FakeGmail()
    fake.attachment = pdf(["Unsupported synthetic invoice layout"])
    c = GmailClient(fake, GmailSettings(cache=tmp_path / "cache", evidence=tmp_path / "evidence"))
    m = c.get_message("msg1")
    d = c.download_attachment("msg1", "attachment1")
    original = (c.settings.cache / "attachments" / (d.sha256 + ".pdf")).read_bytes()
    r = accept_evidence(m, c.settings, human_confirmed=True, download=d, session_factory=factory)
    assert r.import_status == "failed" and r.error_code == "unsupported_document_layout"
    assert hashlib.sha256(original).hexdigest() == d.sha256
    assert c.get_message("msg1") == m
    with factory() as s:
        assert not list(s.scalars(select(Document).where(Document.sha256 == d.sha256)))
