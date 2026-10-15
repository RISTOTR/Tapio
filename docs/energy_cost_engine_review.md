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

## Vattenfall contract evidence accepted — 2025-12-01 onward

Verified 15 October 2026. This is a subsequent human-authorized tariff step; the earlier Phase 04 and Phase 05 results above remain historical records.

The user accepted the order confirmation, previous-contract expiry notice and attached contract confirmation (review candidates 4, 5 and 6). The previous contract ends 30 November 2025. The new Vattenfall Oy Ilmasto Mix 24 kk is fixed-term/fixed-price for 24 months, explicitly 1 December 2025–30 November 2027, at 8.24 snt/kWh plus €4.95/month, VAT 25.5% included. Both price-validity boundaries are explicit source facts. Tax/official-charge changes may alter billed amounts; no such change was inferred or dynamically applied.

### Source mapping and provenance

The private human-confirmed mapping in `data/interim/energy_cost/accepted_supplier_contracts.json` supplies the existing ENERGY_IMPORT and SUPPLIER_FIXED_FEE abstractions. These are source configuration, not prices embedded in calculation algorithms. Source dates are inclusive; the internal end boundary is 2027-12-01 exclusive. The private configuration binds to the existing meter using its hash and verifies the reviewed evidence file hash and accepted source observations. Offer-only and current-web observations cannot supply these rates.

Provenance is REVIEWED_CONTRACT: original message IDs, PDF download SHA-256, reviewed-file hash, human authority, mapping version and tax/charge caveat. The PDF has readable text but no supported structured parser, so Document ID is null and the mapping version is explicitly not a parser version. No Document, invoice, reading, transaction or label was changed. Raw identifiers remain private.

### Exact measured overlap and fee policy

New supplier overlap: 2025-12-01 through 2026-10-05, inclusive Helsinki dates, 7,415 expected and present hourly intervals, with exact supplier-energy, supplier-fee and cached-spot coverage. December 2025–September 2026 comprises ten complete calendar months. The contract extends through November 2027, but costs are not reconstructed past the measured end.

October 1–5 is partial: variable energy is calculated, but the existing FULL_CALENDAR_MONTH_ONLY rule leaves the monthly supplier fee and total unallocated. No daily fee proration or October full-month comparison is claimed.

### Monthly supplier-only comparison

Same measured hourly consumption, no load shifting. Primary spot terms (Vattenfall Optimi Pörssisähkö) are unchanged: gross markup €0.005/kWh and gross supplier fee €5.95/month. Cached FI market prices are NET and receive 25.5% VAT once; gross markup/fees receive no additional VAT. Spot market energy and markup remain separate and retain the existing monthly-component cent-rounding policy. Δ = fixed minus spot; percentage denominator is fixed supplier cost. All euro columns are gross.

| Month | kWh | Fixed energy € | Fixed fee € | Fixed total € | Spot market € | Markup € | Spot fee € | Spot total € | Δ € | Δ % | Winner |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2025-12 | 1857.384 | 153.05 | 4.95 | 158.00 | 85.17 | 9.29 | 5.95 | 100.41 | 57.59 | 36.45 | spot |
| 2026-01 | 2558.235 | 210.80 | 4.95 | 215.75 | 374.45 | 12.79 | 5.95 | 393.19 | -177.44 | -82.24 | fixed |
| 2026-02 | 2445.298 | 201.49 | 4.95 | 206.44 | 447.08 | 12.23 | 5.95 | 465.26 | -258.82 | -125.37 | fixed |
| 2026-03 | 1208.138 | 99.55 | 4.95 | 104.50 | 47.24 | 6.04 | 5.95 | 59.23 | 45.27 | 43.32 | spot |
| 2026-04 | 1025.358 | 84.49 | 4.95 | 89.44 | 62.84 | 5.13 | 5.95 | 73.92 | 15.52 | 17.35 | spot |
| 2026-05 | 673.951 | 55.53 | 4.95 | 60.48 | 48.51 | 3.37 | 5.95 | 57.83 | 2.65 | 4.38 | spot |
| 2026-06 | 498.003 | 41.04 | 4.95 | 45.99 | 29.18 | 2.49 | 5.95 | 37.62 | 8.37 | 18.20 | spot |
| 2026-07 | 512.550 | 42.23 | 4.95 | 47.18 | 9.79 | 2.56 | 5.95 | 18.30 | 28.88 | 61.21 | spot |
| 2026-08 | 588.024 | 48.45 | 4.95 | 53.40 | 30.19 | 2.94 | 5.95 | 39.08 | 14.32 | 26.82 | spot |
| 2026-09 | 707.428 | 58.29 | 4.95 | 63.24 | 50.65 | 3.54 | 5.95 | 60.14 | 3.10 | 4.90 | spot |

All averages below are VAT-inclusive market energy only, in snt/kWh; retailer markup and fees are excluded from those averages. Break-even includes the actual fixed monthly fee versus the primary spot fee, before component cent rounding.

| Month | Simple spot | Consumption-weighted spot | Load-timing effect | Break-even fixed rate |
| --- | ---: | ---: | ---: | ---: |
| 2025-12 | 4.5084 | 4.5857 | 0.0774 | 5.1396 |
| 2026-01 | 14.7170 | 14.6372 | -0.0798 | 15.1763 |
| 2026-02 | 17.2179 | 18.2832 | 1.0654 | 18.8241 |
| 2026-03 | 3.4905 | 3.9105 | 0.4200 | 4.4933 |
| 2026-04 | 6.2113 | 6.1287 | -0.0826 | 6.7262 |
| 2026-05 | 6.6363 | 7.1976 | 0.5613 | 7.8460 |
| 2026-06 | 5.6871 | 5.8591 | 0.1720 | 6.5599 |
| 2026-07 | 1.9321 | 1.9106 | -0.0215 | 2.6057 |
| 2026-08 | 5.1779 | 5.1334 | -0.0445 | 5.8035 |
| 2026-09 | 7.1532 | 7.1597 | 0.0065 | 7.8011 |

### Period supplier totals

| Period | Fixed € | Spot € | Fixed minus spot € | Δ % of fixed | Winner | Weighted spot snt/kWh | Break-even fixed snt/kWh |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| December 2025 | 158.00 | 100.41 | 57.59 | 36.45 | spot | 4.5857 | 5.1396 |
| January–September 2026 | 886.42 | 1204.57 | -318.15 | -35.89 | fixed | 10.7657 | 11.3538 |
| December 2025–September 2026 | 1044.42 | 1304.98 | -260.56 | -24.95 | fixed | 9.8151 | 10.3979 |

### April–September 2026 household import-side comparison

Supplier and grid/tax coverage overlap for this full six-month period. These are gross import-side modeled component totals, excluding solar export compensation and unsupported other charges. They are not export-inclusive net household totals. The same actual grid transfer, electricity tax and grid fee apply to both alternatives.

| Component | Fixed € | Primary spot € |
| --- | ---: | ---: |
| Supplier energy (market only for spot) | 330.03 | 231.16 |
| Retailer markup | — | 20.03 |
| Supplier monthly fees | 29.70 | 35.70 |
| Grid transfer | 110.59 | 110.59 |
| Electricity tax | 116.88 | 116.88 |
| Grid fixed fees | 282.60 | 282.60 |
| Import-side total | 869.80 | 796.96 |

Spot is €72.84 cheaper for this overlap (8.37% of the fixed import-side total). The fixed energy tariff already contains its supplier energy price; no separate fixed markup is added.

### Descriptive load timing

| Period | Simple spot snt/kWh | Weighted spot snt/kWh | Load-timing effect snt/kWh |
| --- | ---: | ---: | ---: |
| combined | 7.1846 | 9.8151 | 2.6304 |
| december_2025 | 4.5084 | 4.5857 | 0.0774 |
| household_april_september_2026 | 5.4518 | 5.7712 | 0.3194 |
| january_september_2026 | 7.4886 | 10.7657 | 3.2772 |

The positive combined-period effect means actual consumption was concentrated in more expensive hours. It includes seasonal/monthly consumption weighting as well as within-day timing; it is not a measure of realistically shiftable load. No heating optimization, shifted usage or prospective savings assumption was modeled. Cached quarter-hour prices remain averaged to hourly prices under the existing Phase 04 policy; within-hour consumption distribution is unknown.

### Partial October, gaps and next step

October 1–5 measured consumption: 155.053 kWh; supplier variable energy: €12.78. Supplier fee and total remain null under the partial-month rule.

Supplier prices before December remain supported only for the previously evidenced January 2025 invoice period; February–November 2025 supplier rates remain missing. Grid coverage before April 2026 remains missing. Export settlement terms remain unknown for the new interval and no net export-inclusive total is asserted. No cost reconstruction beyond 5 October 2026 is possible with current readings.

Private output: `data/processed/energy_cost/accepted_vattenfall/analysis.json`, `monthly_supplier_comparison.csv` and `report.md`. The existing analysis files were preserved byte-for-byte. Repeated new calculations produced identical output and all fourteen source-table fingerprints match the previous baseline.

Next recommended evidence step: supply explicit historical export settlement terms to support a net household comparison. Do not infer them from import tariffs. No further Gmail searches or unrelated-domain work were performed.

### Acceptance-step verification

530 tests passed, including 18 new reviewed-supplier tests. Ruff formatting/lint, Git whitespace, dependency lock and Alembic checks passed. Deterministic repeat and post-test fingerprints passed for all 14 source tables. Privacy scanning found no secret/source-identifier matches in 13 versionable files; new tariff/analysis artifacts are private and ignored. No schema migration, source-record writes or new Gmail searches were performed.

## Actual billed export credits — April–August 2026

Label: **ACTUAL_EXPORT_CREDIT_NET_COMPARISON**. Five months only; not a complete 2026 result.

ACTUAL billed export credits are authoritative. Import-side fixed and spot totals are the existing source-supported reconstructions, including the same saved grid transfer, electricity tax and grid fixed fees. No import/grid/tax recalculation was performed. The primary spot scenario retains its existing EUR 0.005/kWh markup and EUR 5.95 monthly fee. The identical actual export credit is subtracted from both sides.

| Month | Import fixed € | Import spot € | Actual credit € | Net fixed € | Net spot € | Fixed − spot € | Difference % of net fixed | Winner |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-04 | 194.77 | 179.25 | 2.15 | 192.62 | 177.10 | 15.52 | 8.06 | spot |
| 2026-05 | 145.86 | 143.21 | 4.03 | 141.83 | 139.18 | 2.65 | 1.87 | spot |
| 2026-06 | 121.37 | 113.00 | 4.54 | 116.83 | 108.46 | 8.37 | 7.16 | spot |
| 2026-07 | 123.39 | 94.51 | 1.05 | 122.34 | 93.46 | 28.88 | 23.61 | spot |
| 2026-08 | 133.90 | 119.58 | 3.44 | 130.46 | 116.14 | 14.32 | 10.98 | spot |
| Apr–Aug total | 719.29 | 649.55 | 15.21 | 704.08 | 634.34 | 69.74 | 9.91 | spot |

Difference = fixed minus spot; positive means spot is cheaper. Percentage denominator is the absolute net fixed total. Monthly percentages are not summed. Applying the same credit preserves the euro difference and winner; the percentage changes because its denominator changes.

### Accepted evidence and provenance

| Billing month | Source alias | Export kWh | Billed margin snt/kWh | Actual credit € |
|---|---|---:|---:|---:|
| 2026-04 | CONT-02, invoice PDF page 5 | 49.65 | 0.30 | 2.15 |
| 2026-05 | CONT-03, invoice PDF page 5 | 107.70 | 0.30 | 4.03 |
| 2026-06 | CONT-04, invoice PDF page 5 | 122.14 | 0.30 | 4.54 |
| 2026-07 | CONT-05, invoice PDF page 5 | 83.37 | 0.30 | 1.05 |
| 2026-08 | CONT-06, invoice PDF page 5 | 74.20 | 0.24 | 3.44 |

Exact invoice references, Gmail message IDs, PDF hashes, review/acceptance hashes and saved import components are private in `data/processed/energy_cost/actual_export_net/accepted_export_credits.json` and `summary.json`. Evidence review: `data/interim/gmail/export_research/invoice_settlement_review.json`. The existing invoice parser rejects the tax-free-sales layout; these are accepted reviewed facts, not fabricated imported Document records.

Property export status is HUMAN_CONFIRMED NON_VAT_LIABLE. April–July retain the contemporaneously billed 0.30 snt/kWh margin; August uses the applicable, billed 0.24 snt/kWh branch. Rates are provenance here; credits are not recomputed from them.

Continuous export tariff and negative-price mechanics remain unresolved. The EUR 0.01–0.05 diagnostic differences have not been normalized or substituted. Missing months remain missing, including September. This billed-credit layer establishes no hourly export formula or hypothetical export contract.

Private outputs: `monthly_net_comparison.csv`, `summary.json`, `report.md`, and accepted evidence mapping under `data/processed/energy_cost/actual_export_net/`.

Recommended next step: use this accepted five-month result; extend net coverage only after independently accepting additional monthly billed credits. Resolve negative-price/settlement mechanics separately before any continuous export tariff.
