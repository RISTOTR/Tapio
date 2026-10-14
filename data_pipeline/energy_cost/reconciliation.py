"""Independent measured-vs-billed component comparison. Never inserts corrections."""

from .engine import calculate, money
from .types import ZERO, CostError, D


def reconcile_invoice(readings, tariffs, metadata, start, end):
    bill = metadata["bill"]
    kind = metadata["kind"]
    scope = "grid" if kind == "GRID_INVOICE" else "supplier"
    result = {
        "kind": kind,
        "period_start": start,
        "period_end": end,
        "mode": "ACTUAL_RECONSTRUCTION",
        "categories": [],
    }
    try:
        calculated = calculate(readings, tariffs, start, end, scope)
    except CostError as exc:
        result.update(status="INCOMPLETE", error_code=str(exc))
        result["categories"] = [
            "TARIFF_COVERAGE_GAP"
            if str(exc) == "MISSING_PRICE_COVERAGE"
            else "MEASUREMENT_DIFFERENCE"
        ]
        return result
    if len(calculated["monthly"]) != 1 or not calculated["monthly"][0]["complete_month"]:
        return {
            **result,
            "status": "INCOMPLETE",
            "categories": ["UNSUPPORTED_COMPONENT"],
            "error_code": "FULL_MONTH_INVOICE_REQUIRED",
        }
    month = calculated["monthly"][0]
    consumption = sum(
        (D(e["consumption_kwh"]) for e in bill["energy"] if e["consumption_kwh"] is not None), ZERO
    )
    export = sum(
        (D(e["solar_export_kwh"]) for e in bill["energy"] if e["solar_export_kwh"] is not None),
        ZERO,
    )
    expected = {"consumption_kwh": consumption, "solar_export_kwh": export}
    labels = (
        {
            "Perusmaksu": "grid_fixed_cost",
            "Talviarkipäiväsiirto": "winter",
            "Muun ajan siirto": "other",
            "Tuotannon siirto": "production",
        }
        if scope == "grid"
        else {
            "Perusmaksu": "supplier_fixed_cost",
            "Energia": "supplier_energy_cost",
            "Marginaali": "margin",
            "Spot-energia": "spot",
        }
    )
    sums = {}
    unsupported = []
    for line in bill["lines"]:
        label = line["description"]
        key = "electricity_tax_cost" if label.startswith("Sähkövero ") else labels.get(label)
        if key is None:
            unsupported.append(label)
            continue
        sums[key] = sums.get(key, ZERO) + D(line["gross_amount_eur"])
        if key in ("winter", "other"):
            expected["grid_winter_day_kwh" if key == "winter" else "grid_other_time_kwh"] = D(
                line["quantity"]
            )
    if scope == "grid":
        expected.update(
            grid_fixed_cost=sums.get("grid_fixed_cost", ZERO),
            grid_transfer_cost=sums.get("winter", ZERO) + sums.get("other", ZERO),
            electricity_tax_cost=sums.get("electricity_tax_cost", ZERO),
        )
        if sums.get("production", ZERO):
            unsupported.append("NONZERO_PRODUCTION_NETWORK_FEE")
    else:
        expected.update(
            supplier_fixed_cost=sums.get("supplier_fixed_cost", ZERO),
            supplier_energy_cost=sums.get("supplier_energy_cost", ZERO),
            solar_export_credit=-(sums.get("spot", ZERO) + sums.get("margin", ZERO)),
        )
    comparisons = {}
    for key, billed in expected.items():
        actual = month[key]
        delta = actual - billed
        comparisons[key] = {
            "calculated": actual,
            "billed": billed,
            "signed_difference": delta,
            "absolute_difference": abs(delta),
            "percentage_difference": abs(delta) / abs(billed) * 100 if billed else None,
        }
        if delta:
            if not key.endswith("_kwh") and abs(delta) <= D(".01"):
                calculated["warnings"].append(
                    "ONE_CENT_RESIDUAL_SOURCE_PRICE_PRECISION_NOT_VERIFIED"
                )
            if key.endswith("_kwh"):
                category = (
                    "ROUNDING_DIFFERENCE" if money(actual) == billed else "MEASUREMENT_DIFFERENCE"
                )
            else:
                category = "ROUNDING_DIFFERENCE" if abs(delta) <= D(".01") else "CALCULATION_ERROR"
            result["categories"].append(category)
    actual = month["scope_total"]
    billed = D(bill["total_eur"])
    if actual is None:
        unsupported.append("MISSING_FIXED_FEES_OR_EXPORT")
    total_delta = actual - billed if actual is not None else None
    if unsupported:
        result["categories"].append("UNSUPPORTED_COMPONENT")
    if total_delta and abs(total_delta) > D(".01"):
        result["categories"].append("CALCULATION_ERROR")
    result.update(
        status="VALIDATED"
        if not unsupported
        and not any(
            c in ("CALCULATION_ERROR", "MEASUREMENT_DIFFERENCE") for c in result["categories"]
        )
        else "DIFFERENCES",
        comparisons=comparisons,
        calculated_total=actual,
        invoice_total=billed,
        absolute_eur_difference=abs(total_delta) if total_delta is not None else None,
        percentage_difference=abs(total_delta) / abs(billed) * 100
        if total_delta is not None and billed
        else None,
        warnings=calculated["warnings"],
        unsupported_component_count=len(unsupported),
    )
    result["categories"] = sorted(set(result["categories"]))
    return result
