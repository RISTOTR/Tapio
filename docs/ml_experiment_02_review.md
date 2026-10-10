# Experiment 02 review — 2026-10-10

Implemented the predefined offline winter backtest. Results and limitations are in
[the experiment report](ml_experiment_02.md). Property: Viitasaari; Europe/Helsinki
is only the timezone. Weather source assumed FMI-derived; exact station/publication
latency unverified.

## Split and results

Raw train: local January 1–December 31, 2025 (8,760 hours). Usable train:
January 8 00:00–December 31 23:00 (8,592). Test: January 1 00:00–February 28
23:00, 2026 (1,416). History warm-up drops 168; other missing-feature drops zero.
The split and January 12–18 plot week were fixed before model fitting.

| Method | MAE kWh | RMSE kWh | Skill vs persistence | vs daily | vs weekly |
| --- | ---: | ---: | ---: | ---: | ---: |
| Persistence (t-1h) | 0.409451 | 0.538366 | 0.00% | 38.05% | 57.95% |
| Daily naive (t-24h) | 0.660957 | 0.848139 | -61.43% | 0.00% | 32.12% |
| Weekly naive (t-168h) | 0.973720 | 1.205222 | -137.81% | -47.32% | 0.00% |
| Ridge | 0.396414 | 0.499631 | 3.18% | 40.02% | 59.29% |
| HGB | 0.449090 | 0.593236 | -9.68% | 32.05% | 53.88% |
| Ridge without weather | 0.397847 | 0.502640 | 2.83% | 39.81% | 59.14% |
| HGB without weather | 0.443067 | 0.584437 | -8.21% | 32.97% | 54.50% |

Persistence is strongest. Ridge gains 3.18%, HGB loses 9.68%. Weather improves
Ridge by 0.36% relative MAE and worsens HGB by 1.36%; no material weather benefit
or statistical significance is established. In the coldest band (528 hours across
22 days), Ridge MAE is 0.420990, persistence 0.427508, HGB 0.572793.
The report includes all cold bands, counts, mean consumption, three baseline MAEs,
local-hour, weekend and consumption-band analysis. Largest errors remain private.

Exp01's retrospectively added same-cohort baselines show persistence was strongest
there too. Best skill versus persistence declines from 10.15% (HGB without weather)
in Aug–Oct to 3.18% (Ridge) in winter. Different training lengths and overlapping
historical use prevent treating this as an independent season-only experiment.

## Inventory

Created:
- ml/evaluation/winter.py: aligned three-baseline metrics, cold/consumption/weekend
  diagnostics and private matplotlib plots.
- ml/tests/test_winter.py: four synthetic tests covering all three lag alignments,
  identical cohorts, winter counts/chronology, weather-only ablation, exact band
  boundaries, skill against every baseline and deterministic fits for both variants.
- ml/evaluation/experiment_02_summary.json: reviewed aggregate results, versions,
  hashes, repeat verification and supplementary original-holdout baseline metrics.
- docs/ml_experiment_02.md and docs/ml_experiment_02_review.md.

Modified for this phase:
- ml/experiments/temperature_consumption.py: optional fixed winter protocol using
  the existing read/query, feature, fit, metadata and artifact machinery.
- ml/evaluation/metrics.py: grouped baseline name parameter; original default retained.
- README.md and docs/architecture.md: winter command and evaluation findings.

Previous uncommitted Experiment 01 and dependency changes were preserved. No source
schema, migrations, ingestion, database readings or model hyperparameters changed.
Detailed per-run artifact inventory is in the experiment report; all outputs remain
under the existing ignored output directory. No prediction rows or binaries staged.

## Verification

- Full pytest suite: **90 passed**, including PostgreSQL integration tests; all
  86 prior tests retained. Existing mutation-based target/weather leakage and both
  DST-transition tests remain green.
- Ruff format --check, Ruff check and git diff --check passed.
- Two real winter runs: exactly equal model/baseline metrics and byte-identical
  prediction CSVs; same dataset and source-code hashes.
- Default Experiment 01 rerun: all original metrics exactly preserved.
- Independently inspected raw indices 168, 8759, 8760, 8761 and 10175: lag values
  and UTC timestamp offsets, both shifted rolling means, local hour and previous
  complete day's weather agree with direct raw calculations.
- Changed all real targets from the winter boundary onward: training predictors
  and first test predictors remain identical. Changed all same-day/future weather:
  predictors through the first test day remain identical.
- Saved prediction metrics independently recomputed; all methods have identical
  1,416 timestamps, each diagnostic grouping accounts for all hours, and each
  method has ten largest-error rows. Four PNGs inspected.
- Git ignore checks confirm private outputs cannot enter an ordinary git add.

Verified winter output directories:
- `ml/evaluation/output/experiment_02_20261010T075813028782Z`
- `ml/evaluation/output/experiment_02_20261010T080141061247Z`

## Limits and exact next step

Single property; ~1.75 years of source history; daily temperature repeated hourly;
unverified source/station/publication timing; rolling one-hour rather than multi-step
forecasting; no appliance features, occupancy labels, external weather forecasts
or statistical significance claim. Modest Ridge gains do not establish deployment
value. HGB's winter loss to persistence is explicitly retained, not tuned away.

Next: verify Viitasaari weather provenance and publication delays for weather and
consumption, then predeclare a new untouched availability-aware evaluation using
persistence as the primary baseline. No further phase has been started.
