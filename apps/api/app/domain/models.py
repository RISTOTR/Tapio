from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.domain.base import Base
from apps.api.app.domain.enums import (
    BusinessContext,
    DocumentType,
    ImportStatus,
    TaxReviewStatus,
    TransactionDirection,
)


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column()
    source_filename: Mapped[str] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column()
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int | None] = mapped_column()
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="importstatus"), default=ImportStatus.PENDING
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class MeteringPoint(Base):
    __tablename__ = "metering_points"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_code: Mapped[str] = mapped_column(unique=True)
    address: Mapped[str | None] = mapped_column()
    contract_type: Mapped[str | None] = mapped_column()


class EnergyReading(Base):
    __tablename__ = "energy_readings"
    __table_args__ = (UniqueConstraint("metering_point_id", "timestamp", "source_grain"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    metering_point_id: Mapped[UUID] = mapped_column(ForeignKey("metering_points.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumption_kwh: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    solar_export_kwh: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    source_grain: Mapped[str] = mapped_column()
    import_run_id: Mapped[UUID] = mapped_column(ForeignKey("import_runs.id"), index=True)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    booking_date: Mapped[date] = mapped_column()
    value_date: Mapped[date | None] = mapped_column()
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(String(3))
    direction: Mapped[TransactionDirection] = mapped_column(
        Enum(TransactionDirection, name="transactiondirection")
    )
    raw_counterparty: Mapped[str | None] = mapped_column()
    normalized_counterparty: Mapped[str | None] = mapped_column()
    payment_intermediary: Mapped[str | None] = mapped_column()
    ultimate_recipient: Mapped[str | None] = mapped_column()
    reference: Mapped[str | None] = mapped_column()
    message: Mapped[str | None] = mapped_column()
    category: Mapped[str | None] = mapped_column()
    business_context: Mapped[BusinessContext | None] = mapped_column(
        Enum(BusinessContext, name="businesscontext")
    )
    source_file: Mapped[str] = mapped_column()
    import_run_id: Mapped[UUID] = mapped_column(ForeignKey("import_runs.id"), index=True)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType, name="documenttype"))
    source_filename: Mapped[str] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    document_date: Mapped[date | None] = mapped_column()
    import_run_id: Mapped[UUID] = mapped_column(ForeignKey("import_runs.id"), index=True)
    document_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    vendor: Mapped[str] = mapped_column()
    invoice_number: Mapped[str | None] = mapped_column()
    invoice_date: Mapped[date | None] = mapped_column()
    due_date: Mapped[date | None] = mapped_column()
    subtotal_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    vat_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    total_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    business_context: Mapped[BusinessContext | None] = mapped_column(
        Enum(BusinessContext, name="businesscontext")
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    description: Mapped[str] = mapped_column()
    product_code: Mapped[str | None] = mapped_column()
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column()
    unit_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    net_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    vat_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    gross_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class TransactionInvoiceAllocation(Base):
    __tablename__ = "transaction_invoice_allocations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    allocated_amount_eur: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    match_method: Mapped[str] = mapped_column()
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class EnergyBillDetails(Base):
    __tablename__ = "energy_bill_details"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    metering_point_id: Mapped[UUID] = mapped_column(ForeignKey("metering_points.id"), index=True)
    period_start: Mapped[date] = mapped_column()
    period_end: Mapped[date] = mapped_column()
    consumption_kwh: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    solar_export_kwh: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    energy_price_eur_per_kwh: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    base_fee_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    export_price_eur_per_kwh: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    export_margin_eur_per_kwh: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class ForestrySale(Base):
    __tablename__ = "forestry_sales"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    buyer: Mapped[str] = mapped_column()
    contract_number: Mapped[str | None] = mapped_column()
    sale_date: Mapped[date | None] = mapped_column()
    sale_type: Mapped[str | None] = mapped_column()
    municipality: Mapped[str | None] = mapped_column()
    total_area_ha: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    estimated_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    estimated_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class ForestrySaleLine(Base):
    __tablename__ = "forestry_sale_lines"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    forestry_sale_id: Mapped[UUID] = mapped_column(ForeignKey("forestry_sales.id"), index=True)
    harvest_type: Mapped[str | None] = mapped_column()
    timber_product: Mapped[str | None] = mapped_column()
    estimated_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    estimated_price_eur_per_m3: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual_price_eur_per_m3: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    estimated_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    actual_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))


class TaxReview(Base):
    __tablename__ = "tax_reviews"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    suggested_context: Mapped[BusinessContext | None] = mapped_column(
        Enum(BusinessContext, name="businesscontext")
    )
    suggested_treatment: Mapped[str | None] = mapped_column()
    suggested_confidence: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    confirmed_context: Mapped[BusinessContext | None] = mapped_column(
        Enum(BusinessContext, name="businesscontext")
    )
    status: Mapped[TaxReviewStatus] = mapped_column(
        Enum(TaxReviewStatus, name="taxreviewstatus"), default=TaxReviewStatus.UNREVIEWED
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column()
