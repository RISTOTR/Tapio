"""Separate human classification labels from weak suggestions and tax review."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transaction_label_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("suggested_category_snapshot", sa.String(), nullable=False),
        sa.Column("suggested_context_snapshot", sa.String(), nullable=False),
        sa.Column("confirmed_category", sa.String(), nullable=True),
        sa.Column("confirmed_business_context", sa.String(), nullable=True),
        sa.Column("review_status", sa.String(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.String(), nullable=True),
        sa.Column("label_source", sa.String(), nullable=False),
        sa.Column("review_file_sha256", sa.String(64), nullable=True),
        sa.Column("taxonomy_version", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.UniqueConstraint("transaction_id"),
        sa.CheckConstraint(
            "review_status IN ('UNREVIEWED','REVIEWED','SKIPPED_AMBIGUOUS')", name="ck_label_status"
        ),
        sa.CheckConstraint(
            "confirmed_category IN ('ELECTRICITY','GRID_DISTRIBUTION','FORESTRY_SERVICE',"
            "'TIMBER_INCOME','TAX','GROCERIES','FUEL','INSURANCE','MAINTENANCE','TRANSFER',"
            "'SUBSCRIPTION','OTHER','UNKNOWN')",
            name="ck_label_category",
        ),
        sa.CheckConstraint(
            "confirmed_business_context IN ('PERSONAL','PROPERTY','FORESTRY','UNKNOWN')",
            name="ck_label_context",
        ),
        sa.CheckConstraint(
            "(review_status = 'REVIEWED' AND confirmed_category IS NOT NULL "
            "AND confirmed_business_context IS NOT NULL) OR "
            "(review_status != 'REVIEWED' AND confirmed_category IS NULL "
            "AND confirmed_business_context IS NULL)",
            name="ck_label_confirmation",
        ),
        sa.CheckConstraint(
            "(review_status = 'UNREVIEWED' AND reviewed_at IS NULL AND reviewer IS NULL) OR "
            "(review_status != 'UNREVIEWED' AND reviewed_at IS NOT NULL "
            "AND reviewer IS NOT NULL AND length(trim(reviewer)) > 0 "
            "AND review_file_sha256 IS NOT NULL)",
            name="ck_label_reviewer",
        ),
    )


def downgrade() -> None:
    op.drop_table("transaction_label_reviews")
