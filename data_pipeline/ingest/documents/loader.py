"""Atomic immutable document imports with audit attempts and serialized identity checks."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.domain.enums import DocumentType, ImportStatus
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
from data_pipeline.documents.base import DocumentError
from data_pipeline.documents.detect import parser_for

from . import extract

LOCK = 857034921


def persist(session, parsed, run, digest, filename):
    dtype = (
        DocumentType.INVOICE
        if parsed.bill
        else DocumentType.TIMBER_SALE
        if parsed.sale
        else DocumentType.OTHER
    )
    doc = Document(
        document_type=dtype,
        source_filename=filename,
        sha256=digest,
        document_date=parsed.document_date,
        import_run_id=run.id,
        document_metadata=parsed.model_dump(mode="json"),
    )
    session.add(doc)
    session.flush()
    if parsed.bill:
        bill = parsed.bill
        invoice = Invoice(
            document_id=doc.id,
            **bill.model_dump(
                include={
                    "vendor",
                    "invoice_number",
                    "invoice_date",
                    "due_date",
                    "subtotal_eur",
                    "vat_eur",
                    "total_eur",
                }
            ),
        )
        session.add(invoice)
        session.flush()
        for index, line in enumerate(bill.lines, 1):
            data = line.model_dump(
                exclude={"page", "usage_point", "price_basis", "printed_price_quantum", "warnings"}
            )
            session.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    **data,
                    source_metadata={
                        "line_number": index,
                        "page": line.page,
                        "usage_point": line.usage_point,
                        "price_basis": line.price_basis,
                        "printed_price_quantum": str(line.printed_price_quantum)
                        if line.printed_price_quantum is not None
                        else None,
                        "warnings": line.warnings,
                    },
                )
            )
        for e in bill.energy:
            meter = session.scalar(
                select(MeteringPoint).where(MeteringPoint.external_code == e.usage_point)
            )
            if meter is None:
                meter = MeteringPoint(external_code=e.usage_point)
                session.add(meter)
                session.flush()
            session.add(
                EnergyBillDetails(
                    invoice_id=invoice.id,
                    metering_point_id=meter.id,
                    **e.model_dump(exclude={"usage_point", "product", "fuse_size", "page"}),
                )
            )
    if parsed.sale:
        sale = ForestrySale(
            document_id=doc.id,
            **parsed.sale.model_dump(exclude={"association", "lines", "differences"}),
        )
        session.add(sale)
        session.flush()
        for line in parsed.sale.lines:
            session.add(
                ForestrySaleLine(forestry_sale_id=sale.id, **line.model_dump(exclude={"page"}))
            )
    session.flush()
    return doc


def import_document(raw, *, filename, session_factory, parser_override=None):
    digest = sha256(raw).hexdigest()
    filename = Path(filename).name
    parsed = None
    error = None
    version = "pdf-layout-1"
    try:
        pages = extract(raw)
        parser = parser_override or parser_for(pages)
        version = parser.VERSION
        parsed = parser.parse(pages)
        if parsed.parser_version != version:
            raise DocumentError("parser_version_mismatch")
    except DocumentError as exc:
        error = str(exc)
    except (ValidationError, ValueError, IndexError, KeyError):
        error = "document_validation_failed"
    with session_factory() as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        run = ImportRun(
            source_type="pdf_document",
            source_filename=filename,
            sha256=digest,
            parser_version=version,
            status=ImportStatus.RUNNING,
            source_metadata={},
        )
        session.add(run)
        session.flush()
        result = {
            "status": "failed",
            "documents": 0,
            "invoices": 0,
            "invoice_lines": 0,
            "forestry_sales": 0,
            "forestry_sale_lines": 0,
            "parser_version": version,
        }
        if not error:
            existing = session.scalar(select(Document).where(Document.sha256 == digest))
            if existing:
                if existing.document_metadata.get("parser_version") != version:
                    error = "parser_revision_requires_explicit_review"
                elif existing.document_metadata != parsed.model_dump(mode="json"):
                    error = "same_version_output_conflict"
                else:
                    result["status"] = "already_imported"
                    run.source_metadata = {"existing_document_id": str(existing.id)}
            else:
                try:
                    with session.begin_nested():
                        # A business identity in different bytes requires explicit review.
                        if parsed.bill:
                            duplicate = session.scalar(
                                select(Invoice.id).where(
                                    Invoice.vendor == parsed.bill.vendor,
                                    Invoice.invoice_number == parsed.bill.invoice_number,
                                )
                            )
                            if duplicate:
                                raise DocumentError("invoice_identity_conflict")
                        if parsed.sale:
                            duplicate = session.scalar(
                                select(ForestrySale.id).where(
                                    ForestrySale.buyer == parsed.sale.buyer,
                                    ForestrySale.contract_number == parsed.sale.contract_number,
                                )
                            )
                            if duplicate:
                                raise DocumentError("sale_identity_conflict")
                        persist(session, parsed, run, digest, filename)
                        result.update(
                            status="imported",
                            documents=1,
                            invoices=int(parsed.bill is not None),
                            invoice_lines=len(parsed.bill.lines) if parsed.bill else 0,
                            forestry_sales=int(parsed.sale is not None),
                            forestry_sale_lines=len(parsed.sale.lines) if parsed.sale else 0,
                        )
                except DocumentError as exc:
                    error = str(exc)
                except SQLAlchemyError:
                    error = "document_persistence_failed"
        run.status = ImportStatus.FAILED if error else ImportStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.row_count = result["documents"]
        if error:
            run.source_metadata = {"error_code": error}
            result["error_code"] = error
        else:
            run.source_metadata = {
                **run.source_metadata,
                "kind": parsed.kind,
                "page_count": parsed.page_count,
                "vendor": parsed.vendor,
            }
        return result
