# Phase 04 review — 2026-10-14

Completed historical reconstruction, deterministic retail scenarios, real FI spot
acquisition/cache, and no-flexibility load-profile analysis. This phase stops here.

## Changes and source evidence

Added `data_pipeline/energy_cost/` domain/source/engine/reconciliation/coverage modules,
strict spot CSV input, cached Sähkötin provider, scenario/comparison/break-even routines,
and `actual`, `audit`, `simulate`, `provider`, and `break_even` CLIs. Added synthetic
coverage in `apps/api/tests/test_energy_cost.py` and the engine/review documentation.
No existing migrations or source records were changed; no new dependencies were added.

No schema migration was necessary. Existing immutable document metadata provides the
required facts. Ten tariff definitions are projected, not inserted: four grid components
from the consumption contract, plus supplier import/fixed/export definitions for each
of September 2024 and January 2025. Production contract evidence is retained but does
not justify assuming its capacity-dependent exemption applies. Invoice production
charges in the September acceptance case are explicitly zero.

Source links, parser versions, products, providers, periods, precise prices, and basis
are retained in private result provenance. Scenario retail terms come from the user:
Vattenfall Optimi Pörssisähkö, gross markup €0.005/kWh, gross fee €5.95/month, and 25.5%
VAT on net market prices. The sensitivity terms are also user-supplied gross amounts.
Their availability as a historical January 2025 offer is not asserted; this is a
counterfactual application of the specified offer to historical consumption.

## Exact coverage

| Evidence | Supported period / count |
|---|---|
| Consumption and grid-export measurements | Helsinki 2025-01-01 00:00 through 2026-10-05 23:00 interval starts; 15,431 hours |
| UTC measurement interval | [2024-12-31 22:00, 2026-10-05 21:00) |
| Temperature | Present for all 15,431 readings; not used in this engine |
| Documented grid transfer, electricity tax, grid fee | From 2026-04-01; 4,512 measured hours covered |
| Documented supplier import/fixed/export pricing | September 2024 and January 2025 only; 744 measured hours overlap |
| Real spot observations | 61,724 quarter-hour API slots; 15,431 complete hourly means |
| Spot duplicates / missing measured hours | 0 / 0 |
| Tariff overlaps / ambiguities | 0 / 0 |

Sähkötin raw data was retrieved on 2026-10-13 and cached privately with request URL,
retrieval timestamp, and SHA-256. It contains net EUR/MWh. The requested quarter series
repeats hourly prices before the quarter-hour market era; varying quarters first appear
in this response at 2025-09-30 22:00 UTC. There are 8,788 hours with differing quarter
prices. Four-quarter means use UTC alignment and assume no known within-hour load shape.
No quarter-hour consumption was fabricated. Repeated calculations and cache checks use
local files and do not refetch historical data.

Three independent positive-price samples from Porssisahko agree within its 0.001 c/kWh
display precision: an early hourly-era observation, an October 2025 quarter, and a
September 2026 hourly average. Maximum absolute discrepancy is 0.000275 c/kWh.
This verifies sample units/VAT conversion and quarter aggregation, not the entire series
or negative-price VAT settlement. Primary provider: [Sähkötin API](https://sahkotin.fi/api).
Verification provider: [Porssisahko API](https://porssisahko.net/api).

## Invoice acceptance

| September 2026 Elenia component | Reconstructed | Billed | Difference |
|---|---:|---:|---:|
| Consumption kWh | 707.428 | 707.43 | -0.002 |
| Winter-day kWh | 0 | 0.00 | 0 |
| Other-time kWh | 707.428 | 707.43 | -0.002 |
| Transfer | €19.53 | €19.53 | €0.00 |
| Electricity tax | €20.64 | €20.64 | €0.00 |
| Grid fixed fee | €47.10 | €47.10 | €0.00 |
| Grid total | **€87.27** | **€87.27** | **€0.00 / 0%** |

Measured export is 19.630 kWh, matching 19.63 billed. Quantity differences disappear at
the invoice's displayed precision. The derived gross transfer rate is €0.02761/kWh,
from the source net rate and VAT; the rounded printed gross rate €0.0276/kWh would
produce €19.52 instead. Hourly amounts are not rounded prematurely.

| January 2025 Vattenfall component | Reconstructed | Billed |
|---|---:|---:|
| Consumption kWh | 2,064.351 | 2,064.35 |
| Supplier energy at documented 8.88 c/kWh gross | €183.31 | €183.32 |
| Supplier fixed fee | €5.95 | €5.95 |
| Export kWh / credit | 0 / €0.00 | 0 / €0.00 |
| Supplier total | **€189.26** | **€189.27** |

The one-cent residual is 0.005283% of the invoice total. It is retained as a rounding/
source-precision residual, not balanced away; the exact supplier billing precision is
not established. September 2024 supplier and December 2024 grid invoices lack overlapping
readings. January, February, and June 2025 grid invoices lack a documented applicable
historical grid schedule. Their reconstruction reports are incomplete, not guessed.

Source-supported grid component totals for complete months are:

| 2026 month | Grid transfer + electricity tax + fixed fee |
|---|---:|
| April | €105.33 |
| May | €85.38 |
| June | €75.38 |
| July | €76.21 |
| August | €80.50 |
| September | €87.27 |
| Six-month subtotal | **€510.07** |

Only September has an imported matching invoice for this grid period. October 1–5
supports variable grid costs, with no assumed monthly-fee proration. No complete annual
actual household electricity total is established: supplier and grid tariff coverage do
not overlap in a complete measured month. January supplier cost and April–September
grid costs are legitimate scoped reconstructions, not combined whole-household totals.

## No-flexibility January fixed-versus-spot comparison

Every scenario uses the same 744 hourly readings totaling 2,064.351 kWh. No heating or
other consumption is shifted. January export is zero. The documented fixed baseline
is €189.26 reconstructed supplier cost at 8.88 c/kWh plus €5.95/month.

| Retail spot terms (gross) | Market energy incl. VAT | Markup | Fee | Supplier total | Below reconstructed fixed | Break-even fixed c/kWh |
|---|---:|---:|---:|---:|---:|---:|
| Low: €0.003/kWh + €3/month | €145.83 | €6.19 | €3.00 | €155.02 | €34.24 | 7.2213 |
| Primary: €0.005/kWh + €5.95/month | €145.83 | €10.32 | €5.95 | **€162.10** | **€27.16** | **7.5643** |
| Higher: €0.008/kWh + €7/month | €145.83 | €16.51 | €7.00 | €169.34 | €19.92 | 7.9151 |

The primary difference is **14.3506% of reconstructed supplier cost**. Compared directly
with the actual supplier invoice, the difference is €27.17, reflecting the retained
one-cent reconstruction residual. All three specified spot scenarios are cheaper for
this particular month and unchanged load profile.

Grid/tax charges are common to supplier scenarios and are not repriced or assumed zero.
The January grid invoice contains €193.92, but its historical tariff schedule is not
reconstructed. Adding that unchanged billed amount gives €383.18 reconstructed-fixed
supplier plus billed grid, versus €356.02 primary-spot supplier plus billed grid.
Those are mixed source-billed/common-cost totals, not independently reconstructed
whole-household costs. The €27.16 difference is unchanged; the 14.3506% above is a
supplier percentage, not a whole-bill percentage.

## Consumption timing and export-weighted prices

All values below are **c/kWh including the specified 25.5% VAT**, before retailer markup
or fees. Source-net values and monthly results are also stored privately.

| Measured period | Simple average | Consumption-weighted | Load-timing effect | Export-weighted |
|---|---:|---:|---:|---:|
| January 2025 | 6.6289 | 7.0643 | +0.4353 | null: no export |
| Full 2025 | 5.0788 | 5.7126 | +0.6338 | 4.5072 |
| 2026 Jan 1–Oct 5 | 7.4177 | 10.6565 | +3.2388 | 4.9053 |
| Full measured range | 6.0899 | 7.8311 | **+1.7411** | 4.7037 |

The load profile is disproportionately concentrated in expensive periods, especially in
the measured 2026 period. This is descriptive, with no assumption that load can shift.
Across the full range, import-weighted price exceeds export-weighted price by
3.1274 c/kWh on this common gross comparison basis. Export-weighted market prices are
not actual export compensation: the export settlement terms/VAT basis must be supplied
independently. Export cannot establish gross PV generation or self-consumption.

## Annual/multi-month import-only thresholds

These use real spot prices and actual unchanged consumption, with a **scenario** fixed
supplier fee of €5.95/month. They assume identical grid/tax/export terms cancel. They do
not apply January's fixed unit price to unsupported dates or declare an annual winner.

| Complete period | Low spot break-even | Primary break-even | Higher break-even |
|---|---:|---:|---:|
| Full 2025 | 5.7567 c/kWh | **6.2126 c/kWh** | 6.6037 c/kWh |
| 2026 January–September | 10.8059 c/kWh | **11.2657 c/kWh** | 11.6582 c/kWh |

These are gross supplier import rates before invoice cent-rounding effects. Different
retailer monthly fees are included analytically. October's partial month is excluded
from these fee-inclusive thresholds. A fixed-only September smoke scenario at explicitly
hypothetical €0.08/kWh plus €5/month yields €56.59 energy + €5 fee + €87.27 grid =
€148.86 before unknown export compensation. Its net total is correctly null.

## Verification and limitations

Verification completed across October 13–14:

- **414 tests passed** in the final full suite, including PostgreSQL integration tests.
  The October 14 rerun initially found the local container runtime stopped; restarting
  the existing runtime/database restored connectivity. No code or data repair was needed.

- 98 synthetic Phase 04 tests cover local-clock/DST boundaries, exact coverage, Decimal
  arithmetic, fees, provenance, source projection, spot import/quarter aggregation, cache
  behavior, export VAT/signs, scenarios, weighted prices, and break-even calculations.
- Ruff format/check and `git diff --check` passed. Dependency lock is unchanged and valid.
- Alembic reports no new upgrade operations; migration up/down testing is not applicable.
- Seven real CLI invocations passed and produced identical output on repeat. Cached raw
  spot files were not fetched again. Missing supplier coverage failed explicitly.
- All source-table row counts and fingerprints were unchanged across the real checks,
  including a fresh October 14 comparison with the original baseline. The September
  grid and January spot comparison acceptance cases passed again after the restart.
- Privacy scan passed for all 17 new files; private derived/cache artifacts are ignored.

Private artifacts include full hourly,
daily, monthly and yearly reports; cached observations and provenance; invoice
comparisons; three January scenarios; annual thresholds; coverage; independent-source
sample verification; and all-table source fingerprints. No usage-point numbers, bank
identifiers, customer details, private time series, or real document files belong in
committed documentation/tests.

The exact next step is to supply the historical supplier contracts/invoices covering
February 2025 onward and the grid tariff sheets effective before April 2026, together
with explicit export settlement terms. That permits longer source-supported fixed-versus-
spot comparisons and complete household totals. No further spot acquisition is needed
for the currently measured period. Future price or load behavior is not inferred.
