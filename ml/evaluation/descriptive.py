"""Descriptive daily weather relationships, separate from predictive features."""

import math

import polars as pl

from ml.features.energy import hours_in_local_day


def describe_energy(frame: pl.DataFrame) -> tuple[dict, pl.DataFrame]:
    local = pl.col("timestamp").dt.convert_time_zone("Europe/Helsinki")
    frame = frame.with_columns(
        local.dt.date().alias("day"),
        local.dt.strftime("%Y-%m").alias("month"),
        local.dt.hour().alias("hour_of_day"),
        (local.dt.weekday() >= 6).alias("is_weekend"),
    )
    daily = (
        frame.group_by("day")
        .agg(
            pl.col("consumption_kwh").sum().alias("daily_consumption_kwh"),
            pl.col("temperature_c").first().alias("daily_mean_temperature_c"),
            pl.col("temperature_c").null_count().alias("missing_temperature"),
            pl.len().alias("hours"),
        )
        .sort("day")
    )
    daily = daily.with_columns(
        pl.Series("expected_hours", [hours_in_local_day(d) for d in daily["day"]])
    )
    daily = daily.filter(
        (pl.col("hours") == pl.col("expected_hours")) & (pl.col("missing_temperature") == 0)
    ).with_columns(
        (17 - pl.col("daily_mean_temperature_c")).clip(lower_bound=0).alias("heating_degree_17")
    )
    monthly = (
        frame.group_by("month")
        .agg(
            pl.col("consumption_kwh").sum(),
            pl.col("solar_export_kwh").sum(),
            pl.len().alias("hours"),
        )
        .join(
            daily.with_columns(pl.col("day").dt.strftime("%Y-%m").alias("month"))
            .group_by("month")
            .agg(pl.col("daily_mean_temperature_c").mean()),
            on="month",
        )
        .sort("month")
    )
    relationships = daily.select(
        pl.corr("daily_mean_temperature_c", "daily_consumption_kwh").alias("temperature_pearson"),
        pl.corr("heating_degree_17", "daily_consumption_kwh").alias("heating_degree_pearson"),
    ).row(0, named=True)
    relationships = {
        name: value if value is not None and math.isfinite(value) else None
        for name, value in relationships.items()
    }
    return {
        "monthly": monthly.to_dicts(),
        "by_hour": frame.group_by("hour_of_day")
        .agg(pl.col("consumption_kwh").mean())
        .sort("hour_of_day")
        .to_dicts(),
        "weekday_weekend": frame.group_by("is_weekend")
        .agg(pl.col("consumption_kwh").mean(), pl.len().alias("hours"))
        .sort("is_weekend")
        .to_dicts(),
        "complete_days": daily.height,
        "daily_relationships": relationships,
        "interpretation": "Descriptive association, not causation; temperature is a daily mean.",
    }, daily
