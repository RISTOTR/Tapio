from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from ml.evaluation.metrics import seasonal_naive
from ml.features.energy import (
    FEATURES,
    HELSINKI,
    HISTORY,
    build_features,
    chronological_split,
    hours_in_local_day,
)


def synthetic(start: datetime | None = None, hours: int = 300) -> pl.DataFrame:
    start = start or datetime(2026, 1, 1, tzinfo=HELSINKI).astimezone(UTC)
    return pl.DataFrame(
        {
            "timestamp": [start + timedelta(hours=i) for i in range(hours)],
            "consumption_kwh": [float(i) for i in range(hours)],
            "solar_export_kwh": [0.0] * hours,
            "temperature_c": [10.0] * hours,
        },
        schema_overrides={"timestamp": pl.Datetime("us", "UTC")},
    )


def test_helsinki_calendar_and_weekend() -> None:
    frame = build_features(synthetic())
    first = frame.row(0, named=True)
    assert (first["hour_of_day"], first["day_of_week"], first["month"], first["is_weekend"]) == (
        0,
        3,
        1,
        0,
    )
    saturday = frame.row(48, named=True)
    assert saturday["day_of_week"] == 5 and saturday["is_weekend"] == 1


@pytest.mark.parametrize(
    "temperature,degree", [(-5.0, 22.0), (10.0, 7.0), (17.0, 0.0), (25.0, 0.0)]
)
def test_heating_degree(temperature: float, degree: float) -> None:
    result = build_features(synthetic().with_columns(pl.lit(temperature).alias("temperature_c")))
    assert result["heating_degree_17"][24] == degree
    assert result["heating_degree_17"][0] is None


@pytest.mark.parametrize("lag", [1, 24, 168])
def test_elapsed_lag(lag: int) -> None:
    frame = build_features(synthetic())
    assert frame[f"consumption_lag_{lag}h"][200] == 200 - lag
    assert frame[f"consumption_lag_{lag}h"][:lag].null_count() == lag


@pytest.mark.parametrize("window", [24, 168])
def test_shifted_rolling(window: int) -> None:
    frame = build_features(synthetic())
    assert (
        frame[f"consumption_rolling_mean_{window}h"][200] == sum(range(200 - window, 200)) / window
    )
    assert frame[f"consumption_rolling_mean_{window}h"][window - 1] is None


def test_current_and_future_targets_do_not_leak() -> None:
    raw = synthetic()
    changed = (
        raw.with_row_index("i")
        .with_columns(
            pl.when(pl.col("i") >= 200)
            .then(1_000_000.0)
            .otherwise(pl.col("consumption_kwh"))
            .alias("consumption_kwh")
        )
        .drop("i")
    )
    before, after = build_features(raw), build_features(changed)
    assert_frame_equal(before.head(201).select(FEATURES), after.head(201).select(FEATURES))
    assert before["consumption_lag_1h"][201] != after["consumption_lag_1h"][201]


def test_current_days_realized_weather_does_not_leak() -> None:
    raw = synthetic()
    current_day = raw["timestamp"][192].astimezone(HELSINKI).date()
    changed = raw.with_columns(
        pl.when(
            pl.col("timestamp").dt.convert_time_zone("Europe/Helsinki").dt.date() >= current_day
        )
        .then(-40.0)
        .otherwise(pl.col("temperature_c"))
        .alias("temperature_c")
    )
    before, after = build_features(raw), build_features(changed)
    assert_frame_equal(before.head(216).select(FEATURES), after.head(216).select(FEATURES))
    assert after["temperature_c"][216] == -40.0
    assert after["observed_daily_mean_temperature_c"][192] == -40.0
    assert after["temperature_c"][192] == 10.0


def test_split_and_explicit_history_loss() -> None:
    frame = build_features(synthetic())
    split = chronological_split(
        frame,
        test_start=frame["timestamp"][240],
        test_end=frame["timestamp"][-1] + timedelta(hours=1),
    )
    assert split.warmup_rows == 168 and split.other_missing_rows == 0
    assert split.train.height == 72 and split.test.height == 60
    assert split.train["timestamp"][-1] < split.test["timestamp"][0]
    assert seasonal_naive(split.test)[0] == 72
    assert split.test["consumption_lag_1h"][1] == 240  # allowed sequential test observation


def test_feature_order_is_chronological() -> None:
    raw = synthetic()
    assert_frame_equal(build_features(raw), build_features(raw.reverse()))


@pytest.mark.parametrize(
    "start", [datetime(2025, 3, 24, tzinfo=HELSINKI), datetime(2025, 10, 20, tzinfo=HELSINKI)]
)
def test_dst_preserves_elapsed_lags_and_local_calendar(start: datetime) -> None:
    frame = build_features(synthetic(start.astimezone(UTC)))
    for i in range(168, frame.height):
        assert frame["consumption_lag_168h"][i] == i - 168
        assert frame["hour_of_day"][i] == frame["timestamp"][i].astimezone(HELSINKI).hour
    transition = datetime(2025, 3, 30).date() if start.month == 3 else datetime(2025, 10, 26).date()
    day = frame.filter(pl.col("local_date") == transition)
    assert day.height == hours_in_local_day(transition) == (23 if start.month == 3 else 25)
    assert day["temperature_c"].null_count() == 0


@pytest.mark.parametrize("problem", ["gap", "duplicate", "naive", "null_target", "inf"])
def test_invalid_series_rejected(problem: str) -> None:
    raw = synthetic()
    if problem == "gap":
        raw = raw.slice(0, 100).vstack(raw.slice(101))
    if problem == "duplicate":
        raw = raw.vstack(raw.head(1))
    if problem == "naive":
        raw = raw.with_columns(pl.col("timestamp").dt.replace_time_zone(None))
    if problem == "null_target":
        raw = raw.with_columns(pl.lit(None, dtype=pl.Float64).alias("consumption_kwh"))
    if problem == "inf":
        raw = raw.with_columns(pl.lit(float("inf")).alias("consumption_kwh"))
    with pytest.raises(ValueError):
        build_features(raw)


def test_missing_weather_is_explicit_not_imputed() -> None:
    raw = (
        synthetic()
        .with_row_index("i")
        .with_columns(
            pl.when(pl.col("i") == 192)
            .then(None)
            .otherwise(pl.col("temperature_c"))
            .alias("temperature_c")
        )
        .drop("i")
    )
    frame = build_features(raw)
    assert frame["temperature_c"][216:240].null_count() == 24
    split = chronological_split(
        frame,
        test_start=frame["timestamp"][240],
        test_end=frame["timestamp"][-1] + timedelta(hours=1),
    )
    assert split.other_missing_rows == 24
    assert split.train.select(HISTORY).null_count().sum_horizontal()[0] == 0


def test_local_split_boundaries_are_converted_to_utc() -> None:
    frame = build_features(synthetic())
    start = frame["timestamp"][240]
    end = frame["timestamp"][-1] + timedelta(hours=1)
    utc_split = chronological_split(frame, test_start=start, test_end=end)
    local_split = chronological_split(
        frame, test_start=start.astimezone(HELSINKI), test_end=end.astimezone(HELSINKI)
    )
    assert_frame_equal(utc_split.train, local_split.train)
    assert_frame_equal(utc_split.test, local_split.test)
