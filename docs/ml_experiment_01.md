# Experiment 01: hourly consumption

## Question and protocol

Can a simple sklearn model improve one-hour-ahead consumption predictions over a
168-hour seasonal-naive baseline? The property is in **Viitasaari**. Europe/Helsinki
is the Finnish civil **time zone**, not the source of weather observations. The
CSV's temperature column contains daily means but does not identify a station or
weather location; its representativeness for Viitasaari is unverified. No external
Helsinki weather data is used.

Target: consumption_kwh for the UTC interval starting at t. Forecast origin: t,
assuming the completed interval t-1h is available. This is a rolling one-hour-ahead
backtest with one fixed model fit, not a forecast of the entire test horizon made
on July 31. Later test predictions may use already-observed earlier test targets.
Supplier reporting delays are unknown; this availability assumption must be checked
before any operational use.

The sole data source is the existing combined hourly EnergyReading series for
meter <METERING_POINT_CONSUMPTION>. Queries are read-only; no schema or ingestion changes.
The intended source period is January 1, 2025 through October 5, 2026, inclusive,
using local calendar dates. Query bounds and hyperparameters are fixed in code.

## Chronological split

All boundaries below are Europe/Helsinki wall times:

- Raw training period: [2025-01-01 00:00, 2026-08-01 00:00).
- Test: [2026-08-01 00:00, 2026-10-06 00:00).
- Exclude the first 168 hours for complete lag/rolling history.
- Any additional feature-null rows are counted separately, never imputed silently.
- Baseline, both main models and both ablations share the same complete-case rows.
- No shuffle, random split, test-fitted scaling, tuning, or test early stopping.

Feature construction may span the split because all predictors refer to times
strictly before the target interval. Splitting the source first and resetting
lags at the test boundary would incorrectly discard available history.

## Features and leakage protections

| Feature | Definition |
| --- | --- |
| hour_of_day | Helsinki local hour, 0–23 |
| day_of_week | Helsinki local weekday, Monday=0 through Sunday=6 |
| month | Helsinki local month, 1–12 |
| is_weekend | Local Saturday/Sunday indicator |
| temperature_c | Previous complete local day's source daily mean |
| heating_degree_17 | max(0, 17 - the above available daily mean) |
| consumption_lag_1h / 24h / 168h | Observed consumption at that elapsed UTC-hour lag |
| consumption_rolling_mean_24h / 168h | shift(1).rolling_mean(window), full history required |

The input's same-day mean is retained as observed_daily_mean_temperature_c for
inspection, and is explicitly excluded from the feature list. A realized full-day
mean contains future weather at the start of that day. The main weather candidate
therefore uses the *previous completed local day*, assumed available at the next
local midnight. Unknown publication latency remains a limitation. Entire missing
or incomplete previous days are not filled from the future.

Solar export, target-hour consumption, realized same-day weather, current-day
peak/base load, monthly target-containing totals and unshifted rolling statistics
are excluded. Source measurements are not altered, and predictions are not clipped
to zero; negative prediction counts are recorded to expose this model limitation.

UTC continuity is validated before row shifts: gaps, duplicates, nonfinite values
and null targets raise errors. Sorting is explicit. A UTC lag of 168 hours is not
always the same local clock hour across DST; it remains exactly 168 elapsed hours.
Calendar features nevertheless reflect Finnish wall time. A local day can contain
23 or 25 rows; prior-day temperature joins use local dates, not a fixed 24-row shift.

## Models fixed before viewing results

- Seasonal naive: predict consumption_lag_168h.
- Ridge: alpha=1, deterministic SVD solver. sklearn Pipeline with one-hot calendar
  categories (fixed calendar domains) and train-fitted StandardScaler for numeric
  weather/history features. No hyperparameter selection.
- HistGradientBoostingRegressor: learning_rate=0.05, max_iter=200,
  max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1, random_state=42.
  Calendar columns are categorical; other numeric inputs remain unscaled.
  early_stopping=False avoids a random internal validation split.
- Repeat Ridge and HGB without temperature/heating-degree, preserving the same
  evaluation rows. No extra models or feature search.

Library behavior references: [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html),
[HGB](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html),
and [Polars rolling mean](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.rolling_mean.html).

## Descriptive analysis and evaluation

Before fitting, generate monthly consumption/export and mean daily-mean temperature,
hourly mean consumption and weekday/weekend means. For weather relationships,
use one row per complete Helsinki day: daily consumption total versus that day's
source mean temperature and heating degree. Monthly temperature averages give
complete days equal weight. Correlations are descriptive, confounded by season
and routines, and are not causal evidence. The whole-period descriptive output is
not used to tune configurations or choose the split.

MAE and RMSE are in kWh per hourly observation. Skill is
1 - model_MAE / seasonal_naive_MAE on the identical cohort. Positive beats the
baseline; negative is worse. A zero baseline MAE makes relative skill undefined
(null). Evaluate overall and by local month, local hour and available-temperature
bands (<0, [0,10), [10,17), >=17 °C), with counts and each group's baseline.

Record each model's 10 largest absolute residuals, labeled prediction errors,
not anomalies. There are no anomaly labels or evidence of abnormal behavior.

## Reproduce and privacy

```sh
uv sync --locked
uv run python -m ml.experiments.temperature_consumption --metering-point <METERING_POINT_CONSUMPTION>
```

Use the running local PostgreSQL database and configured DATABASE_URL. Each run
creates a fresh timestamped directory under ignored ml/evaluation/output/ with
metrics.json (versions, data/lock fingerprints, split, features, configuration and
metrics), descriptive.json, grouped-error CSVs, prediction rows, largest residuals,
feature spot checks, Ridge coefficients and four matplotlib plots. One numerical
thread and fixed seeds make repeat runs comparable. No trained binaries are saved.
Detailed plots/rows can reveal household behavior and must remain ignored. The
review documents aggregate model metrics and qualitative error patterns only.

## Results on the fixed holdout

There are 15,431 raw hours. Dropping 168 initial history rows leaves 13,679 training
rows and 1,584 test rows; no additional missing-feature rows were removed. The
first usable training hour is January 8, 2025 00:00 local, and the final training
hour is July 31, 2026 23:00 local. Test dates are August 1 through October 5 inclusive.

| Model | MAE (kWh) | RMSE (kWh) | MAE skill |
| --- | ---: | ---: | ---: |
| Seasonal naive, t-168h | 0.337733 | 0.523316 | 0.00% |
| Ridge, delayed daily temperature | 0.217734 | 0.343107 | 35.53% |
| HGB, delayed daily temperature | 0.210108 | 0.328491 | 37.79% |
| Ridge, no temperature | 0.219296 | 0.343611 | 35.07% |
| HGB, no temperature | 0.210053 | 0.327928 | 37.80% |

HGB has the lowest error among the main candidates. The no-temperature HGB variant
is numerically best overall, but its advantage over weather-HGB is only 0.000055
kWh MAE (about 0.026% relative), which is not evidence of a meaningful difference.
Weather improves Ridge MAE by about 0.71% relative to its no-weather variant.
No significance test or uncertainty interval was calculated. No settings were
changed in response to the test results.

The dataset contains 643 complete local days. Descriptive daily Pearson correlation
is -0.933 for temperature versus consumption and +0.945 for heating degree versus
consumption. This strong seasonal association does not establish causal heating
effects, identify the weather location, or prove that weather adds predictive value
beyond recent consumption/calendar. The ablation shows little incremental value
in this particular warm-to-mild holdout.

### Error analysis

| Local test month | Hours | Baseline MAE | Ridge MAE | HGB MAE | HGB skill |
| --- | ---: | ---: | ---: | ---: | ---: |
| August 2026 | 744 | 0.316523 | 0.189009 | 0.178045 | 43.75% |
| September 2026 | 720 | 0.334088 | 0.231721 | 0.225486 | 32.51% |
| October 1–5, 2026 | 120 | 0.491108 | 0.311913 | 0.316633 | 35.53% |

Both main models beat seasonal naive in every month. October has the greatest
absolute error and only five days of support; it must not be treated as a complete
October or winter evaluation. Ridge has slightly lower MAE than HGB in that slice.

By local hour, main-model MAE is greatest at 15:00, 14:00 and 09:00. At 01:00,
seasonal naive beats both main models: baseline MAE 0.126, Ridge 0.140 and HGB
0.151, each based on 66 observations. Overall improvement is therefore not uniform.
Complete hour-by-hour tables remain in ignored generated outputs.

| Previous-day mean band | Test hours | HGB MAE | HGB skill |
| --- | ---: | ---: | ---: |
| <0 °C | 0 | Not evaluated | Not evaluated |
| [0,10) °C | 336 | 0.257566 | 34.44% |
| [10,17) °C | 1,152 | 0.202779 | 37.56% |
| >=17 °C | 96 | 0.131962 | 56.09% |

Cold-weather generalization is untested. The hottest band is small; its better
score does not prove temperature caused the difference. The ten largest absolute
residuals for each fitted model are all underpredictions. The first-week plot also
shows missed sharp peaks. Their causes are unknown; appliance activity, occupancy
or abnormal behavior must not be inferred from residual size alone. Timestamped
largest-error rows are generated privately, not embedded in these docs.

## Limitations and next hypothesis

This is one property and one 66-day holdout; errors are temporally dependent. It is
not a general-purpose forecast model, a validated winter model or an anomaly detector.
Lagged observed consumption is assumed available immediately after each hour.
The prior-day weather mean is assumed available at midnight; actual publication
latency and weather location/representativeness for Viitasaari are unverified.
No future-day weather forecasts are used. Gross household load is not the target:
these are the imported netted grid-consumption measurements, which can be affected
by solar self-consumption even though solar export is excluded as a predictor.

The descriptive analysis includes the full dataset, including the holdout, and the
holdout has now been inspected. Any next model-selection work needs predeclared
chronological validation windows, rather than repeated tuning on this test period.
No confidence intervals, winter holdout, multi-step forecast or deployment test was
performed. Nothing about the model difference warrants an anomaly claim.

Next hypothesis: most one-hour skill may come from recent consumption, and the
incremental value of trustworthy local weather may be larger in winter. The exact
next recommended step is to verify the temperature source's location and publication
timing for **Viitasaari**, before specifying a winter chronological backtest with
an additional last-hour persistence baseline. That next experiment was not started.

See [review and verification](ml_experiment_01_review.md) and the
[aggregate result snapshot](../ml/evaluation/experiment_01_summary.json).
