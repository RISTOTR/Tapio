"""Actual source-backed fixed costs versus unchanged-load spot, excluding export."""

from .engine import calculate
from .spot import weighted_prices
from .types import ZERO, CostError, D


def compare_actual_import(readings, tariffs, start, end, spot_supplier, scope="supplier"):
    if scope not in ("supplier", "all") or spot_supplier.definition.import_pricing_type != "spot":
        raise CostError("IMPORT_COMPARISON_REQUIRES_SPOT_AND_SUPPLIER_OR_ALL")
    if spot_supplier.definition.export_pricing_type != "omit":
        raise CostError("IMPORT_COMPARISON_EXCLUDES_EXPORT")
    spot_supplier.import_spot.require(readings)
    fixed = calculate(readings, tariffs, start, end, scope=scope, export_policy="exclude")
    spot = calculate(
        readings, tariffs, start, end, scope=scope, supplier=spot_supplier, export_policy="exclude"
    )
    if any(
        not m["complete_month"] or m["scope_total"] is None
        for result in (fixed, spot)
        for m in result["monthly"]
    ):
        raise CostError("COMPLETE_MONTHS_REQUIRED_FOR_COMPARISON")
    fields = (
        "supplier_energy_cost",
        "supplier_fixed_cost",
        "raw_spot_energy_cost",
        "retailer_markup_cost",
        "grid_transfer_cost",
        "electricity_tax_cost",
        "grid_fixed_cost",
        "consumption_kwh",
        "scope_total",
    )

    def totals(result):
        return {
            f: sum((m[f] for m in result["monthly"]), ZERO)
            if all(m[f] is not None for m in result["monthly"])
            else None
            for f in fields
        }

    a, b = totals(fixed), totals(spot)
    assert a["consumption_kwh"] == b["consumption_kwh"]
    difference = a["scope_total"] - b["scope_total"]
    variable = sum((spot_supplier.hour(r)["supplier_energy_cost"] for r in readings), ZERO)
    quantity = a["consumption_kwh"]
    break_even = (
        (variable + b["supplier_fixed_cost"] - a["supplier_fixed_cost"]) / quantity
        if quantity
        else None
    )
    stats = weighted_prices(readings, spot_supplier.import_spot)
    gross = stats["gross_retail_basis"]
    return {
        "mode": "ACTUAL_FIXED_VS_SPOT_SCENARIO",
        "scope": "SUPPLIER_IMPORT_ONLY" if scope == "supplier" else "HOUSEHOLD_IMPORT_SIDE",
        "start": start,
        "end": end,
        "export_compensation": "EXCLUDED_UNKNOWN_NOT_ZERO",
        "net_household_total": None,
        "fixed": {
            "mode": fixed["mode"],
            "totals": a,
            "monthly": fixed["monthly"],
            "provenance": fixed["provenance"],
            "warnings": fixed["warnings"],
        },
        "spot": {
            "mode": spot["mode"],
            "totals": b,
            "monthly": spot["monthly"],
            "scenario": spot["scenario"],
            "provenance": spot["provenance"],
        },
        "fixed_minus_spot_eur": difference,
        "difference_percent_of_fixed": difference / abs(a["scope_total"]) * D(100)
        if a["scope_total"]
        else None,
        "winner": "spot" if difference > 0 else "fixed" if difference < 0 else "tie",
        "break_even_fixed_price_cents_per_kwh": break_even * D(100)
        if break_even is not None
        else None,
        "break_even_policy": (
            "Analytical before component cent rounding; actual fixed supplier fees included; "
            "unchanged grid cancels"
        ),
        "simple_spot_average_cents_per_kwh": gross["simple_average"] * D(100),
        "consumption_weighted_spot_cents_per_kwh": gross["consumption_weighted"] * D(100)
        if quantity
        else None,
        "load_timing_effect_cents_per_kwh": gross["load_timing_effect"] * D(100)
        if quantity
        else None,
        "spot_price_statistics": stats,
        "consumption_policy": "IDENTICAL_MEASURED_HOURLY_CONSUMPTION_NO_SHIFTING",
    }
