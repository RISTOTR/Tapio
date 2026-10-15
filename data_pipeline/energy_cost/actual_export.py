"""Apply accepted monthly billed credits to saved import totals; no tariff or database I/O."""

from copy import deepcopy
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .types import ZERO, CostError, D, Exact, Frozen

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BilledCreditSource(Frozen):
    invoice_reference: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    attachment_filename: str = Field(min_length=1)
    pdf_sha256: Digest
    review_sha256: Digest
    acceptance_sha256: Digest
    page: int = Field(ge=1)
    document_id: None = None
    extraction_status: Literal["REVIEWED_EXTRACTED_LINES_NOT_IMPORTED"]


class ActualExportCredit(Frozen):
    year_month: str
    export_kwh: Annotated[Exact, Field(ge=0)]
    actual_credit_eur: Exact
    billed_margin_snt_per_kwh: Annotated[Exact, Field(ge=0)]
    evidence_status: Literal["ACTUAL_BILLED"]
    continuous_tariff_inference: Literal[False] = False
    source: BilledCreditSource

    @field_validator("year_month")
    @classmethod
    def calendar_month(cls, value):
        if len(value) != 7 or date.fromisoformat(value + "-01").strftime("%Y-%m") != value:
            raise ValueError("invalid_calendar_month")
        return value

    @field_validator("actual_credit_eur")
    @classmethod
    def billed_cents(cls, value):
        if value != value.quantize(D(".01")):
            raise ValueError("billed_credit_requires_cents")
        return value


class AcceptedExportCredits(Frozen):
    version: Literal["actual-export-credits-1"]
    customer_vat_liability: Literal["NON_VAT_LIABLE"]
    applicability_source: Literal["HUMAN_CONFIRMED_PROPERTY_CONTEXT"]
    scope: Literal["PROPERTY_EXPORT_ONLY"]
    credits: tuple[ActualExportCredit, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_months(self):
        months = [c.year_month for c in self.credits]
        if len(months) != len(set(months)):
            raise ValueError("duplicate_actual_export_month")
        return self


def exact(value):
    if isinstance(value, (float, bool)) or value is None:
        raise CostError("EXACT_SAVED_IMPORT_AMOUNT_REQUIRED")
    result = D(value)
    if not result.is_finite():
        raise CostError("EXACT_SAVED_IMPORT_AMOUNT_REQUIRED")
    return result


def comparison(fixed, spot):
    difference = fixed - spot
    return {
        "fixed_minus_spot_eur": difference,
        "difference_percent_of_net_fixed": difference / abs(fixed) * 100 if fixed else None,
        "winner": "spot" if difference > 0 else "fixed" if difference < 0 else "tie",
    }


def apply_actual_export_credits(saved_import, accepted):
    """Join exact accepted months only. Never call the hourly engine or infer missing credits."""
    if saved_import["scope"] != "HOUSEHOLD_IMPORT_SIDE":
        raise CostError("HOUSEHOLD_IMPORT_SIDE_REQUIRED")
    indexed = {}
    for side in ("fixed", "spot"):
        rows = saved_import[side]["monthly"]
        indexed[side] = {r["month"]: r for r in rows}
        if len(indexed[side]) != len(rows):
            raise CostError("DUPLICATE_IMPORT_MONTH")
    monthly = []
    component_names = (
        "supplier_energy_cost",
        "supplier_fixed_cost",
        "grid_transfer_cost",
        "electricity_tax_cost",
        "grid_fixed_cost",
    )
    for credit in sorted(accepted.credits, key=lambda c: c.year_month):
        month = credit.year_month
        if any(month not in indexed[side] for side in indexed):
            raise CostError("ACCEPTED_CREDIT_MISSING_IMPORT_MONTH")
        a, b = (indexed[side][month] for side in ("fixed", "spot"))
        for row in (a, b):
            if not row["complete_month"] or row.get("solar_export_credit") is not None:
                raise CostError("COMPLETE_IMPORT_ONLY_MONTH_REQUIRED")
            if row.get("net_total_cost") is not None:
                raise CostError("ALREADY_NETTED_IMPORT_NOT_ALLOWED")
            if sum((exact(row[k]) for k in component_names), ZERO) != exact(row["scope_total"]):
                raise CostError("SAVED_IMPORT_COMPONENT_TOTAL_MISMATCH")
        if any(exact(a[k]) != exact(b[k]) for k in component_names[2:] + ("consumption_kwh",)):
            raise CostError("IMPORT_SCENARIOS_REQUIRE_IDENTICAL_GRID_AND_LOAD")
        if exact(b["raw_spot_energy_cost"]) + exact(b["retailer_markup_cost"]) != exact(
            b["supplier_energy_cost"]
        ):
            raise CostError("SAVED_SPOT_COMPONENT_TOTAL_MISMATCH")
        fixed, spot = exact(a["scope_total"]), exact(b["scope_total"])
        net_fixed, net_spot = fixed - credit.actual_credit_eur, spot - credit.actual_credit_eur
        monthly.append(
            {
                "year_month": month,
                "import_side_fixed_total": fixed,
                "import_side_spot_total": spot,
                "actual_export_credit": credit.actual_credit_eur,
                "net_fixed_household_total": net_fixed,
                "net_spot_household_total": net_spot,
                **comparison(net_fixed, net_spot),
                "winner_unchanged": comparison(fixed, spot)["winner"]
                == comparison(net_fixed, net_spot)["winner"],
                "accepted_export_evidence": credit.model_dump(mode="python"),
                "saved_import_components": {"fixed": deepcopy(a), "spot": deepcopy(b)},
            }
        )
    fields = (
        "import_side_fixed_total",
        "import_side_spot_total",
        "actual_export_credit",
        "net_fixed_household_total",
        "net_spot_household_total",
    )
    aggregate = {key: sum((r[key] for r in monthly), ZERO) for key in fields}
    aggregate.update(
        comparison(aggregate["net_fixed_household_total"], aggregate["net_spot_household_total"])
    )
    aggregate["winner_unchanged"] = (
        aggregate["winner"]
        == comparison(aggregate["import_side_fixed_total"], aggregate["import_side_spot_total"])[
            "winner"
        ]
    )
    return {
        "label": "ACTUAL_EXPORT_CREDIT_NET_COMPARISON",
        "months": [r["year_month"] for r in monthly],
        "monthly": monthly,
        "aggregate": aggregate,
        "excluded_import_months": sorted(
            set(indexed["fixed"]) - {r["year_month"] for r in monthly}
        ),
        "export_basis": "SAME_ACTUAL_BILLED_CREDIT_IN_BOTH_IMPORT_SCENARIOS",
        "continuous_export_tariff": None,
        "negative_price_policy": "UNRESOLVED_NOT_REQUIRED_TO_REUSE_BILLED_CREDIT",
        "percentage_basis": "(net fixed - net spot) / abs(net fixed) * 100; null if fixed is zero",
    }
