"""Bounded finance aggregates, separated from invoice and forestry-sale values."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from apps.api.app.domain.enums import BusinessContext, TransactionCategory
from tapio.tools.schemas import Period, Schema


class FinanceQuery(Period):
    business_context: BusinessContext | None = Field(
        default=None,
        description=(
            "Omit or null for ALL contexts grouped separately. mixed means only literal "
            "MIXED labels, never multiple contexts. For property AND forestry overview use null."
        ),
    )
    categories: list[TransactionCategory] | None = Field(
        default=None,
        max_length=20,
        description=(
            "Omit or null for ALL categories grouped separately; "
            "never guess a category list for a broad overview."
        ),
    )


class CashGroup(Schema):
    business_context: str
    category: str
    currency: str
    debit_total: Decimal
    credit_total: Decimal
    net_cash_flow: Decimal
    transaction_count: int
    confirmed_count: int
    unresolved_count: int
    transaction_ids: list[UUID]
    human_review_ids: list[UUID]
    evidence: list[str]


class FinanceSummary(Schema):
    view: Literal["BANK_CASH_FLOW"] = "BANK_CASH_FLOW"
    date_from: date
    date_to: date
    context_filter: str | None
    categories_filter: list[str] | None
    groups: list[CashGroup]
    context_totals: list[CashGroup]
    transaction_count: int
    confirmed_count: int
    unresolved_count: int
    observed_first_date: date | None
    observed_last_date: date | None
    coverage: Literal["IMPORTED_ROWS_ONLY_NOT_COMPLETE_BANK_STATEMENT"]
    excluded_unresolved_context_count: int
    tax_treatment: Literal["NOT_DETERMINED"] = "NOT_DETERMINED"
    limitations: list[str]


class SavedEnergyQuery(Schema):
    result: Literal["actual_export_net_april_august_2026"] = "actual_export_net_april_august_2026"


class SavedEnergyMonth(Schema):
    year_month: str
    import_side_fixed_total: Decimal
    import_side_spot_total: Decimal
    actual_export_credit: Decimal
    net_fixed_household_total: Decimal
    net_spot_household_total: Decimal
    fixed_minus_spot_eur: Decimal
    difference_percent_of_net_fixed: Decimal | None
    winner: Literal["fixed", "spot", "tie"]


class SavedEnergySummary(Schema):
    evidence: Literal["DETERMINISTIC_ENERGY_RESULT"]
    label: Literal["ACTUAL_EXPORT_CREDIT_NET_COMPARISON"]
    months: list[str]
    monthly: list[SavedEnergyMonth]
    aggregate: SavedEnergyMonth
    source_sha256: str
    source_import_sha256: str
    source_review_sha256: str
    coverage: str
    limitations: list[str]
