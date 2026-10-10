"""Bank source identity, raw audit data and rule provenance.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ["source_namespace", "source_transaction_id", "transaction_type_code"]:
        op.add_column("transactions", sa.Column(name, sa.String(), nullable=True))
    for name in ["raw_source", "rule_metadata"]:
        op.add_column("transactions", sa.Column(name, postgresql.JSONB(), nullable=True))
    op.create_unique_constraint(
        "uq_bank_source_identity", "transactions", ["source_namespace", "source_transaction_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_bank_source_identity", "transactions", type_="unique")
    for name in [
        "rule_metadata",
        "raw_source",
        "transaction_type_code",
        "source_transaction_id",
        "source_namespace",
    ]:
        op.drop_column("transactions", name)
