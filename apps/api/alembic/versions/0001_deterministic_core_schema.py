"""deterministic core schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Shared native enums are created once before their referencing tables.
    postgresql.ENUM("PENDING", "RUNNING", "COMPLETED", "FAILED", name="importstatus").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(
        "INVOICE", "TIMBER_SALE", "BANK_STATEMENT", "OTHER", name="documenttype"
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM("INCOMING", "OUTGOING", name="transactiondirection").create(
        op.get_bind(), checkfirst=False
    )
    postgresql.ENUM(
        "PERSONAL", "PROPERTY", "FORESTRY", "MIXED", "UNKNOWN", name="businesscontext"
    ).create(op.get_bind(), checkfirst=False)
    postgresql.ENUM(
        "UNREVIEWED",
        "LIKELY_BUSINESS_EXPENSE",
        "LIKELY_PERSONAL",
        "NEEDS_REVIEW",
        "CONFIRMED_BUSINESS_EXPENSE",
        "CONFIRMED_NON_BUSINESS",
        name="taxreviewstatus",
    ).create(op.get_bind(), checkfirst=False)
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING", "RUNNING", "COMPLETED", "FAILED", name="importstatus", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_runs")),
    )
    op.create_index(op.f("ix_import_runs_sha256"), "import_runs", ["sha256"], unique=False)
    op.create_table(
        "metering_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_code", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("contract_type", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metering_points")),
        sa.UniqueConstraint("external_code", name=op.f("uq_metering_points_external_code")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "document_type",
            postgresql.ENUM(
                "INVOICE",
                "TIMBER_SALE",
                "BANK_STATEMENT",
                "OTHER",
                name="documenttype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("source_filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name=op.f("fk_documents_import_run_id_import_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        op.f("ix_documents_import_run_id"), "documents", ["import_run_id"], unique=False
    )
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=False)
    op.create_table(
        "energy_readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("metering_point_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumption_kwh", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("solar_export_kwh", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("temperature_c", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("source_grain", sa.String(), nullable=False),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name=op.f("fk_energy_readings_import_run_id_import_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["metering_point_id"],
            ["metering_points.id"],
            name=op.f("fk_energy_readings_metering_point_id_metering_points"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_energy_readings")),
        sa.UniqueConstraint(
            "metering_point_id",
            "timestamp",
            "source_grain",
            name=op.f("uq_energy_readings_metering_point_id"),
        ),
    )
    op.create_index(
        op.f("ix_energy_readings_import_run_id"), "energy_readings", ["import_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_energy_readings_metering_point_id"),
        "energy_readings",
        ["metering_point_id"],
        unique=False,
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM("INCOMING", "OUTGOING", name="transactiondirection", create_type=False),
            nullable=False,
        ),
        sa.Column("raw_counterparty", sa.String(), nullable=True),
        sa.Column("normalized_counterparty", sa.String(), nullable=True),
        sa.Column("payment_intermediary", sa.String(), nullable=True),
        sa.Column("ultimate_recipient", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column(
            "business_context",
            postgresql.ENUM(
                "PERSONAL",
                "PROPERTY",
                "FORESTRY",
                "MIXED",
                "UNKNOWN",
                name="businesscontext",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("source_file", sa.String(), nullable=False),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["import_runs.id"],
            name=op.f("fk_transactions_import_run_id_import_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(
        op.f("ix_transactions_import_run_id"), "transactions", ["import_run_id"], unique=False
    )
    op.create_table(
        "forestry_sales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("buyer", sa.String(), nullable=False),
        sa.Column("contract_number", sa.String(), nullable=True),
        sa.Column("sale_date", sa.Date(), nullable=True),
        sa.Column("sale_type", sa.String(), nullable=True),
        sa.Column("municipality", sa.String(), nullable=True),
        sa.Column("total_area_ha", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("estimated_volume_m3", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("actual_volume_m3", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("estimated_value_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("actual_value_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_forestry_sales_document_id_documents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forestry_sales")),
    )
    op.create_index(
        op.f("ix_forestry_sales_document_id"), "forestry_sales", ["document_id"], unique=False
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("invoice_number", sa.String(), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("subtotal_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("vat_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("total_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column(
            "business_context",
            postgresql.ENUM(
                "PERSONAL",
                "PROPERTY",
                "FORESTRY",
                "MIXED",
                "UNKNOWN",
                name="businesscontext",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_invoices_document_id_documents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
    )
    op.create_index(op.f("ix_invoices_document_id"), "invoices", ["document_id"], unique=False)
    op.create_table(
        "tax_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "suggested_context",
            postgresql.ENUM(
                "PERSONAL",
                "PROPERTY",
                "FORESTRY",
                "MIXED",
                "UNKNOWN",
                name="businesscontext",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("suggested_treatment", sa.String(), nullable=True),
        sa.Column("suggested_confidence", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column(
            "confirmed_context",
            postgresql.ENUM(
                "PERSONAL",
                "PROPERTY",
                "FORESTRY",
                "MIXED",
                "UNKNOWN",
                name="businesscontext",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "UNREVIEWED",
                "LIKELY_BUSINESS_EXPENSE",
                "LIKELY_PERSONAL",
                "NEEDS_REVIEW",
                "CONFIRMED_BUSINESS_EXPENSE",
                "CONFIRMED_NON_BUSINESS",
                name="taxreviewstatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_tax_reviews_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tax_reviews")),
    )
    op.create_index(
        op.f("ix_tax_reviews_transaction_id"), "tax_reviews", ["transaction_id"], unique=False
    )
    op.create_table(
        "energy_bill_details",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("metering_point_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("consumption_kwh", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("solar_export_kwh", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("energy_price_eur_per_kwh", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("base_fee_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("export_price_eur_per_kwh", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("export_margin_eur_per_kwh", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], name=op.f("fk_energy_bill_details_invoice_id_invoices")
        ),
        sa.ForeignKeyConstraint(
            ["metering_point_id"],
            ["metering_points.id"],
            name=op.f("fk_energy_bill_details_metering_point_id_metering_points"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_energy_bill_details")),
    )
    op.create_index(
        op.f("ix_energy_bill_details_invoice_id"),
        "energy_bill_details",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_energy_bill_details_metering_point_id"),
        "energy_bill_details",
        ["metering_point_id"],
        unique=False,
    )
    op.create_table(
        "forestry_sale_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("forestry_sale_id", sa.Uuid(), nullable=False),
        sa.Column("harvest_type", sa.String(), nullable=True),
        sa.Column("timber_product", sa.String(), nullable=True),
        sa.Column("estimated_volume_m3", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("actual_volume_m3", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("estimated_price_eur_per_m3", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("actual_price_eur_per_m3", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("estimated_value_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("actual_value_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["forestry_sale_id"],
            ["forestry_sales.id"],
            name=op.f("fk_forestry_sale_lines_forestry_sale_id_forestry_sales"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forestry_sale_lines")),
    )
    op.create_index(
        op.f("ix_forestry_sale_lines_forestry_sale_id"),
        "forestry_sale_lines",
        ["forestry_sale_id"],
        unique=False,
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("unit_price_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("vat_rate", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("net_amount_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("vat_amount_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("gross_amount_eur", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], name=op.f("fk_invoice_lines_invoice_id_invoices")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_lines")),
    )
    op.create_index(
        op.f("ix_invoice_lines_invoice_id"), "invoice_lines", ["invoice_id"], unique=False
    )
    op.create_table(
        "transaction_invoice_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_amount_eur", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("match_method", sa.String(), nullable=False),
        sa.Column("match_confidence", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_transaction_invoice_allocations_invoice_id_invoices"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_transaction_invoice_allocations_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_invoice_allocations")),
    )
    op.create_index(
        op.f("ix_transaction_invoice_allocations_invoice_id"),
        "transaction_invoice_allocations",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction_invoice_allocations_transaction_id"),
        "transaction_invoice_allocations",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_transaction_invoice_allocations_transaction_id"),
        table_name="transaction_invoice_allocations",
    )
    op.drop_index(
        op.f("ix_transaction_invoice_allocations_invoice_id"),
        table_name="transaction_invoice_allocations",
    )
    op.drop_table("transaction_invoice_allocations")
    op.drop_index(op.f("ix_invoice_lines_invoice_id"), table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index(op.f("ix_forestry_sale_lines_forestry_sale_id"), table_name="forestry_sale_lines")
    op.drop_table("forestry_sale_lines")
    op.drop_index(
        op.f("ix_energy_bill_details_metering_point_id"), table_name="energy_bill_details"
    )
    op.drop_index(op.f("ix_energy_bill_details_invoice_id"), table_name="energy_bill_details")
    op.drop_table("energy_bill_details")
    op.drop_index(op.f("ix_tax_reviews_transaction_id"), table_name="tax_reviews")
    op.drop_table("tax_reviews")
    op.drop_index(op.f("ix_invoices_document_id"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_index(op.f("ix_forestry_sales_document_id"), table_name="forestry_sales")
    op.drop_table("forestry_sales")
    op.drop_index(op.f("ix_transactions_import_run_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_energy_readings_metering_point_id"), table_name="energy_readings")
    op.drop_index(op.f("ix_energy_readings_import_run_id"), table_name="energy_readings")
    op.drop_table("energy_readings")
    op.drop_index(op.f("ix_documents_sha256"), table_name="documents")
    op.drop_index(op.f("ix_documents_import_run_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_table("metering_points")
    op.drop_index(op.f("ix_import_runs_sha256"), table_name="import_runs")
    op.drop_table("import_runs")

    # Drop enum types only after all referencing tables have been removed.
    postgresql.ENUM(name="taxreviewstatus").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="businesscontext").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="transactiondirection").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="documenttype").drop(op.get_bind(), checkfirst=False)
    postgresql.ENUM(name="importstatus").drop(op.get_bind(), checkfirst=False)
