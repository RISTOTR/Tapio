"""Pure Decimal cost calculation. Monthly component rounding, no hourly cent rounding."""

from calendar import monthrange
from collections import defaultdict
from decimal import ROUND_HALF_UP, localcontext

from .types import HELSINKI, ZERO, Component, CostError, D, Window, validate_readings

COST_FIELDS = (
    "supplier_energy_cost",
    "supplier_fixed_cost",
    "grid_transfer_cost",
    "electricity_tax_cost",
    "grid_fixed_cost",
    "other_billed_cost",
    "solar_export_credit",
)
VARIABLE_FIELDS = (
    "supplier_energy_cost",
    "grid_transfer_cost",
    "electricity_tax_cost",
    "solar_export_credit",
)
QUANTITIES = ("consumption_kwh", "solar_export_kwh", "grid_winter_day_kwh", "grid_other_time_kwh")


def money(value):
    return value.quantize(D(".01"), rounding=ROUND_HALF_UP)


def ratio(value, quantity):
    return value / quantity if value is not None and quantity else None


def month_key(timestamp):
    return timestamp.astimezone(HELSINKI).strftime("%Y-%m")


def provenance(tariff):
    return tariff.model_dump(mode="json")


def calculate(readings, tariffs, start, end, scope="all", supplier=None, export_policy="include"):
    """supplier is an optional pure scenario pricing adapter, after 04A validation."""
    if scope not in ("all", "grid", "supplier"):
        raise CostError("INVALID_COST_SCOPE")
    if export_policy not in ("include", "exclude"):
        raise CostError("INVALID_EXPORT_POLICY")
    readings = validate_readings(readings, start, end)
    grid = scope in ("all", "grid")
    energy = scope in ("all", "supplier")
    hourly = []
    used = {}
    warnings = set()
    with localcontext() as ctx:
        ctx.prec = 34
        for r in readings:
            local = r.timestamp.astimezone(HELSINKI)
            day = local.date()
            row = {
                "timestamp_utc": r.timestamp,
                "consumption_kwh": r.consumption_kwh,
                "solar_export_kwh": r.solar_export_kwh,
                "grid_winter_day_kwh": ZERO if grid else None,
                "grid_other_time_kwh": ZERO if grid else None,
                "supplier_energy_cost": None,
                "grid_transfer_cost": None,
                "electricity_tax_cost": None,
                "solar_export_credit": None,
                "spot_export_value": None,
                "export_margin": None,
                "raw_spot_energy_cost": None,
                "retailer_markup_cost": None,
            }
            if grid:
                tariff, window = tariffs.grid(r.timestamp)
                tax = tariffs.get(Component.ELECTRICITY_TAX, day)
                row["grid_window"] = window.value
                row[
                    "grid_winter_day_kwh" if window == Window.WINTER_DAY else "grid_other_time_kwh"
                ] = r.consumption_kwh
                row["grid_transfer_cost"] = r.consumption_kwh * tariff.gross_rate
                row["electricity_tax_cost"] = r.consumption_kwh * tax.gross_rate
                for t in (tariff, tax):
                    used[t.model_dump_json()] = provenance(t)
            if energy:
                if supplier is not None:
                    row.update(supplier.hour(r))
                else:
                    tariff = tariffs.get(Component.ENERGY_IMPORT, day)
                    row["supplier_energy_cost"] = r.consumption_kwh * tariff.gross_rate
                    used[tariff.model_dump_json()] = provenance(tariff)
                    try:
                        if export_policy == "exclude":
                            raise CostError("EXPORT_EXCLUDED")
                        export = tariffs.get(Component.SOLAR_EXPORT_CREDIT, day)
                        row["solar_export_credit"] = r.solar_export_kwh * export.gross_rate
                        export_factor = (
                            1 + export.vat_rate / 100 if export.price_basis == "NET" else 1
                        )
                        row["spot_export_value"] = (
                            r.solar_export_kwh * export.export_spot_rate * export_factor
                        )
                        row["export_margin"] = (
                            r.solar_export_kwh * export.export_margin * export_factor
                        )
                        used[export.model_dump_json()] = provenance(export)
                        if r.solar_export_kwh:
                            warnings.add("BILLED_EXPORT_AVERAGE_NOT_HOURLY_SPOT")
                    except CostError:
                        if export_policy == "exclude":
                            pass
                        elif r.solar_export_kwh:
                            raise
                        else:
                            row["solar_export_credit"] = ZERO
                            row["spot_export_value"] = row["export_margin"] = ZERO
                if export_policy == "exclude":
                    row["solar_export_credit"] = None
                    row["spot_export_value"] = row["export_margin"] = None
                    warnings.add("EXPORT_COMPENSATION_EXCLUDED_NOT_ASSUMED_ZERO")
            hourly.append(row)
        by_month = defaultdict(list)
        for row in hourly:
            by_month[month_key(row["timestamp_utc"])].append(row)
        monthly = []
        for month, rows in sorted(by_month.items()):
            first = rows[0]["timestamp_utc"].astimezone(HELSINKI).date()
            last = rows[-1]["timestamp_utc"].astimezone(HELSINKI).date()
            full = first.day == 1 and last.day == monthrange(last.year, last.month)[1]
            result = {
                "month": month,
                "hours": len(rows),
                "fixed_fee_policy": "FULL_CALENDAR_MONTH_ONLY",
                "complete_month": full,
                **{
                    field: sum((r[field] for r in rows), ZERO)
                    if all(r[field] is not None for r in rows)
                    else None
                    for field in QUANTITIES
                },
            }
            for field in VARIABLE_FIELDS + (
                "spot_export_value",
                "export_margin",
                "raw_spot_energy_cost",
                "retailer_markup_cost",
            ):
                amounts = [r[field] for r in rows]
                result[field] = (
                    money(sum(amounts, ZERO)) if all(v is not None for v in amounts) else None
                )
            if result["raw_spot_energy_cost"] is not None:
                result["supplier_energy_cost"] = (
                    result["raw_spot_energy_cost"] + result["retailer_markup_cost"]
                )
            if result["spot_export_value"] is not None and result["export_margin"] is not None:
                result["solar_export_credit"] = (
                    result["spot_export_value"] - result["export_margin"]
                )
            if supplier is not None and supplier.definition.export_pricing_type == "omit":
                warnings.add("EXPORT_TERMS_OMITTED")
            if grid:
                result["grid_transfer_cost"] = sum(
                    (
                        money(
                            sum(
                                (r["grid_transfer_cost"] for r in rows if r["grid_window"] == w),
                                ZERO,
                            )
                        )
                        for w in (Window.WINTER_DAY.value, Window.OTHER_TIME.value)
                    ),
                    ZERO,
                )
            for comp, field, enabled in [
                (Component.GRID_FIXED_FEE, "grid_fixed_cost", grid),
                (Component.SUPPLIER_FIXED_FEE, "supplier_fixed_cost", energy),
            ]:
                result[field] = None
                if enabled:
                    if not full:
                        warnings.add("PARTIAL_MONTH_FIXED_FEE_NOT_ALLOCATED")
                        continue
                    if supplier is not None and comp == Component.SUPPLIER_FIXED_FEE:
                        result[field] = money(supplier.monthly_fee)
                    else:
                        definitions = {
                            tariffs.get(comp, r["timestamp_utc"].astimezone(HELSINKI).date())
                            for r in rows
                        }
                        if len(definitions) != 1:
                            raise CostError("MID_MONTH_FIXED_FEE_CHANGE_REQUIRES_BILLING_POLICY")
                        t = definitions.pop()
                        used[t.model_dump_json()] = provenance(t)
                        result[field] = money(t.gross_rate)
            # No unsupported charge is assumed absent from full actual electricity costs.
            # This subtotal covers the selected modeled components only.
            result["other_billed_cost"] = None
            required = (
                ["grid_transfer_cost", "electricity_tax_cost", "grid_fixed_cost"] if grid else []
            ) + (
                ["supplier_energy_cost", "supplier_fixed_cost"]
                + (["solar_export_credit"] if export_policy == "include" else [])
                if energy
                else []
            )
            known = [
                result[f] * (-1 if f == "solar_export_credit" else 1)
                for f in required
                if result[f] is not None
            ]
            result["known_component_subtotal"] = sum(known, ZERO)
            result["scope_total"] = (
                sum(known, ZERO) if all(result[f] is not None for f in required) else None
            )
            result["net_total_cost"] = (
                result["scope_total"] if scope == "all" and export_policy == "include" else None
            )
            result["effective_cost_per_consumed_kwh"] = ratio(
                result["net_total_cost"], result["consumption_kwh"]
            )
            result["average_credit_per_exported_kwh"] = ratio(
                result["solar_export_credit"], result["solar_export_kwh"]
            )
            monthly.append(result)
        mode = "SCENARIO" if supplier else "ACTUAL_RECONSTRUCTION"
        return {
            "mode": mode,
            "scope": scope,
            "total_definition": (
                "IMPORT_SIDE_EXCLUDING_EXPORT_COMPENSATION_AND_UNSUPPORTED_OTHER_CHARGES"
                if export_policy == "exclude"
                else "MODELED_COMPONENTS_EXCLUDING_UNSUPPORTED_OTHER_CHARGES"
            ),
            "export_policy": export_policy,
            "start": start,
            "end": end,
            "warnings": sorted(warnings),
            "provenance": list(used.values()),
            "scenario": supplier.metadata() if supplier else None,
            "hourly": hourly,
            "daily": aggregate_variable(hourly, "day"),
            "monthly": monthly,
            "yearly": aggregate_months(monthly),
        }


def aggregate_variable(rows, period):
    groups = defaultdict(list)
    for r in rows:
        key = (
            r["timestamp_utc"]
            .astimezone(HELSINKI)
            .strftime("%Y-%m-%d" if period == "day" else "%Y")
        )
        groups[key].append(r)
    output = []
    for key, items in sorted(groups.items()):
        result = {"period": key, "fixed_fees": "NOT_DISTRIBUTED_TO_HOURS_OR_DAYS"}
        for field in QUANTITIES + VARIABLE_FIELDS:
            values = [r[field] for r in items]
            result[field] = sum(values, ZERO) if all(v is not None for v in values) else None
        output.append(result)
    return output


def aggregate_months(months):
    groups = defaultdict(list)
    for r in months:
        groups[r["month"][:4]].append(r)
    result = []
    for year, items in sorted(groups.items()):
        record = {
            "year": year,
            "months_present": len(items),
            "full_year": len(items) == 12 and all(i["complete_month"] for i in items),
        }
        for field in (
            QUANTITIES
            + COST_FIELDS
            + (
                "raw_spot_energy_cost",
                "retailer_markup_cost",
                "spot_export_value",
                "export_margin",
                "net_total_cost",
                "scope_total",
                "known_component_subtotal",
            )
        ):
            values = [i[field] for i in items]
            record[field] = sum(values, ZERO) if all(v is not None for v in values) else None
        record["effective_cost_per_consumed_kwh"] = ratio(
            record["net_total_cost"], record["consumption_kwh"]
        )
        record["average_credit_per_exported_kwh"] = ratio(
            record["solar_export_credit"], record["solar_export_kwh"]
        )
        denominator = record["scope_total"]
        record["signed_component_percentages"] = {
            f: 100 * record[f] * (-1 if f == "solar_export_credit" else 1) / denominator
            if denominator and record[f] is not None
            else None
            for f in COST_FIELDS
        }
        result.append(record)
    return result
