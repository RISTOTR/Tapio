"""Audit expected UTC intervals and source-supported prices without filling gaps."""

from .types import HELSINKI, HOUR, Component, CostError, hours


def ranges(ticks):
    result = []
    for t in sorted(ticks):
        if result and result[-1]["end_exclusive"] == t:
            result[-1]["end_exclusive"] = t + HOUR
        else:
            result.append({"start": t, "end_exclusive": t + HOUR})
    return result


def audit(readings, tariffs, start, end, spot=None):
    expected = hours(start, end)
    present = {r.timestamp for r in readings}
    counts = {
        "expected_hours": len(expected),
        "reading_rows": len(readings),
        "duplicate_reading_intervals": len(readings) - len(present),
    }
    gaps = {}
    available = {}
    for name, component in [
        ("supplier_price", Component.ENERGY_IMPORT),
        ("grid_tariff", Component.GRID_TRANSFER),
        ("electricity_tax", Component.ELECTRICITY_TAX),
        ("grid_fixed_fee", Component.GRID_FIXED_FEE),
        ("supplier_fixed_fee", Component.SUPPLIER_FIXED_FEE),
        ("export_price", Component.SOLAR_EXPORT_CREDIT),
    ]:
        valid = []
        missing = []
        for t in expected:
            try:
                tariffs.grid(t) if component == Component.GRID_TRANSFER else tariffs.get(
                    component, t.astimezone(HELSINKI).date()
                )
                valid.append(t)
            except CostError:
                missing.append(t)
        counts[name + "_hours"] = len(valid)
        gaps[name] = ranges(missing)
        available[name] = ranges(valid)
    for name, valid in [
        ("energy_readings", present),
        ("solar_export_readings", present),
        ("spot_prices", set(spot.prices) if spot else set()),
    ]:
        valid = set(expected) & valid
        counts[name + "_hours"] = len(valid)
        gaps[name] = ranges(set(expected) - valid)
        available[name] = ranges(valid)
    return {
        "mode": "COVERAGE_AUDIT",
        **counts,
        "available_ranges_utc": available,
        "missing_ranges_utc": gaps,
        "overlapping_definitions": 0,
        "ambiguous_definitions": 0,
        "overlap_policy": "Tariffs constructor fails before audit if definitions overlap",
        "tariff_provenance": [t.model_dump(mode="json") for t in tariffs.values],
    }
