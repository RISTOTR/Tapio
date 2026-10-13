"""Read-only verification of stored canonical facts, structured rows and provenance."""

import argparse
import json
from collections import Counter
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import (
    Document,
    EnergyBillDetails,
    ForestrySale,
    ForestrySaleLine,
    ImportRun,
    Invoice,
    InvoiceLine,
    MeteringPoint,
)
from data_pipeline.documents.base import ParsedDocument
from data_pipeline.documents.detect import parser_for
from data_pipeline.ingest.documents import extract


def verify(session, source_paths=()):
    sources = {sha256(Path(p).read_bytes()).hexdigest(): Path(p) for p in source_paths}
    documents = list(
        session.scalars(
            select(Document).join(ImportRun).where(ImportRun.source_type == "pdf_document")
        )
    )
    counts = Counter()
    details = []
    for doc in documents:
        canonical = ParsedDocument.model_validate(doc.document_metadata)
        run = session.get(ImportRun, doc.import_run_id)
        assert run.sha256 == doc.sha256 and run.parser_version == canonical.parser_version
        assert run.completed_at and run.status.name == "COMPLETED"
        if sources:
            assert doc.sha256 in sources, "document_source_missing_from_manifest"
            pages = extract(sources[doc.sha256].read_bytes())
            reparsed = parser_for(pages).parse(pages)
            assert reparsed.model_dump(mode="json") == doc.document_metadata, (
                "source_reparse_difference"
            )
        counts["documents"] += 1
        counts[canonical.kind] += 1
        report = {"kind": canonical.kind, "invoice_total": None}
        if canonical.bill:
            bill = canonical.bill
            invoices = list(session.scalars(select(Invoice).where(Invoice.document_id == doc.id)))
            assert len(invoices) == 1
            inv = invoices[0]
            counts["invoices"] += 1
            for key in (
                "vendor",
                "invoice_number",
                "invoice_date",
                "due_date",
                "subtotal_eur",
                "vat_eur",
                "total_eur",
            ):
                assert getattr(inv, key) == getattr(bill, key), "invoice_fact_difference"
            lines = list(
                session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id))
            )
            lines.sort(key=lambda row: row.source_metadata["line_number"])
            assert len(lines) == len(bill.lines)
            for db, parsed in zip(lines, bill.lines, strict=True):
                for key, value in parsed.model_dump(
                    exclude={
                        "page",
                        "usage_point",
                        "price_basis",
                        "printed_price_quantum",
                        "warnings",
                    }
                ).items():
                    assert getattr(db, key) == value, "invoice_line_fact_difference"
                assert db.source_metadata["page"] == parsed.page
                assert db.source_metadata["usage_point"] == parsed.usage_point
            counts["invoice_lines"] += len(lines)
            energies = session.execute(
                select(EnergyBillDetails, MeteringPoint.external_code)
                .join(MeteringPoint)
                .where(EnergyBillDetails.invoice_id == inv.id)
            ).all()
            assert len(energies) == len(bill.energy)
            for db, code in energies:
                parsed = next(e for e in bill.energy if e.usage_point == code)
                for key, value in parsed.model_dump(
                    exclude={"usage_point", "product", "fuse_size", "page"}
                ).items():
                    assert getattr(db, key) == value, "energy_fact_difference"
            counts["energy_components"] += len(energies)
            report.update(
                invoice_total=str(inv.total_eur),
                lines=len(lines),
                gross_line_difference=str(
                    sum((line.gross_amount_eur for line in lines), Decimal(0)) - inv.total_eur
                ),
            )
        if canonical.sale:
            sales = list(
                session.scalars(select(ForestrySale).where(ForestrySale.document_id == doc.id))
            )
            assert len(sales) == 1
            sale = sales[0]
            for key, value in canonical.sale.model_dump(
                exclude={"association", "lines", "differences"}
            ).items():
                assert getattr(sale, key) == value, "forestry_sale_fact_difference"
            lines = list(
                session.scalars(
                    select(ForestrySaleLine).where(ForestrySaleLine.forestry_sale_id == sale.id)
                )
            )
            assert len(lines) == len(canonical.sale.lines)
            fields = set(canonical.sale.lines[0].model_fields) - {"page"}
            expected = Counter(
                tuple(getattr(line, k) for k in sorted(fields)) for line in canonical.sale.lines
            )
            actual = Counter(tuple(getattr(line, k) for k in sorted(fields)) for line in lines)
            assert actual == expected, "forestry_line_fact_difference"
            counts["forestry_sales"] += 1
            counts["forestry_sale_lines"] += len(lines)
            report["sale_differences"] = canonical.sale.differences
        details.append(report)
    return dict(counts), details


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Private JSON array of local PDF paths")
    args = parser.parse_args(argv)
    paths = json.loads(args.manifest.read_text()) if args.manifest else []
    with SessionLocal() as session:
        counts, _ = verify(session, paths)
    print(json.dumps({"verified": True, **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
