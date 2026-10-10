# Experiment 02: predefined winter backtest

## Question and fixed protocol

Do Ridge and HGB beat previous-hour, daily and weekly persistence during winter,
and does delayed daily temperature add predictive value? The property is in
**Viitasaari**. Europe/Helsinki specifies the calendar/timezone only.

**Weather source assumed FMI-derived; exact station/publication latency unverified.**
No external Helsinki weather was used. Weather representativeness for Viitasaari
has not been independently verified.

Before fitting, we fixed raw training to local **2025-01-01 00:00 through
2025-12-31 23:00**, and test to **2026-01-01 00:00 through 2026-02-28 23:00**.
Bounds are inclusive hourly interval starts; exclusive test end is March 1 00:00.
The query contains 10,176 hourly readings: 8,760 raw training and 1,416 test.
The first 168 hours are history warm-up; no additional rows were dropped.
Usable training is January 8–December 31, 2025 (**8,592 rows**).
UTC training bounds are [2025-01-07 22:00, 2025-12-31 22:00), and test bounds
are [2025-12-31 22:00, 2026-02-28 22:00).

All seven methods use exactly the same 1,416 test instants. Models fit once on
training only; later predictions may use consumption already observed in earlier
test hours. This is rolling one-hour-ahead evaluation, not a two-month forecast.
Neither split, features nor settings were selected using winter test scores.

## Shared implementation and leakage protections

The existing experiment runner accepts `--winter`; the default remains Experiment 01.
Both experiments use the same feature builder, chronological split and model builder.
Calendar features are local hour, weekday, month and weekend. Weather features are
the previous complete local day's mean and max(0, 17 - that mean). History uses
UTC elapsed-hour lags 1/24/168 and 24/168-hour means shifted by one row before rolling.
Only complete 23/24/25-hour local days provide weather; no same-day realized weather
enters predictors. Immediate availability of completed hourly consumption and
previous-day weather at midnight are assumptions, not verified publication schedules.

Ridge retains alpha=1, solver=svd, fixed-domain one-hot calendar encoding and
train-fitted numeric StandardScaler. HGB retains learning_rate=0.05, max_iter=200,
max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1, random_state=42,
early_stopping=False and categorical calendar columns. Numerical threading is one.
Both ablations remove only temperature_c and heating_degree_17, on identical rows.
No optional interaction, new model family, clipping, tuning or feature selection.

Baselines directly select the three lag columns on the shared test frame. MAE and
RMSE are kWh per hourly observation. Skill against each baseline is
`1 - model_MAE / baseline_MAE`; a zero denominator yields null, not infinity.

## Overall results

| Method | MAE kWh | RMSE kWh | Skill vs persistence | vs daily | vs weekly |
| --- | ---: | ---: | ---: | ---: | ---: |
| Persistence (t-1h) | 0.409451 | 0.538366 | 0.00% | 38.05% | 57.95% |
| Daily naive (t-24h) | 0.660957 | 0.848139 | -61.43% | 0.00% | 32.12% |
| Weekly naive (t-168h) | 0.973720 | 1.205222 | -137.81% | -47.32% | 0.00% |
| Ridge | 0.396414 | 0.499631 | 3.18% | 40.02% | 59.29% |
| HGB | 0.449090 | 0.593236 | -9.68% | 32.05% | 53.88% |
| Ridge without weather | 0.397847 | 0.502640 | 2.83% | 39.81% | 59.14% |
| HGB without weather | 0.443067 | 0.584437 | -8.21% | 32.97% | 54.50% |

**Persistence is the strongest baseline. Ridge beats it by 3.18%; HGB loses by 9.68%.**
Ridge's absolute MAE gain is only 0.013037 kWh per hour. Both fitted families beat
weekly naive, but that weaker comparison overstates the winter one-hour advantage.

Weather lowers Ridge MAE from 0.397847 to 0.396414: 0.001433 kWh, or 0.36% relative.
Weather increases HGB MAE from 0.443067 to 0.449090: 0.006023 kWh, or 1.36% relative.
There is no demonstrated material weather benefit, and no significance claim.
No settings were revised after these results. All predictions are nonnegative.

## Cold-weather analysis

Bands refer to the **previous complete day's mean used by the model**, not an
hourly thermometer reading or target-day realized weather. Exact boundary ownership
is shown below. Daily repetition means the effective weather support is days, not
independent hourly samples.

| Previous-day mean °C | Hours (days) | Mean actual kWh | Persistence MAE | Daily MAE | Weekly MAE | Ridge MAE | HGB MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| T > 0 | 48 (2) | 2.240 | 0.381125 | 0.606396 | 1.262396 | 0.341359 | 0.346415 |
| -5 <= T <= 0 | 144 (6) | 2.596 | 0.377333 | 0.650250 | 1.226708 | 0.371230 | 0.345530 |
| -10 <= T < -5 | 312 (13) | 3.165 | 0.409744 | 0.538929 | 0.879308 | 0.382909 | 0.369099 |
| -15 <= T < -10 | 384 (16) | 3.614 | 0.399969 | 0.617161 | 0.793346 | 0.389921 | 0.395661 |
| T < -15 | 528 (22) | 4.066 | 0.427508 | 0.772795 | 1.065449 | 0.420990 | 0.572793 |

Ridge beats persistence in every temperature band, but only narrowly in the coldest
band. HGB is worse than persistence below -15°C (0.572793 vs 0.427508), whereas
it beats persistence in the other bands. This identifies where much of its winter
weakness occurs; it does not establish a causal explanation. The above-zero group
contains only two days, and the -5 to 0 group six days; avoid generalizing from them.
Ablation metrics for every band are in the safe aggregate JSON and private CSV.

## Other error breakdowns

Each local hour has 59 observations. Ridge's largest hourly MAEs occur at 02:00
(0.478334), 08:00 (0.452944), and 01:00 (0.439808). HGB's largest occur at 10:00
(0.556594), 09:00 (0.526618), and 00:00 (0.497880). Full 24-hour results include
all baselines and both ablations in the private output.

| Group | Hours | Persistence MAE | Ridge MAE | HGB MAE |
| --- | ---: | ---: | ---: | ---: |
| Weekday | 1008 | 0.405238 | 0.391631 | 0.446316 |
| Weekend | 408 | 0.419858 | 0.408232 | 0.455943 |
| Consumption [0,1) kWh | 0 | — | — | — |
| Consumption [1,2) kWh | 41 | 0.281707 | 0.361246 | 0.305269 |
| Consumption [2,3) kWh | 346 | 0.337561 | 0.325008 | 0.292068 |
| Consumption >=3 kWh | 1029 | 0.438713 | 0.421826 | 0.507619 |

Consumption bands are predefined absolute cutoffs, not fitted quantiles. They use
observed targets for retrospective diagnostics only, never model inputs. The lowest
nonempty group is small. Ridge improves weekday and weekend MAE; HGB loses on both.
At >=3 kWh, HGB is worse than persistence, while Ridge retains a modest improvement.

The largest ten absolute residuals per method are retained privately, sorted by
absolute error with timestamp tie-breaking. HGB and its ablation underpredict all
ten; Ridge and its ablation underpredict nine of ten. These are **largest prediction
errors**, not anomalies; no appliance or occupancy cause is inferred.

## Experiment 01 comparison

Experiment 01 originally reported only weekly naive. For a fair comparison we
calculated persistence and daily naive retrospectively on its exact original 1,584
rows, with no refitting or tuning for baseline selection. Their MAE/RMSE are
0.233770/0.402603 and 0.316852/0.510861; weekly remains 0.337733/0.523316.
The shared-runner regression check also reproduces all original ML metrics exactly.
The historical Experiment 01 snapshot is preserved unchanged.

| Holdout | Strongest of three baselines | Ridge MAE | HGB MAE | Best ML skill vs strongest | Weather effect |
| --- | --- | ---: | ---: | ---: | --- |
| Aug 1–Oct 5, 2026 | Persistence: 0.233770 | 0.217734 | 0.210108 | 10.15% (HGB without weather) | Ridge improves 0.71%; HGB worsens 0.026% |
| Jan 1–Feb 28, 2026 | Persistence: 0.409451 | 0.396414 | 0.449090 | 3.18% (Ridge) | Ridge improves 0.36%; HGB worsens 1.36% |

Ridge's advantage over persistence survives both holdouts; HGB's does not.
The two runs have different training lengths, and winter test rows were part of
Experiment 01's later training period. These are separate chronological evaluations,
not independent replications or a controlled causal comparison of seasons. No rows
were pooled for tuning. The stronger baseline narrows Experiment 01's apparent gain
from 37.80% versus weekly naive to 10.15% versus persistence.

## Reproduce, artifacts and privacy

```sh
uv sync --locked
uv run python -m ml.experiments.temperature_consumption --metering-point 643006966022870423 --winter
```

Each run creates an ignored `ml/evaluation/output/experiment_02_<UTC timestamp>/`.
Metadata records Python/sklearn/Polars/NumPy versions, feature lists, split, configs,
row counts and SHA-256 fingerprints of data, ML Python sources and uv.lock.
Two real runs have identical metrics and byte-identical predictions. Historical
code fingerprints naturally differ after adding Experiment 02; Experiment 01's
predictions and metrics are unchanged.

Private outputs: metrics.json, descriptive.json, predictions.csv, largest_residuals.csv,
feature_spot_checks.csv, ridge_coefficients.json, errors_by_month.csv,
errors_by_hour_of_day.csv, errors_by_is_weekend.csv, errors_by_temperature_band.csv,
errors_by_consumption_band.csv, and four matplotlib PNGs: actual_vs_predicted,
residual_distribution, mae_by_temperature_band, baseline_comparison. The plotted
week is January 12–18, fixed before fitting rather than selected by errors; it is
an illustration, not a claim that seven days statistically represent winter.
Font caches and all these artifacts remain ignored. No model binaries are saved.
Only reviewed aggregate metadata/results are in experiment_02_summary.json.

## Limitations and next step

Single property; only about 1.75 years of available source history, with one year
used for this model's training. Temperature is a daily mean repeated hourly; its
source/station and publication timing are unverified. This is one-hour rolling
evaluation, not multi-step forecasting. No appliance-level features, occupancy
labels or external weather forecast. No confidence interval or statistical
significance claim; adjacent errors and repeated daily temperatures are dependent.
Imported netted grid consumption is not gross household load. Observed test results
are not operational forecast validation or evidence of performance at other homes.

**Next recommended step:** verify the temperature source/station's relevance to
Viitasaari and actual publication latency for both temperature and hourly consumption.
Then specify a new untouched chronological evaluation with those availability delays
and persistence as the primary baseline. Do not tune on either now-inspected holdout.
Stop here: no cost engine, anomaly product, ingestion expansion, frontend or serving.

See [verification review](ml_experiment_02_review.md) and
[aggregate snapshot](../ml/evaluation/experiment_02_summary.json).
