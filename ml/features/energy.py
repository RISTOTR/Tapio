"""Reusable one-hour-ahead features: elapsed UTC history, Helsinki calendar."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl

HELSINKI = ZoneInfo("Europe/Helsinki")
CALENDAR = ["hour_of_day", "day_of_week", "month", "is_weekend"]
WEATHER = ["temperature_c", "heating_degree_17"]
HISTORY = [
    "consumption_lag_1h",
    "consumption_lag_24h",
    "consumption_lag_168h",
    "consumption_rolling_mean_24h",
    "consumption_rolling_mean_168h",
]
FEATURES = CALENDAR + WEATHER + HISTORY


def hours_in_local_day(day: date) -> int:
    start = datetime.combine(day, time(), HELSINKI).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), HELSINKI).astimezone(UTC)
    return int((end - start).total_seconds() // 3600)


def validate_hourly(frame: pl.DataFrame) -> pl.DataFrame:
    required = {"timestamp", "consumption_kwh", "temperature_c"}
    if not required.issubset(frame.columns) or frame.is_empty():
        raise ValueError("Nonempty timestamp/consumption/temperature series required")
    if frame.schema["timestamp"] != pl.Datetime("us", "UTC"):
        raise ValueError("Timestamps must be UTC microsecond datetimes")
    result = frame.sort("timestamp")
    timestamps = result["timestamp"]
    if timestamps.null_count() or timestamps.n_unique() != result.height:
        raise ValueError("Null or duplicate timestamps")
    if (timestamps.diff().drop_nulls().dt.total_microseconds() != 3_600_000_000).any():
        raise ValueError("Hourly gaps: row shifts would not represent elapsed-hour lags")
    for column in ("consumption_kwh", "temperature_c"):
        series = result[column]
        if not series.dtype.is_numeric() or (~series.drop_nulls().is_finite()).any():
            raise ValueError(f"Nonfinite or nonnumeric {column}")
    if result["consumption_kwh"].null_count() or (result["consumption_kwh"] < 0).any():
        raise ValueError("Missing/negative target consumption")
    return result


def build_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Keep warm-up nulls explicit; never use the current day's realized weather.

    temperature_c in the returned frame is the PREVIOUS completed Helsinki day's
    mean. The input temperature is retained under an explicitly descriptive name.
    Availability at the next local midnight is an experiment assumption, not a
    verified supplier publication SLA.
    """
    frame = validate_hourly(frame)
    local = pl.col("timestamp").dt.convert_time_zone("Europe/Helsinki")
    frame = frame.with_columns(local.dt.date().alias("local_date"))
    daily = (
        frame.group_by("local_date")
        .agg(
            pl.len().alias("hours"),
            pl.col("temperature_c").null_count().alias("missing"),
            pl.col("temperature_c").drop_nulls().n_unique().alias("unique_temperatures"),
            pl.col("temperature_c").first().alias("temperature_c"),
        )
        .sort("local_date")
    )
    if (daily["unique_temperatures"] > 1).any():
        raise ValueError("Expected a daily mean repeated consistently within each local day")
    expected = pl.Series("expected", [hours_in_local_day(d) for d in daily["local_date"]])
    daily = (
        daily.with_columns(expected)
        .filter((pl.col("hours") == pl.col("expected")) & (pl.col("missing") == 0))
        .select(pl.col("local_date").dt.offset_by("1d").alias("local_date"), "temperature_c")
    )
    frame = (
        frame.rename({"temperature_c": "observed_daily_mean_temperature_c"})
        .join(daily, on="local_date", how="left", validate="m:1")
        .sort("timestamp")
    )
    return frame.with_columns(
        local.dt.hour().alias("hour_of_day"),
        (local.dt.weekday() - 1).alias("day_of_week"),  # Monday=0, Sunday=6
        local.dt.month().alias("month"),
        (local.dt.weekday() >= 6).cast(pl.Int8).alias("is_weekend"),
        (17 - pl.col("temperature_c")).clip(lower_bound=0).alias("heating_degree_17"),
        *[pl.col("consumption_kwh").shift(h).alias(f"consumption_lag_{h}h") for h in (1, 24, 168)],
        *[
            pl.col("consumption_kwh")
            .shift(1)
            .rolling_mean(h, min_samples=h)
            .alias(f"consumption_rolling_mean_{h}h")
            for h in (24, 168)
        ],
    )


@dataclass(frozen=True)
class ChronologicalSplit:
    train: pl.DataFrame
    test: pl.DataFrame
    warmup_rows: int
    other_missing_rows: int


def chronological_split(
    features: pl.DataFrame, *, test_start: datetime, test_end: datetime
) -> ChronologicalSplit:
    """Use one shared complete-case cohort for baseline, models and weather ablation."""
    if test_start.utcoffset() is None or test_end.utcoffset() is None or test_start >= test_end:
        raise ValueError("Ordered, timezone-aware split boundaries required")
    test_start = test_start.astimezone(UTC)
    test_end = test_end.astimezone(UTC)
    features = features.sort("timestamp").filter(pl.col("timestamp") < test_end)
    warmup = features.filter(pl.any_horizontal(pl.col(HISTORY).is_null())).height
    eligible = features.drop_nulls(FEATURES + ["consumption_kwh"])
    train = eligible.filter(pl.col("timestamp") < test_start)
    test = eligible.filter(pl.col("timestamp") >= test_start)
    if train.is_empty() or test.is_empty():
        raise ValueError("Both chronological partitions must contain eligible rows")
    return ChronologicalSplit(train, test, warmup, features.height - eligible.height - warmup)
