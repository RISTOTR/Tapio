"""Append-only human confirmations; no source or legacy review backfill."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "confirmation_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.Uuid(), sa.ForeignKey("confirmation_revisions.id")),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.Column("knowledge_event", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("transaction_id", "sequence", name="uq_confirmation_sequence"),
        sa.CheckConstraint("action IN ('CONFIRM','CHANGE')", name="confirmation_action"),
    )
    op.create_index(
        "ix_confirmation_revisions_transaction_id", "confirmation_revisions", ["transaction_id"]
    )
    op.execute("""CREATE FUNCTION reject_confirmation_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'confirmation history is append-only'; END;
        $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER immutable_confirmation BEFORE UPDATE OR DELETE
        ON confirmation_revisions FOR EACH ROW EXECUTE FUNCTION reject_confirmation_mutation()""")


def downgrade():
    # An operator must export/review history before any removal; migrations cannot erase decisions.
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM confirmation_revisions) THEN
        RAISE EXCEPTION 'cannot downgrade populated confirmation history'; END IF; END $$""")
    op.drop_table("confirmation_revisions")
    op.execute("DROP FUNCTION reject_confirmation_mutation()")
