"""Line provenance and non-destructive candidate/confirmed reconciliation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "invoice_lines",
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "transaction_invoice_allocations",
        sa.Column("status", sa.String(), nullable=False, server_default="CANDIDATE"),
    )
    op.add_column(
        "transaction_invoice_allocations",
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "transaction_invoice_allocations",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_unique_constraint(
        "uq_allocation_pair", "transaction_invoice_allocations", ["transaction_id", "invoice_id"]
    )
    op.create_check_constraint(
        "allocation_status",
        "transaction_invoice_allocations",
        "status IN ('CANDIDATE','CONFIRMED','REJECTED')",
    )
    op.create_table(
        "transaction_reversal_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("debit_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("credit_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("debit_id", "credit_id", name="uq_reversal_pair"),
        sa.CheckConstraint("debit_id != credit_id", name="distinct_reversal_transactions"),
    )
    for col in ("debit_id", "credit_id"):
        op.create_index(
            f"ix_transaction_reversal_candidates_{col}", "transaction_reversal_candidates", [col]
        )


def downgrade():
    op.drop_table("transaction_reversal_candidates")
    op.drop_constraint("allocation_status", "transaction_invoice_allocations", type_="check")
    op.drop_constraint("uq_allocation_pair", "transaction_invoice_allocations", type_="unique")
    for col in ("created_at", "evidence", "status"):
        op.drop_column("transaction_invoice_allocations", col)
    op.drop_column("invoice_lines", "source_metadata")
