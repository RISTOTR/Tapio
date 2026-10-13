"""Allow the human-reviewed TRAVEL category without relabeling historical records."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

OLD = (
    "confirmed_category IN ('ELECTRICITY','GRID_DISTRIBUTION','FORESTRY_SERVICE',"
    "'TIMBER_INCOME','TAX','GROCERIES','FUEL','INSURANCE','MAINTENANCE','TRANSFER',"
    "'SUBSCRIPTION','OTHER','UNKNOWN')"
)
NEW = OLD.replace("'SUBSCRIPTION',", "'SUBSCRIPTION','TRAVEL',")


def upgrade():
    op.drop_constraint("ck_label_category", "transaction_label_reviews", type_="check")
    op.create_check_constraint("ck_label_category", "transaction_label_reviews", NEW)


def downgrade():
    # Existing TRAVEL reviews cause this transaction to fail safely, never relabel.
    op.drop_constraint("ck_label_category", "transaction_label_reviews", type_="check")
    op.create_check_constraint("ck_label_category", "transaction_label_reviews", OLD)
