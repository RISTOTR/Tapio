# Experiment 01 review — 2026-10-09

## Delivered scope

Reusable Polars feature functions, chronological cohort selection, seasonal-naive
baseline, sklearn Ridge and HGB with a no-temperature ablation, descriptive daily
analysis, grouped error analysis and private matplotlib outputs. The CLI queries
PostgreSQL read-only and fits models locally. No migration, ingestion redesign,
model serving, frontend, bank/forestry work, retrieval or LLM functionality.

The house is in Viitasaari. Europe/Helsinki is used only for Finland's calendar/time
zone. The daily temperature's source station/location is unknown; no Helsinki
weather observations were imported. Same-day realized daily means would leak future
weather into early hours, so predictors use the previous complete local day's mean.
Its next-midnight availability remains an explicit, unverified assumption.

## Exact cohort

- Dataset: 15,431 UTC-contiguous hourly rows, local 2025-01-01 00:00 through
  2026-10-05 23:00.
- Raw training period: local 2025-01-01 through 2026-07-31.
- History loss: exactly 168 rows; additional missing-feature loss: 0.
- Usable train: **13,679 rows**, local 2025-01-08 00:00 through 2026-07-31 23:00.
- Test: **1,584 rows**, local 2026-08-01 00:00 through 2026-10-05 23:00.
- UTC usable train: [2025-01-07 22:00, 2026-07-31 21:00).
- UTC test: [2026-07-31 21:00, 2026-10-05 21:00).

All five methods use the same test rows. Later test predictions can use already
observed earlier test consumption, consistent with rolling one-hour-ahead evaluation;
the estimator and preprocessing are never fitted on test data. Calendar features
use local civil time; lags and shifted full-window means use elapsed UTC hours.

## Results

| Model | MAE kWh | RMSE kWh | Skill vs weekly naive |
| --- | ---: | ---: | ---: |
| Seasonal naive | 0.337733 | 0.523316 | 0.00% |
| Ridge | 0.217734 | 0.343107 | 35.53% |
| HistGradientBoosting | 0.210108 | 0.328491 | 37.79% |
| Ridge without weather | 0.219296 | 0.343611 | 35.07% |
| HGB without weather | 0.210053 | 0.327928 | 37.80% |

Best main model: HGB. Best numerical result including ablation: HGB without weather,
by a negligible margin. Weather improves Ridge modestly (about 0.71% relative MAE)
and slightly worsens HGB (about 0.026%). There is no demonstrated substantial
incremental weather benefit in this holdout and no significance claim.

Daily descriptive correlations over 643 complete days are -0.933 with temperature
and +0.945 with heating degree. These are associations, not causal or geographic
validation. Errors are greatest in the short October slice, with no sub-zero weather
in the test cohort. Both models lose to weekly naive at local 01:00. Their ten largest
residuals are underpredictions; the private output labels these as prediction errors.
All predictions are finite; no model generated negative test predictions.

## Verification completed

- **86 pytest tests passed**, including existing PostgreSQL integration tests.
- Added **29 synthetic ML tests**: local calendar, weekend, heating degree, three
  lag horizons, shifted rolling windows, mutation-based leakage tests, explicit
  warm-up and missing-weather handling, sorted output, gaps/duplicates/nonfinite
  targets, both DST transitions, local-to-UTC split boundaries, baseline alignment,
  metrics/skill, group alignment and train-only preprocessing.
- Ruff format --check, Ruff check and git diff --check passed.
- Real PostgreSQL experiment completed twice using fixed settings and one numerical
  thread. All model metrics matched exactly; prediction CSV bytes matched exactly.
- Saved metrics were independently recomputed from generated predictions. Every model
  has 1,584 predictions; every grouped-error table accounts for all test rows; each
  model has exactly ten largest-error rows. All four PNG plots were generated and
  visually inspected.
- Independently checked raw indices 168, 13,846, 13,847 and 15,430 (first feature row,
  final train, first test, final test). Each lag matched the correct earlier UTC
  timestamp; both rolling means matched sums over strictly preceding raw rows;
  local calendar and previous-day temperature matched independent calculations.
- Changed every real target from the test boundary onward to a large sentinel:
  all training predictors and the first test predictors remained identical.
- Unit tests additionally changed current/future daily means and verified that
  same-day predictors did not change. This tests weather leakage separately from
  consumption leakage.
- No schema/model/ingestion files changed. Real database readings were only queried.
- Generated detailed outputs are Git-ignored. Only the reviewed aggregate metadata
  and global model metrics are supplied in experiment_01_summary.json; no model
  binaries, raw target/prediction rows or detailed household plots are candidates
  for version control.

The first real run exposed a Polars timezone-literal mismatch at the split boundary;
boundaries now convert explicitly to UTC, and a regression test covers equivalent
local and UTC cutoffs. Final results above are from successful runs after that fix.

## Reproduce and inspect locally

```sh
uv sync --locked
uv run python -m ml.experiments.temperature_consumption --metering-point 643006966022870423
TAPIO_TEST_DATABASE_URL=postgresql+psycopg://tapio:tapio_local@localhost:5433/tapio uv run pytest -q
```

Dependencies are locked. Result metadata records Python/sklearn/NumPy/Polars versions,
run time, feature list, split, hyperparameters, row counts and hashes of the dataset,
lockfile and ML source. No test-based parameter search or early-stopping validation
was performed. Full plotting and detailed rows remain under ignored output folders.

Reviewed successful output:
`ml/evaluation/output/experiment_01_20261009T081530845244Z/`.
The retained aggregate snapshot is `ml/evaluation/experiment_01_summary.json`.

## Files created

- ml/features/energy.py
- ml/evaluation/descriptive.py
- ml/evaluation/metrics.py
- ml/evaluation/plots.py
- ml/evaluation/experiment_01_summary.json
- ml/experiments/temperature_consumption.py
- ml/tests/test_features.py
- ml/tests/test_evaluation.py
- docs/ml_experiment_01.md
- docs/ml_experiment_01_review.md

Generated and ignored per run: metrics.json, descriptive.json, predictions.csv,
largest_residuals.csv, feature_spot_checks.csv, ridge_coefficients.json,
errors_by_month.csv, errors_by_hour_of_day.csv, errors_by_temperature_band.csv,
actual_vs_predicted.png, residual_distribution.png, mae_by_hour.png,
daily_temperature_consumption.png and a matplotlib font cache. No trained model
binary is saved.

## Files changed

- pyproject.toml and uv.lock: sklearn, matplotlib, NumPy and threadpoolctl;
  ML tests included in pytest discovery.
- .gitignore: all generated ML outputs and matplotlib caches excluded.
- README.md: short experiment command and documentation link.
- docs/architecture.md: offline statistical layer and availability/privacy boundaries.

## Limitations, unverified claims and next step

Verified: deterministic implementation, fixed data split, backtest metrics, artifact
consistency, feature formulas and conditional leakage protections. Not verified:
weather station/location or publication latency, timely arrival of hourly readings,
winter or other-property generalization, statistical significance, appliance causes
of large residuals, or operational forecast performance. No current-day weather is
used predictively. A rolling one-hour-ahead result is not a multi-step forecast.

**Next recommended step:** establish the CSV temperature's weather source and
publication timing for Viitasaari. Then predefine a winter chronological backtest
including a last-hour persistence baseline to test whether weather adds value beyond
recent consumption. No work on that next experiment or another domain was started.
