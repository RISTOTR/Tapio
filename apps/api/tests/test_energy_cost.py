"""Synthetic Phase 04 tests; no private identifiers or live network."""

import copy
import json
from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from data_pipeline.energy_cost.coverage import audit
from data_pipeline.energy_cost.engine import calculate, money
from data_pipeline.energy_cost.provider import SahkotinProvider, aggregate_hours, normalize_sahkotin
from data_pipeline.energy_cost.scenarios import ElectricityScenario, SupplierScenario, compare
from data_pipeline.energy_cost.sources import Tariffs, project_tariffs
from data_pipeline.energy_cost.spot import SpotMetadata, SpotPrices, read_spot, weighted_prices
from data_pipeline.energy_cost.types import (
    HELSINKI,
    Component,
    CostError,
    D,
    Reading,
    Season,
    Tariff,
    Window,
    classify_grid_tariff,
    hours,
    validate_readings,
)

START, END = date(2025, 1, 1), date(2025, 1, 31)
SEASON = Season(
    start_month=11,
    start_day=1,
    end_month=3,
    end_day=31,
    weekdays=tuple(range(6)),
    start_time=time(7),
    end_time=time(22),
)


def tariff(component=Component.ENERGY_IMPORT, **changes):
    values = dict(
        provider="Synthetic provider",
        product="Synthetic product",
        effective_from=START,
        component=component,
        unit="EUR_PER_KWH",
        unit_price=D(".10"),
        price_basis="GROSS",
        vat_rate=D("25.5"),
        source_document_id="synthetic-document",
        source_version="test-v1",
        source_kind="CONTRACT",
    )
    if component in (Component.GRID_FIXED_FEE, Component.SUPPLIER_FIXED_FEE):
        values.update(unit="EUR_PER_MONTH", unit_price=D("5"))
    if component == Component.GRID_TRANSFER:
        values.update(season=SEASON)
    if component == Component.SOLAR_EXPORT_CREDIT:
        values.update(unit_price=D(".03"), export_spot_rate=D(".04"), export_margin=D(".01"))
    return Tariff(**{**values, **changes})


def tariffs():
    return Tariffs(
        [
            tariff(),
            tariff(Component.GRID_TRANSFER, window=Window.WINTER_DAY),
            tariff(Component.GRID_TRANSFER, window=Window.OTHER_TIME, unit_price=D(".02")),
            tariff(Component.ELECTRICITY_TAX, unit_price=D(".01")),
            tariff(Component.GRID_FIXED_FEE),
            tariff(Component.SUPPLIER_FIXED_FEE),
            tariff(Component.SOLAR_EXPORT_CREDIT),
        ]
    )


def readings(start=START, end=END, consumption="1", export="0"):
    return [
        Reading(timestamp=t, consumption_kwh=D(consumption), solar_export_kwh=D(export))
        for t in hours(start, end)
    ]


def scenario(**changes):
    definition = ElectricityScenario(
        **{
            **dict(
                name="Synthetic",
                import_pricing_type="fixed",
                fixed_import_price=D(".10"),
                supplier_monthly_fee=D("5"),
                price_basis="GROSS",
                vat_rate=D("25.5"),
            ),
            **changes,
        }
    )
    return definition


def spot(rows, price=".04", **changes):
    meta = SpotMetadata(
        **{
            **dict(
                source="synthetic",
                market_area="FI",
                currency="EUR",
                resolution="PT1H",
                timezone="UTC",
                price_basis="NET",
                vat_rate=D("25.5"),
            ),
            **changes,
        }
    )
    return SpotPrices({r.timestamp: D(price) for r in rows}, meta, "synthetic-sha256")


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        ("2025-11-03T06:59:00+02:00", "OTHER_TIME"),
        ("2025-11-03T07:00:00+02:00", "WINTER_DAY"),
        ("2025-11-03T21:59:00+02:00", "WINTER_DAY"),
        ("2025-11-03T22:00:00+02:00", "OTHER_TIME"),
        ("2025-11-02T12:00:00+02:00", "OTHER_TIME"),
        ("2025-11-01T12:00:00+02:00", "WINTER_DAY"),
        ("2025-07-01T12:00:00+03:00", "OTHER_TIME"),
        ("2025-03-31T21:59:00+03:00", "WINTER_DAY"),
        ("2025-04-01T12:00:00+03:00", "OTHER_TIME"),
        ("2025-10-31T12:00:00+02:00", "OTHER_TIME"),
        ("2025-11-03T05:00:00Z", "WINTER_DAY"),
        ("2025-11-03T04:59:00Z", "OTHER_TIME"),
        ("2025-03-30T00:00:00Z", "OTHER_TIME"),
        ("2025-03-30T01:00:00Z", "OTHER_TIME"),
        ("2025-10-26T00:00:00Z", "OTHER_TIME"),
        ("2025-10-26T01:00:00Z", "OTHER_TIME"),
    ],
)
def test_local_clock_boundaries(timestamp, expected):
    assert classify_grid_tariff(datetime.fromisoformat(timestamp), SEASON) == expected


@pytest.mark.parametrize("day,count", [(date(2025, 3, 30), 23), (date(2025, 10, 26), 25)])
def test_dst_intervals(day, count):
    rs = readings(day, day)
    assert len(validate_readings(rs, day, day)) == count
    assert len({r.timestamp for r in rs}) == count
    locals_ = [r.timestamp.astimezone(HELSINKI) for r in rs]
    assert sum(t.hour == 3 for t in locals_) == (0 if count == 23 else 2)


def test_effective_boundaries():
    t = tariff(effective_to=date(2025, 2, 1))
    assert t.covers(START)
    assert t.covers(END)
    assert not t.covers(date(2024, 12, 31))
    assert not t.covers(date(2025, 2, 1))


def test_overlap_rejected():
    with pytest.raises(CostError, match="OVERLAPPING"):
        Tariffs([tariff(), tariff(effective_from=END)])


def test_adjacent_allowed():
    ts = Tariffs([tariff(effective_to=date(2025, 2, 1)), tariff(effective_from=date(2025, 2, 1))])
    assert ts.get(Component.ENERGY_IMPORT, END).effective_from == START


@pytest.mark.parametrize("component", list(Component))
def test_missing_tariff(component):
    with pytest.raises(CostError, match="MISSING_PRICE"):
        Tariffs([]).get(component, START)


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price", 0.1),
        ("vat_rate", 25.5),
        ("unit_price", "NaN"),
        ("unit_price", "Infinity"),
        ("source_document_id", ""),
        ("source_version", ""),
        ("effective_to", START),
        ("vat_rate", "101"),
    ],
)
def test_tariff_invalid_or_missing_provenance(field, value):
    with pytest.raises(ValidationError):
        tariff(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("consumption_kwh", 0.2),
        ("solar_export_kwh", "-1"),
        ("timestamp", datetime(2025, 1, 1)),
        ("timestamp", datetime(2025, 1, 1, 0, 15, tzinfo=UTC)),
    ],
)
def test_reading_validation(field, value):
    with pytest.raises(ValidationError):
        Reading(
            **{
                **dict(
                    timestamp=datetime(2025, 1, 1, tzinfo=UTC),
                    consumption_kwh="1",
                    solar_export_kwh="0",
                ),
                field: value,
            }
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra"])
def test_exact_measurement_coverage(mutation):
    rows = readings()
    if mutation == "missing":
        rows.pop()
    if mutation == "duplicate":
        rows.append(rows[0])
    if mutation == "extra":
        rows.append(
            Reading(
                timestamp=rows[-1].timestamp + timedelta(hours=1),
                consumption_kwh="1",
                solar_export_kwh="0",
            )
        )
    with pytest.raises(CostError):
        calculate(rows, tariffs(), START, END)


def test_decimal_components_monthly_annual_and_provenance():
    rows = readings(export=".5")
    result = calculate(rows, tariffs(), START, END)
    m = result["monthly"][0]
    assert m["consumption_kwh"] == 744
    assert m["supplier_energy_cost"] == D("74.40")
    assert m["electricity_tax_cost"] == D("7.44")
    assert m["supplier_fixed_cost"] == m["grid_fixed_cost"] == D("5")
    assert m["solar_export_credit"] == D("11.16")
    assert m["spot_export_value"] == D("14.88")
    assert m["export_margin"] == D("3.72")
    assert m["grid_winter_day_kwh"] + m["grid_other_time_kwh"] == 744
    assert m["grid_transfer_cost"] == money(
        m["grid_winter_day_kwh"] * D(".1") + m["grid_other_time_kwh"] * D(".02")
    )
    assert (
        m["net_total_cost"]
        == sum(
            m[k]
            for k in (
                "supplier_energy_cost",
                "electricity_tax_cost",
                "supplier_fixed_cost",
                "grid_fixed_cost",
                "grid_transfer_cost",
            )
        )
        - m["solar_export_credit"]
    )
    assert abs(m["effective_cost_per_consumed_kwh"] - m["net_total_cost"] / 744) < D("1e-27")
    assert result["yearly"][0]["net_total_cost"] == m["net_total_cost"]
    assert not result["yearly"][0]["full_year"]
    assert sum(r["supplier_energy_cost"] for r in result["daily"]) == D("74.4")
    assert all(p["source_document_id"] == "synthetic-document" for p in result["provenance"])
    assert result["mode"] == "ACTUAL_RECONSTRUCTION"


def test_partial_fee_policy():
    result = calculate(readings(START, START), tariffs(), START, START)
    m = result["monthly"][0]
    assert m["grid_fixed_cost"] is None and m["supplier_fixed_cost"] is None
    assert m["net_total_cost"] is None
    assert m["known_component_subtotal"] > 0
    assert "PARTIAL_MONTH_FIXED_FEE_NOT_ALLOCATED" in result["warnings"]


def test_zero_denominators():
    m = calculate(readings(consumption="0"), tariffs(), START, END)["monthly"][0]
    assert m["effective_cost_per_consumed_kwh"] is None
    assert m["average_credit_per_exported_kwh"] is None


def test_no_premature_hour_rounding():
    rs = readings(consumption=".01")
    m = calculate(rs, tariffs(), START, END)["monthly"][0]
    assert m["supplier_energy_cost"] == D(".74")
    assert sum(money(r.consumption_kwh * D(".1")) for r in rs) == 0


@pytest.mark.parametrize(
    "value,expected", [("1.005", "1.01"), ("-1.005", "-1.01"), ("1.0049", "1.00")]
)
def test_invoice_rounding(value, expected):
    assert money(D(value)) == D(expected)


def test_precise_net_vat_not_display_price():
    assert tariff(unit_price=D(".022"), price_basis="NET").gross_rate == D(".02761")
    assert tariff(unit_price=D(".0276"), price_basis="GROSS").gross_rate == D(".0276")


def test_historical_gap_not_carried_back():
    with pytest.raises(CostError, match="MISSING_PRICE"):
        calculate(
            readings(date(2024, 12, 1), date(2024, 12, 31)),
            tariffs(),
            date(2024, 12, 1),
            date(2024, 12, 31),
        )


def test_missing_supplier_not_invented():
    ts = Tariffs([t for t in tariffs().values if t.component != Component.ENERGY_IMPORT])
    with pytest.raises(CostError, match="MISSING_PRICE"):
        calculate(readings(), ts, START, END)


def csv_file(tmp_path, rows=None, **meta):
    p = tmp_path / "prices.csv"
    p.write_text(
        "timestamp_utc,market_area,price_eur_per_mwh\n" + (rows or "2025-01-01T00:00:00Z,FI,40\n")
    )
    p.with_suffix(".json").write_text(
        json.dumps(
            {
                **dict(
                    source="Synthetic",
                    market_area="FI",
                    currency="EUR",
                    resolution="PT1H",
                    timezone="UTC",
                    price_basis="NET",
                    vat_rate="25.5",
                ),
                **meta,
            }
        )
    )
    return p


def test_csv_conversion_and_vat(tmp_path):
    s = read_spot(csv_file(tmp_path))
    t = datetime(2025, 1, 1, tzinfo=UTC)
    assert s.prices[t] == D(".04")
    assert s.gross(t) == D(".05020")
    s = read_spot(csv_file(tmp_path, price_basis="GROSS"))
    assert s.gross(t) == D(".04")


@pytest.mark.parametrize(
    "row",
    [
        "2025-01-01T00:00:00Z,FI,1\n2025-01-01T00:00:00Z,FI,2\n",
        "2025-01-01T00:00:00Z,SE,1\n",
        "2025-01-01T00:00:00,FI,1\n",
        "2025-01-01T00:00:00+02:00,FI,1\n",
        "2025-01-01T00:15:00Z,FI,1\n",
        "2025-01-01T00:00:00Z,FI,NaN\n",
    ],
)
def test_spot_invalid_rows(tmp_path, row):
    with pytest.raises(ValueError):
        read_spot(csv_file(tmp_path, row))


@pytest.mark.parametrize(
    "field,value",
    [
        ("market_area", "SE"),
        ("currency", "USD"),
        ("resolution", "PT15M"),
        ("price_basis", "UNKNOWN"),
        ("vat_rate", "101"),
        ("source", ""),
    ],
)
def test_spot_invalid_metadata(tmp_path, field, value):
    with pytest.raises(ValueError):
        read_spot(csv_file(tmp_path, **{field: value}))


def test_spot_missing_hour(tmp_path):
    s = read_spot(csv_file(tmp_path))
    with pytest.raises(CostError, match="MISSING_SPOT"):
        s.require(readings())


def test_weighted_prices_and_timing():
    rs = readings(START, START)[:2]
    rs = [
        rs[0].model_copy(update={"consumption_kwh": D("3"), "solar_export_kwh": D("0")}),
        rs[1].model_copy(update={"consumption_kwh": D("1"), "solar_export_kwh": D("2")}),
    ]
    s = spot(rs)
    s = SpotPrices({rs[0].timestamp: D(".10"), rs[1].timestamp: D(".02")}, s.metadata, "test")
    w = weighted_prices(rs, s)
    assert w["simple_average"] == D(".06")
    assert w["consumption_weighted"] == D(".08")
    assert w["export_weighted"] == D(".02")
    assert w["load_timing_effect"] == D(".02")


def test_fixed_scenario_and_immutability():
    rs = readings()
    ts = tariffs()
    before = copy.deepcopy((rs, ts.values))
    result = calculate(rs, ts, START, END, supplier=SupplierScenario(scenario()))
    assert result["mode"] == "SCENARIO"
    assert result["scenario"]["source_kind"] == "USER_SCENARIO"
    assert result["monthly"][0]["supplier_energy_cost"] == D("74.40")
    assert (rs, ts.values) == before


@pytest.mark.parametrize("fee,expected", [("5", ".0552"), ("7", None)])
def test_spot_markup_break_even_and_fees(fee, expected):
    rs = readings()
    fixed = SupplierScenario(scenario())
    s = SupplierScenario(
        scenario(
            import_pricing_type="spot",
            fixed_import_price=None,
            spot_markup_per_kwh=D(".005"),
            supplier_monthly_fee=D(fee),
        ),
        spot(rs),
    )
    result = compare(rs, tariffs(), START, END, fixed, s)
    assert result["winner"] == "spot"
    assert result["break_even_gross_eur_per_kwh"] == D(".0552") + (D(fee) - 5) / 744
    a = result["fixed"]["monthly"][0]
    b = result["spot"]["monthly"][0]
    assert a["consumption_kwh"] == b["consumption_kwh"] == 744
    assert a["grid_transfer_cost"] == b["grid_transfer_cost"]
    assert b["raw_spot_energy_cost"] == D("37.35")
    assert b["retailer_markup_cost"] == D("3.72")


def test_independent_export_source_required():
    d = scenario(
        export_pricing_type="spot",
        export_margin=D(".01"),
        export_price_basis="GROSS",
        export_vat_rate=D(0),
    )
    with pytest.raises(CostError, match="INDEPENDENT_EXPORT"):
        SupplierScenario(d)


def test_negative_spot_and_export_credit():
    rs = readings(export="1")
    d = scenario(
        import_pricing_type="spot",
        fixed_import_price=None,
        export_pricing_type="spot",
        export_margin=D(".01"),
        export_price_basis="GROSS",
        export_vat_rate=D(0),
    )
    s = SupplierScenario(d, spot(rs, "-.02"), spot(rs, ".06", price_basis="GROSS"))
    r = s.hour(rs[0])
    assert r["supplier_energy_cost"] == D("-.0251")
    assert r["solar_export_credit"] == D(".05")


def test_omitted_export_prevents_total():
    r = calculate(
        readings(export="1"), tariffs(), START, END, supplier=SupplierScenario(scenario())
    )
    assert r["monthly"][0]["net_total_cost"] is None
    with pytest.raises(CostError, match="EXPORT_TERMS"):
        compare(
            readings(export="1"),
            tariffs(),
            START,
            END,
            SupplierScenario(scenario()),
            SupplierScenario(
                scenario(import_pricing_type="spot", fixed_import_price=None), spot(readings())
            ),
        )


def test_coverage_audit():
    rs = readings()
    r = audit(rs, tariffs(), START, END, spot(rs))
    assert r["energy_readings_hours"] == r["grid_tariff_hours"] == r["spot_prices_hours"] == 744
    assert not any(r["missing_ranges_utc"].values())


def source_payload(missing=None, duplicate=False):
    items = [
        {"date": f"2025-01-01T00:{m:02d}:00Z", "value": str(v)}
        for m, v in zip((0, 15, 30, 45), ("10", "20", "30", "40"), strict=True)
        if m != missing
    ]
    if duplicate:
        items.append(items[0])
    return json.dumps({"prices": items}).encode()


def normalized(payload):
    return normalize_sahkotin(
        payload,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
        "synthetic-retrieval",
    )


def test_quarter_conversion():
    observations = normalized(source_payload())
    assert list(aggregate_hours(observations).values()) == [D("25")]
    assert observations[0]["price_eur_per_kwh"] == D(".01")
    assert observations[0]["vat_included"] is False
    assert observations[0]["interval_end_utc"] - observations[0]["timestamp_utc"] == timedelta(
        minutes=15
    )


@pytest.mark.parametrize("missing", [0, 15, 30, 45])
def test_incomplete_quarters_not_filled(missing):
    assert aggregate_hours(normalized(source_payload(missing))) == {}


def test_duplicate_source_quarter():
    with pytest.raises(CostError, match="DUPLICATE_SOURCE"):
        normalized(source_payload(duplicate=True))


def test_provider_cache_no_repeat_network(tmp_path, monkeypatch):
    import io

    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        return io.BytesIO(source_payload())

    monkeypatch.setattr("data_pipeline.energy_cost.provider.urlopen", fetch)
    provider = SahkotinProvider(tmp_path)
    a, b = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)
    first = provider.fetch(a, b)
    second = provider.fetch(a, b)
    assert first == second and len(calls) == 1
    provider.fetch(a, b, refresh=True)
    assert len(calls) == 2


def test_source_projection_does_not_mutate():
    docs = [("synthetic", {"kind": "UNRELATED", "bill": {}})]
    before = copy.deepcopy(docs)
    assert not project_tariffs(docs, "synthetic-meter").values
    assert docs == before


def test_document_projection_rates_dates_and_no_mutation():
    from apps.api.tests.document_fixtures import contract, vattenfall
    from data_pipeline.documents.detect import parser_for

    docs = []
    for pages in (contract(), vattenfall()):
        docs.append(
            (
                "synthetic-document-" + str(len(docs)),
                parser_for(pages).parse(pages).model_dump(mode="json"),
            )
        )
    before = copy.deepcopy(docs)
    ts = project_tariffs(docs, "111111111111111111")
    assert len(ts.values) == 7
    grid, _ = ts.grid(datetime(2026, 1, 2, 10, tzinfo=UTC))
    assert grid.gross_rate == D(".02510")
    assert grid.source_document_id == "synthetic-document-0"
    assert ts.get(Component.ENERGY_IMPORT, date(2026, 1, 15)).gross_rate == D(".1255")
    assert ts.get(Component.SOLAR_EXPORT_CREDIT, date(2026, 1, 15)).gross_rate == D(".125")
    with pytest.raises(CostError):
        ts.get(Component.ENERGY_IMPORT, date(2026, 2, 1))
    assert docs == before
    assert not project_tariffs(docs, "unrelated-meter").values


def test_synthetic_invoice_reconciliation_retains_difference():
    from apps.api.tests.document_fixtures import vattenfall
    from data_pipeline.documents.detect import parser_for
    from data_pipeline.energy_cost.reconciliation import reconcile_invoice

    pages = vattenfall()
    m = parser_for(pages).parse(pages).model_dump(mode="json")
    ts = project_tariffs([("synthetic-document", m)], "111111111111111111")
    a, b = date(2026, 1, 1), date(2026, 1, 31)
    rs = readings(a, b, consumption="0", export="0")
    rs[0] = rs[0].model_copy(update={"consumption_kwh": D("100"), "solar_export_kwh": D("10")})
    before = copy.deepcopy(m)
    result = reconcile_invoice(rs, ts, m, a, b)
    assert result["status"] == "VALIDATED" and result["calculated_total"] == D("13.81")
    m["bill"]["total_eur"] = "14.81"
    changed = reconcile_invoice(rs, ts, m, a, b)
    assert changed["status"] == "DIFFERENCES" and "CALCULATION_ERROR" in changed["categories"]
    assert before["bill"]["total_eur"] == "13.81"


def test_midmonth_fixed_change_needs_policy():
    ts = tariffs()
    definitions = [t for t in ts.values if t.component != Component.GRID_FIXED_FEE]
    definitions.extend(
        [
            tariff(Component.GRID_FIXED_FEE, effective_to=date(2025, 1, 15)),
            tariff(Component.GRID_FIXED_FEE, effective_from=date(2025, 1, 15), unit_price=D("6")),
        ]
    )
    with pytest.raises(CostError, match="MID_MONTH_FIXED"):
        calculate(readings(), Tariffs(definitions), START, END)


def test_full_year_months_aggregate():
    end = date(2025, 12, 31)
    result = calculate(readings(START, end, consumption="0"), tariffs(), START, end)
    assert result["yearly"][0]["full_year"]
    assert result["yearly"][0]["supplier_fixed_cost"] == 60
    assert result["yearly"][0]["net_total_cost"] == 120


def test_comparison_requires_same_export():
    rs = readings()
    fixed = SupplierScenario(scenario())
    variable = SupplierScenario(
        scenario(
            import_pricing_type="spot",
            fixed_import_price=None,
            export_pricing_type="fixed",
            export_fixed_price=D(".05"),
            export_margin=D(0),
            export_price_basis="GROSS",
            export_vat_rate=D(0),
        ),
        spot(rs),
    )
    with pytest.raises(CostError, match="IDENTICAL_EXPORT"):
        compare(rs, tariffs(), START, END, fixed, variable)


def test_supplier_comparison_missing_grid_is_explicit():
    rs = readings()
    result = compare(
        rs,
        Tariffs([]),
        START,
        END,
        SupplierScenario(scenario()),
        SupplierScenario(scenario(import_pricing_type="spot", fixed_import_price=None), spot(rs)),
        scope="supplier",
    )
    m = result["fixed"]["monthly"][0]
    assert m["scope_total"] == D("79.40")
    assert m["net_total_cost"] is None and m["grid_winter_day_kwh"] is None


def test_separate_spot_components_add_up_after_rounding():
    rs = readings(consumption="2.774665322580645161290322581")
    s = SupplierScenario(
        scenario(
            import_pricing_type="spot", fixed_import_price=None, spot_markup_per_kwh=D(".008")
        ),
        spot(rs, ".05628884730358354756531229428"),
    )
    m = calculate(rs, tariffs(), START, END, supplier=s)["monthly"][0]
    assert m["supplier_energy_cost"] == m["raw_spot_energy_cost"] + m["retailer_markup_cost"]


def test_spot_gross_averages():
    rs = readings()
    w = weighted_prices(rs, spot(rs))
    assert w["gross_retail_basis"]["consumption_weighted"] == D(".05020")
    assert w["import_minus_export_weighted"] is None


def test_cache_superset_reused(tmp_path, monkeypatch):
    import io

    calls = []

    def fetch(*args, **kwargs):
        calls.append(1)
        return io.BytesIO(source_payload())

    monkeypatch.setattr("data_pipeline.energy_cost.provider.urlopen", fetch)
    provider = SahkotinProvider(tmp_path)
    a = datetime(2025, 1, 1, tzinfo=UTC)
    provider.fetch(a, a + timedelta(days=2))
    provider.fetch(a, a + timedelta(days=1))
    assert len(calls) == 1


def test_cache_tampering_rejected(tmp_path, monkeypatch):
    import io

    monkeypatch.setattr(
        "data_pipeline.energy_cost.provider.urlopen",
        lambda *args, **kwargs: io.BytesIO(source_payload()),
    )
    provider = SahkotinProvider(tmp_path)
    a = datetime(2025, 1, 1, tzinfo=UTC)
    provider.fetch(a, a + timedelta(days=1))
    next(tmp_path.glob("*.raw.json")).write_bytes(b"{}")
    with pytest.raises(CostError, match="HASH_MISMATCH"):
        provider.fetch(a, a + timedelta(days=1))


def test_canonical_hash_checked(tmp_path):
    p = csv_file(tmp_path)
    p.with_suffix(".provenance.json").write_text('{"canonical_sha256":"wrong"}')
    with pytest.raises(CostError, match="HASH_MISMATCH"):
        read_spot(p)


def test_output_tree_gitignored():
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "data/processed/energy_cost/spot/fi_hourly.csv"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_import_break_even_without_grid_or_export_assumptions():
    from data_pipeline.energy_cost.scenarios import supplier_break_even

    rs = readings(export="2")
    s = SupplierScenario(
        scenario(
            import_pricing_type="spot",
            fixed_import_price=None,
            spot_markup_per_kwh=D(".005"),
            supplier_monthly_fee=D("7"),
        ),
        spot(rs),
    )
    r = supplier_break_even(rs, START, END, s, D("5"))
    assert r["scope"] == "SUPPLIER_IMPORT_ONLY"
    assert r["break_even_gross_eur_per_kwh"] == D(".0552") + D(2) / 744
    assert "not assumed zero" in r["assumption"]


def test_import_break_even_partial_month_rejected():
    from data_pipeline.energy_cost.scenarios import supplier_break_even

    rs = readings(START, START)
    s = SupplierScenario(scenario(import_pricing_type="spot", fixed_import_price=None), spot(rs))
    with pytest.raises(CostError, match="COMPLETE_CALENDAR"):
        supplier_break_even(rs, START, START, s, D("5"))


def test_net_export_components_apply_same_vat_basis():
    definitions = [t for t in tariffs().values if t.component != Component.SOLAR_EXPORT_CREDIT]
    definitions.append(tariff(Component.SOLAR_EXPORT_CREDIT, price_basis="NET"))
    m = calculate(readings(export="1"), Tariffs(definitions), START, END)["monthly"][0]
    assert m["spot_export_value"] == money(D(744) * D(".04") * D("1.255"))
    assert m["export_margin"] == money(D(744) * D(".01") * D("1.255"))
    assert m["solar_export_credit"] == m["spot_export_value"] - m["export_margin"]
