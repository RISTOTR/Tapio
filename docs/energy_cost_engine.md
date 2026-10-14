# Phase 04 — deterministic electricity cost engine

Phase 04A reconstructs source-supported billed components. Phase 04B applies explicit
retail scenarios to the **same measured consumption**, without shifting any load.
Calculations use Decimal; they do not involve an LLM, forecasts, weather, or inferred PV.

## Architecture and storage

`data_pipeline/energy_cost/` contains immutable domain contracts (`types.py`), read-only
source projections (`sources.py`), calculation/aggregation (`engine.py`), invoice
reconciliation, coverage auditing, spot-file validation, scenarios, and an external
Sähkötin adapter. CLI transactions explicitly use PostgreSQL `READ ONLY`.

No schema change or migration 0006 is needed. Existing `Document.document_metadata`
retains the parsed prices, periods, schedules, and source evidence. Frozen tariff objects
are projected from those facts on demand. No hypothetical prices are written to invoices,
invoice lines, bill details, contracts, readings, or bank records. Derived JSON/CSV and
raw spot responses stay under ignored `data/processed/energy_cost/`.

## Components, signs, and completeness

The domain distinguishes `ENERGY_IMPORT`, `GRID_TRANSFER`, `ELECTRICITY_TAX`,
`GRID_FIXED_FEE`, `SUPPLIER_FIXED_FEE`, `SOLAR_EXPORT_CREDIT`, and
`OTHER_BILLED_COMPONENT`. Expenses are positive; export credits are positive when paid
to the household. A negative export credit is an expense. Costs minus credits give net
cost. `solar_export_kwh` is grid export, never gross generation or self-consumption.

Each full monthly result includes consumption/export, winter/other grid volumes,
supplier energy and fees, grid transfer and fees, electricity tax, export value/margin/
credit, totals, and effective cost per consumed kWh. Spot scenarios additionally separate
VAT-adjusted raw market energy, retailer markup, and retailer monthly fee. The raw
source observations themselves remain VAT-exclusive.

`scope=grid` or `scope=supplier` returns a component `scope_total`; `net_total_cost`
remains null for those scopes. Unsupported/unselected components are null, not zero.
`other_billed_cost` is currently unsupported and remains null. Even an `all` total is
explicitly a total of **modeled components**, excluding unsupported other charges.
Invoice reconciliation flags any unhandled billed component. Network production charges
are not inferred from fuse size: the contract's nameplate-power exemption condition
cannot be established from the available information.

For unknown export terms, omit export pricing. Positive exported volume then prevents
a complete scenario net total, while `known_component_subtotal` remains available.
Zero measured export contributes zero credit without inventing an export tariff.

## Clock and effective dates

Ingestion establishes that readings represent **hourly interval starts**. The engine
converts persisted UTC timestamps to `Europe/Helsinki` before applying date, weekday,
and clock rules. Date arguments are inclusive Helsinki dates; internal boundaries are
half-open UTC intervals. Spring and autumn transition days contain 23 and 25 hours.
Neither duplicate local wall-clock hours nor the missing spring hour are repaired.

The documented seasonal schedule is November 1–March 31, Monday–Saturday,
07:00 inclusive to 22:00 exclusive. Sundays and all other times are `OTHER_TIME`.
Rates and schedule come from stored contract facts, not production-code constants.
The projected start is the later of contract start and price-sheet start. The April 2026
sheet therefore cannot price 2025 or early 2026. An absent source end remains open;
this is the documented contract definition, not evidence of future unchanged prices.

Supplier invoice prices cover only their explicit invoiced dates, with exclusive end
at the following midnight. They are never carried forward. The invoice's export average
is labeled `BILLED_EXPORT_AVERAGE`, not treated as a historical hourly spot series.

Tariffs retain provider, product, effective dates, component, window, unit, net/gross
basis, VAT percentage, source document ID, parser version, and source kind. Overlapping
same-component/window definitions fail before calculation/audit; gaps raise
`MISSING_PRICE_COVERAGE`. Multiple reading meters require an explicit meter selection.

## Precision, rounding, and fees

Money inputs reject binary floats and nonfinite values. Hourly multiplication uses
Decimal with 34-digit calculation precision. Hourly values are not rounded to cents.
Monthly component sums use `ROUND_HALF_UP` to two decimals. Winter and other transfer
lines round separately. Export market value and margin round separately, then subtract.
Scenario market energy and markup also round separately, then add; displayed components
therefore add to the reported supplier total. Annual totals sum monthly rounded amounts.
Daily results contain variable costs without artificially distributing monthly fees.

Grid net rates are multiplied by the VAT factor evidenced by the contract's precise
net/gross tax pair. A rounded displayed gross tariff is not substituted for that value.
For example, the September acceptance case needs the precise derived gross transfer
rate to reproduce the billed line. No balancing rows or correction amounts are inserted.

Full calendar months receive one applicable monthly fee. Partial periods report variable
costs and a null fixed fee/complete total, with `PARTIAL_MONTH_FIXED_FEE_NOT_ALLOCATED`.
Mid-month fee changes fail unless a future explicit billing policy is implemented.
Effective cost divides net modeled cost by **consumed** kWh, never consumption plus
export. Zero denominators return null. Annual percentages use signed components;
export is negative, and zero totals return null percentages. Partial years are labeled.

Invoice reports distinguish quantity/display rounding, measurement differences, tariff
gaps, unsupported components, and calculation errors. A one-cent monetary residual is
reported within rounding tolerance, with an explicit warning that hidden source-price
precision has not been verified. This does not establish why the source bill differs.

## Real spot data contract and acquisition

The external adapter follows [Sähkötin's API](https://sahkotin.fi/api): `quarter` requests
quarter-hour slots; omitting `fix` and `vat` requests net EUR/MWh. It uses a timeout,
limited retries/backoff, request-keyed raw response caching, retrieval timestamps, and
SHA-256 checks. A cached superset can serve a narrower request. Explicit `--refresh`
refetches; ordinary calculations only read local files. No property readings, identifiers,
or load profiles are sent to a provider.

Canonical observations retain UTC interval start/end, FI market area, EUR/MWh and
EUR/kWh, `vat_included=false`, source, retrieval timestamp, and source resolution.
The API's requested quarter series repeats hourly values in the earlier hourly market
era. Those are provider-returned slots, not evidence of earlier quarter-hour settlement.

Exactly four distinct UTC quarter slots produce one hourly price by arithmetic mean.
A missing quarter makes the hour unavailable. This assumes no known within-hour load
shape; it does **not** create quarter-hour consumption. UTC alignment handles DST.
Raw and canonical prices are preserved separately so the transformation can be audited.

The calculation input CSV has exactly these columns:

```csv
timestamp_utc,market_area,price_eur_per_mwh
2025-01-01T00:00:00Z,FI,40.00
```

The same basename `.json` sidecar supplies explicit metadata:

```json
{"source":"synthetic example","market_area":"FI","currency":"EUR",
 "resolution":"PT1H","timezone":"UTC","price_basis":"NET","vat_rate":"25.5"}
```

VAT rate is a **percentage**: `25.5`, not `0.255`. NET prices are multiplied by
`1 + vat_rate/100`; GROSS prices are not. Retail markup/fee basis is independently
explicit. The user's primary comparison applies 25.5% to net market prices, including
negative prices, and treats the supplied markup/fees as already gross. This is the
specified scenario arithmetic, not a conclusion about every retailer's settlement.

Duplicate timestamps, invalid area/currency/resolution, naive or non-hourly canonical
timestamps, nonfinite prices, and missing required hours fail validation. Negative
prices are allowed. Canonical output includes a provenance sidecar tying its hash to
the raw request/hash and retrieval time. Tests use synthetic fixtures, not live APIs.
A small positive-price sample was independently checked against
[Porssisahko's API](https://porssisahko.net/api), accounting for its gross cents/kWh units
and display rounding; it is not a second runtime dependency.

## Scenarios, weighted prices, and break-even

All CLI-supplied terms are `USER_SCENARIO`; actual reconstructions are separately marked
`ACTUAL_RECONSTRUCTION`. A scenario changes prices only. Grid schedules, taxes, timestamps,
and measured quantities remain unchanged. Export pricing can independently be fixed,
spot from an explicitly selected source, or omitted; import spot is never implicitly
reused for export settlement.

For prices p and measured consumption q, consumption-weighted price is sum(q*p)/sum(q).
The simple average weights each measured hour equally. Export weighting uses exported
kWh instead. Load-timing effect = consumption-weighted minus simple price. Positive
means the observed load is more concentrated in expensive hours. It is descriptive,
not an optimization or a claim that the household can shift heating. Reports include
both source-net and VAT-adjusted views, and import-minus-export weighted prices.

Fixed-versus-spot comparisons use identical measured profiles and export assumptions.
Differences and percentages refer to the reported scope. Supplier-only comparison is
possible without guessing historical grid prices: common grid costs cancel, but their
absolute amounts stay unknown. A whole-household total requires its own coverage.

The analytical gross fixed import break-even rate is:

```text
(spot market energy + retailer markup + spot fixed fees - fixed-contract fixed fees)
/ measured consumption
```

It is calculated before cent rounding, with unchanged grid/tax/export terms. The
`break_even` command also supports import-only annual thresholds when historical fixed
price evidence is absent. This is explicitly a scenario threshold with a user-specified
fixed monthly fee, not an annual actual-contract winner. It requires complete calendar
months. Zero consumption gives null. Different monthly fees change the threshold.

## Commands

Run from the repository root with `.venv/bin/python` or `uv run python`.

```sh
# Source-supported September grid reconstruction (supplier coverage is absent).
uv run python -m data_pipeline.energy_cost.actual --start 2026-09-01 --end 2026-09-30 \
  --scope grid --output data/processed/energy_cost/september_grid.json

# Stored electricity invoices wholly inside the requested date range.
uv run python -m data_pipeline.energy_cost.actual --start 2024-09-01 --end 2026-10-05 \
  --reconcile --output data/processed/energy_cost/invoice_reconciliation.json

# Explicit external acquisition; repeat uses cache.
uv run python -m data_pipeline.energy_cost.provider --start 2025-01-01 --end 2026-10-05 \
  --vat-rate 25.5

# Coverage plus monthly/yearly weighted-price statistics.
uv run python -m data_pipeline.energy_cost.audit --start 2025-01-01 --end 2026-10-05 \
  --spot-source data/processed/energy_cost/spot/fi_hourly.csv \
  --output data/processed/energy_cost/tariff_coverage.json

# January's documented fixed terms vs user-supplied primary retail spot terms.
uv run python -m data_pipeline.energy_cost.simulate --start 2025-01-01 --end 2025-01-31 \
  --scope supplier --compare --fixed-price-eur-kwh 0.0888 --supplier-monthly-fee 5.95 \
  --spot-source data/processed/energy_cost/spot/fi_hourly.csv \
  --spot-markup-eur-kwh 0.005 --spot-supplier-monthly-fee 5.95 \
  --price-basis GROSS --vat-rate 25.5 \
  --output data/processed/energy_cost/comparison_primary_cli.json

# Annual supplier import threshold; fixed monthly fee is an explicit assumption.
uv run python -m data_pipeline.energy_cost.break_even --start 2025-01-01 --end 2025-12-31 \
  --spot-source data/processed/energy_cost/spot/fi_hourly.csv \
  --spot-markup-eur-kwh 0.005 --supplier-monthly-fee 5.95 \
  --fixed-monthly-fee-gross 5.95 --price-basis GROSS --vat-rate 25.5 \
  --output data/processed/energy_cost/break_even_2025.json
```

A fixed-only scenario omits `--compare` and `--spot-source`. Export flags are
`--export-pricing`, `--export-price-eur-kwh`, `--export-margin-eur-kwh`,
`--export-price-basis`, `--export-vat-rate`, and `--export-spot-source`.
Use `--help` for the full interface. Date ranges with absent measured data or required
prices fail; they are not truncated silently. JSON preserves Decimal amounts as strings.
Actual/scenario reports with monthly rows also write a sibling monthly CSV. Keep all
output paths private. No frontend or plot is required to assess these results.
