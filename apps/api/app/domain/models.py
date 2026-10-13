from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
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
    __table_args__ = (
        UniqueConstraint(
            "source_namespace", "source_transaction_id", name="uq_bank_source_identity"
        ),
    )
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
    # Nullable only for legacy/non-bank records. Bank loader requires all source identity fields.
    source_namespace: Mapped[str | None] = mapped_column()
    source_transaction_id: Mapped[str | None] = mapped_column()
    transaction_type_code: Mapped[str | None] = mapped_column()
    raw_source: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rule_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Initial weak suggestions; human decisions live separately in TaxReview.
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
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
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
    __table_args__ = (
        UniqueConstraint("transaction_id", "invoice_id", name="uq_allocation_pair"),
        CheckConstraint("status IN ('CANDIDATE','CONFIRMED','REJECTED')", name="allocation_status"),
    )
    status: Mapped[str] = mapped_column(default="CANDIDATE", server_default="CANDIDATE")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
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


class TransactionLabelReview(Base):
    """Classification ground truth, independent of rule suggestions and TaxReview."""

    __tablename__ = "transaction_label_reviews"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('UNREVIEWED','REVIEWED','SKIPPED_AMBIGUOUS')",
            name="ck_label_status",
        ),
        CheckConstraint(
            "confirmed_category IN ('ELECTRICITY','GRID_DISTRIBUTION','FORESTRY_SERVICE',"
            "'TIMBER_INCOME','TAX','GROCERIES','FUEL','INSURANCE','MAINTENANCE','TRANSFER',"
            "'SUBSCRIPTION','TRAVEL','OTHER','UNKNOWN')",
            name="ck_label_category",
        ),
        CheckConstraint(
            "confirmed_business_context IN ('PERSONAL','PROPERTY','FORESTRY','UNKNOWN')",
            name="ck_label_context",
        ),
        CheckConstraint(
            "(review_status = 'REVIEWED' AND confirmed_category IS NOT NULL "
            "AND confirmed_business_context IS NOT NULL) OR "
            "(review_status != 'REVIEWED' AND confirmed_category IS NULL "
            "AND confirmed_business_context IS NULL)",
            name="ck_label_confirmation",
        ),
        CheckConstraint(
            "(review_status = 'UNREVIEWED' AND reviewed_at IS NULL AND reviewer IS NULL) OR "
            "(review_status != 'UNREVIEWED' AND reviewed_at IS NOT NULL "
            "AND reviewer IS NOT NULL AND length(trim(reviewer)) > 0 "
            "AND review_file_sha256 IS NOT NULL)",
            name="ck_label_reviewer",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), unique=True)
    suggested_category_snapshot: Mapped[str] = mapped_column()
    suggested_context_snapshot: Mapped[str] = mapped_column()
    confirmed_category: Mapped[str | None] = mapped_column()
    confirmed_business_context: Mapped[str | None] = mapped_column()
    review_status: Mapped[str] = mapped_column(default="UNREVIEWED")
    reviewer: Mapped[str | None] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column()
    label_source: Mapped[str] = mapped_column(default="review_queue_csv_v1")
    review_file_sha256: Mapped[str | None] = mapped_column(String(64))
    taxonomy_version: Mapped[str] = mapped_column(default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransactionReversalCandidate(Base):
    """Separate non-authoritative refund/debit links; preserve every possible pair."""

    __tablename__ = "transaction_reversal_candidates"
    __table_args__ = (
        UniqueConstraint("debit_id", "credit_id", name="uq_reversal_pair"),
        CheckConstraint("debit_id != credit_id", name="distinct_reversal_transactions"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    debit_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    credit_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
