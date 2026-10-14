"""Retrospective pricing of an unchanged measured profile."""

from typing import Literal

from pydantic import model_validator

from .engine import calculate
from .types import ZERO, CostError, Exact, Frozen


class ElectricityScenario(Frozen):
    name: str
    import_pricing_type: Literal["fixed", "spot"]
    fixed_import_price: Exact | None = None
    supplier_monthly_fee: Exact
    spot_markup_per_kwh: Exact = ZERO
    price_basis: Literal["NET", "GROSS"]
    vat_rate: Exact
    export_pricing_type: Literal["omit", "fixed", "spot"] = "omit"
    export_fixed_price: Exact | None = None
    export_margin: Exact | None = None
    export_price_basis: Literal["NET", "GROSS"] | None = None
    export_vat_rate: Exact | None = None

    @model_validator(mode="after")
    def valid(self):
        if not ZERO <= self.vat_rate <= 100 or self.supplier_monthly_fee < 0:
            raise ValueError("invalid_fee_or_vat")
        if (self.import_pricing_type == "fixed") != (self.fixed_import_price is not None):
            raise ValueError("fixed_price_required_only_for_fixed")
        if self.import_pricing_type == "fixed" and self.spot_markup_per_kwh:
            raise ValueError("fixed_price_includes_markup")
        if self.export_pricing_type != "omit":
            if (
                self.export_margin is None
                or self.export_price_basis is None
                or self.export_vat_rate is None
            ):
                raise ValueError("explicit_export_terms_required")
            if not ZERO <= self.export_vat_rate <= 100:
                raise ValueError("invalid_export_vat")
            if (self.export_pricing_type == "fixed") != (self.export_fixed_price is not None):
                raise ValueError("export_fixed_price_required_only_for_fixed")
        elif any(
            v is not None
            for v in (
                self.export_fixed_price,
                self.export_margin,
                self.export_price_basis,
                self.export_vat_rate,
            )
        ):
            raise ValueError("unused_export_parameters")
        return self


class SupplierScenario:
    def __init__(self, definition, import_spot=None, export_spot=None):
        self.definition = definition
        self.import_spot = import_spot
        self.export_spot = export_spot
        if definition.import_pricing_type == "spot" and import_spot is None:
            raise CostError("IMPORT_SPOT_SOURCE_REQUIRED")
        if definition.export_pricing_type == "spot" and export_spot is None:
            raise CostError("INDEPENDENT_EXPORT_SPOT_SOURCE_REQUIRED")

    def gross(self, value, export=False):
        d = self.definition
        basis, vat = (
            (d.export_price_basis, d.export_vat_rate) if export else (d.price_basis, d.vat_rate)
        )
        return value * (1 + vat / 100) if basis == "NET" else value

    @property
    def monthly_fee(self):
        return self.gross(self.definition.supplier_monthly_fee)

    def hour(self, reading):
        d = self.definition
        rate = (
            self.gross(d.fixed_import_price)
            if d.import_pricing_type == "fixed"
            else self.import_spot.gross(reading.timestamp) + self.gross(d.spot_markup_per_kwh)
        )
        if d.export_pricing_type == "omit":
            credit = value = margin = None if reading.solar_export_kwh else ZERO
        else:
            export_rate = (
                self.gross(d.export_fixed_price, True)
                if d.export_pricing_type == "fixed"
                else self.export_spot.gross(reading.timestamp)
            )
            value = reading.solar_export_kwh * export_rate
            margin = reading.solar_export_kwh * self.gross(d.export_margin, True)
            credit = value - margin
        return {
            "supplier_energy_cost": reading.consumption_kwh * rate,
            "raw_spot_energy_cost": reading.consumption_kwh
            * self.import_spot.gross(reading.timestamp)
            if d.import_pricing_type == "spot"
            else None,
            "retailer_markup_cost": reading.consumption_kwh * self.gross(d.spot_markup_per_kwh)
            if d.import_pricing_type == "spot"
            else None,
            "solar_export_credit": credit,
            "spot_export_value": value,
            "export_margin": margin,
        }

    def metadata(self):
        return {
            "source_kind": "USER_SCENARIO",
            **self.definition.model_dump(mode="json"),
            "import_spot": self.import_spot.provenance() if self.import_spot else None,
            "export_spot": self.export_spot.provenance() if self.export_spot else None,
        }


def compare(readings, tariffs, start, end, fixed, spot, scope="all"):
    if scope not in ("all", "supplier"):
        raise CostError("SUPPLIER_COMPARISON_SCOPE_REQUIRED")
    if (
        fixed.definition.import_pricing_type != "fixed"
        or spot.definition.import_pricing_type != "spot"
    ):
        raise CostError("FIXED_AND_SPOT_REQUIRED")
    export_keys = (
        "export_pricing_type",
        "export_fixed_price",
        "export_margin",
        "export_price_basis",
        "export_vat_rate",
    )
    if (
        any(getattr(fixed.definition, k) != getattr(spot.definition, k) for k in export_keys)
        or fixed.metadata()["export_spot"] != spot.metadata()["export_spot"]
    ):
        raise CostError("IDENTICAL_EXPORT_ASSUMPTIONS_REQUIRED")
    results = [
        calculate(readings, tariffs, start, end, scope=scope, supplier=s) for s in (fixed, spot)
    ]
    if any(
        not m["complete_month"] or m["scope_total"] is None for r in results for m in r["monthly"]
    ):
        raise CostError("COMPLETE_MONTHS_AND_EXPORT_TERMS_REQUIRED")
    totals = [sum((m["scope_total"] for m in r["monthly"]), ZERO) for r in results]
    quantity = sum((r.consumption_kwh for r in readings), ZERO)
    # Analytical equality before invoice rounding; differing supplier fixed fees included.
    variable = sum((spot.hour(r)["supplier_energy_cost"] for r in readings), ZERO)
    fee_delta = len(results[0]["monthly"]) * (spot.monthly_fee - fixed.monthly_fee)
    difference = totals[0] - totals[1]
    return {
        "mode": "SCENARIO_COMPARISON",
        "scope": scope,
        "fixed": results[0],
        "spot": results[1],
        "fixed_minus_spot_eur": difference,
        "difference_percent_of_fixed": difference / abs(totals[0]) * 100 if totals[0] else None,
        "winner": "spot" if difference > 0 else "fixed" if difference < 0 else "tie",
        "break_even_gross_eur_per_kwh": (variable + fee_delta) / quantity if quantity else None,
        "break_even_fixed_price_cents_per_kwh": 100 * (variable + fee_delta) / quantity
        if quantity
        else None,
        "break_even_policy": (
            "Analytical, before component cent rounding; identical grid and export; "
            "supplier fee difference included"
        ),
    }


def supplier_break_even(readings, start, end, spot_supplier, fixed_monthly_fee):
    """Import-only threshold; unchanged grid/export cancel, neither is assumed zero."""
    from calendar import monthrange

    from .types import HELSINKI, D, validate_readings

    if (
        not isinstance(fixed_monthly_fee, D)
        or not fixed_monthly_fee.is_finite()
        or fixed_monthly_fee < 0
    ):
        raise CostError("EXACT_GROSS_FIXED_MONTHLY_FEE_REQUIRED")
    if spot_supplier.definition.import_pricing_type != "spot":
        raise CostError("SPOT_SCENARIO_REQUIRED")
    rows = validate_readings(readings, start, end)
    if start.day != 1 or end.day != monthrange(end.year, end.month)[1]:
        raise CostError("COMPLETE_CALENDAR_MONTHS_REQUIRED")
    spot_supplier.import_spot.require(rows)
    months = len({r.timestamp.astimezone(HELSINKI).strftime("%Y-%m") for r in rows})
    quantity = sum((r.consumption_kwh for r in rows), ZERO)
    raw = sum(
        (r.consumption_kwh * spot_supplier.import_spot.gross(r.timestamp) for r in rows), ZERO
    )
    markup = quantity * spot_supplier.gross(spot_supplier.definition.spot_markup_per_kwh)
    spot_fees = months * spot_supplier.monthly_fee
    fixed_fees = months * fixed_monthly_fee
    price = (raw + markup + spot_fees - fixed_fees) / quantity if quantity else None
    return {
        "mode": "SCENARIO_BREAK_EVEN",
        "scope": "SUPPLIER_IMPORT_ONLY",
        "start": start,
        "end": end,
        "consumption_kwh": quantity,
        "months": months,
        "raw_spot_energy_cost_unrounded": raw,
        "retailer_markup_cost_unrounded": markup,
        "spot_supplier_fees": spot_fees,
        "fixed_supplier_fees": fixed_fees,
        "break_even_gross_eur_per_kwh": price,
        "break_even_fixed_price_cents_per_kwh": price * 100 if price is not None else None,
        "assumption": (
            "Identical grid, tax, other charges and export settlement cancel; "
            "their amounts are not assumed zero. Fixed monthly fee is a user scenario, "
            "not historical contract evidence."
        ),
        "scenario": spot_supplier.metadata(),
    }
