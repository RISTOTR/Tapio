"""Provider-neutral, bounded input/output contracts. No ORM or private raw-source fields."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.app.domain.enums import (
    BusinessContext,
    DocumentType,
    TransactionCategory,
    TransactionDirection,
)
from data_pipeline.energy_cost.scenarios import ElectricityScenario
from data_pipeline.energy_cost.types import ReviewedSource


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class DateFilter(Schema):
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("invalid_date_range")
        return self


class Period(Schema):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def dates(self):
        if not 0 <= (self.date_to - self.date_from).days <= 731:
            raise ValueError("period_must_be_within_two_years")
        return self


class TransactionQuery(DateFilter):
    category: TransactionCategory | None = None
    business_context: BusinessContext | None = None
    counterparty: str | None = Field(default=None, min_length=2, max_length=100)
    direction: TransactionDirection | None = None


class TransactionSummary(Schema):
    id: UUID
    booking_date: date
    amount: Decimal
    currency: str
    direction: TransactionDirection
    counterparty: str | None
    category: str | None
    business_context: str | None
    label_authority: Literal["HUMAN_REVIEWED", "UNREVIEWED"]


class Page[T](Schema):
    items: list[T] = Field(max_length=50)
    truncated: bool = False


class EnergyQuery(Period):
    metric: Literal["consumption_kwh", "solar_export_kwh"]


class EnergySummary(Schema):
    date_from: date
    date_to: date
    metric: Literal["consumption_kwh", "solar_export_kwh"]
    total: Decimal
    hours: int
    coverage: Literal["COMPLETE"]


class CostQuery(Period):
    scope: Literal["all", "grid", "supplier"] = "all"


class ScenarioQuery(CostQuery):
    scenario: ElectricityScenario
    compare_fixed: ElectricityScenario | None = None
    # Source is a configured local dataset; no agent-supplied filesystem path.
    use_cached_spot: bool = False
    use_cached_export_spot: bool = False


class MonthlyCost(Schema):
    month: str
    consumption_kwh: Decimal
    solar_export_kwh: Decimal
    supplier_energy_cost: Decimal | None
    supplier_fixed_cost: Decimal | None
    grid_transfer_cost: Decimal | None
    electricity_tax_cost: Decimal | None
    grid_fixed_cost: Decimal | None
    solar_export_credit: Decimal | None
    scope_total: Decimal | None
    net_total_cost: Decimal | None
    known_component_subtotal: Decimal
    complete_month: bool


class PriceProvenance(Schema):
    source_document_id: str | None
    provider: str
    product: str
    source_version: str
    effective_from: date
    effective_to: date | None
    component: str
    source_kind: str | None = None
    reviewed_source: ReviewedSource | None = None


class CostSummary(Schema):
    mode: Literal["ACTUAL_RECONSTRUCTION", "SCENARIO"]
    scope: str
    start: date
    end: date
    warnings: list[str]
    total_definition: str
    monthly: list[MonthlyCost] = Field(max_length=25)
    provenance: list[PriceProvenance]


class ScenarioSummary(Schema):
    mode: Literal["SCENARIO", "SCENARIO_COMPARISON"]
    result: CostSummary
    fixed: CostSummary | None = None
    fixed_minus_spot_eur: Decimal | None = None
    difference_percent_of_fixed: Decimal | None = None
    break_even_fixed_price_cents_per_kwh: Decimal | None = None
    winner: Literal["fixed", "spot", "tie"] | None = None
    assumptions: ElectricityScenario


class DocumentQuery(DateFilter):
    document_type: DocumentType | None = None
    vendor: str | None = Field(default=None, min_length=2, max_length=100)


class DocumentID(Schema):
    document_id: UUID


class DocumentSummary(Schema):
    id: UUID
    document_type: DocumentType
    document_date: date | None
    vendor: str | None
    kind: str | None
    parser_version: str | None
    sha256: str


class InvoiceID(Schema):
    invoice_id: UUID


class InvoiceQuery(DateFilter):
    vendor: str | None = Field(default=None, min_length=2, max_length=100)
    invoice_number: str | None = Field(default=None, min_length=1, max_length=100)
    status: (
        Literal["PAID", "AMBIGUOUS", "UNMATCHED", "PARTIALLY_PAID", "REFUNDED", "OVERPAID"] | None
    ) = None


class ReconciliationSummary(Schema):
    invoice_id: UUID
    state: str
    confirmed_paid_eur: Decimal
    confirmed_refund_eur: Decimal
    confirmed_net_eur: Decimal
    human_review_required: bool


class InvoiceSummary(Schema):
    id: UUID
    source_document_id: UUID
    parser_version: str | None
    vendor: str
    invoice_number: str | None
    invoice_date: date | None
    total_eur: Decimal | None
    subtotal_eur: Decimal | None
    vat_eur: Decimal | None
    reconciliation: ReconciliationSummary


class ForestryQuery(DateFilter):
    buyer: str | None = Field(default=None, min_length=2, max_length=100)


class ForestryID(Schema):
    sale_id: UUID


class ForestrySummary(Schema):
    id: UUID
    source_document_id: UUID
    parser_version: str | None
    buyer: str
    sale_date: date | None
    actual_volume_m3: Decimal | None
    actual_value_eur: Decimal | None
    estimated_volume_m3: Decimal | None
    estimated_value_eur: Decimal | None
