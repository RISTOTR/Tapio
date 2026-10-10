"""Predeclared winter diagnostics on a single aligned evaluation cohort."""

import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl

from ml.evaluation.metrics import evaluation_rows, regression_metrics
from ml.features.energy import HELSINKI

BASELINES = {"persistence": 1, "daily_naive": 24, "weekly_naive": 168}
BANDS = ["above_0", "minus_5_to_0", "minus_10_to_minus_5", "minus_15_to_minus_10", "below_minus_15"]


def naive_predictions(test: pl.DataFrame) -> dict:
    predictions = {
        name: test[f"consumption_lag_{lag}h"].to_numpy() for name, lag in BASELINES.items()
    }
    if any(not np.isfinite(values).all() for values in predictions.values()):
        raise ValueError("All baselines require complete aligned history")
    return predictions


def metrics_against_baselines(actual, predictions: dict) -> dict:
    baseline_mae = {
        name: regression_metrics(actual, predictions[name], 0)["mae_kwh"] for name in BASELINES
    }
    result = {}
    for name, values in predictions.items():
        metric = regression_metrics(actual, values, baseline_mae["weekly_naive"])
        metric.update(
            {
                f"skill_vs_{base}": regression_metrics(actual, values, mae)["skill_mae"]
                for base, mae in baseline_mae.items()
            }
        )
        result[name] = metric
    return result


def winter_rows(test: pl.DataFrame, predictions: dict) -> pl.DataFrame:
    temp = pl.col("temperature_c")
    consumption = pl.col("consumption_kwh")
    return evaluation_rows(test, predictions).with_columns(
        pl.when(temp > 0)
        .then(pl.lit(BANDS[0]))
        .when(temp >= -5)
        .then(pl.lit(BANDS[1]))
        .when(temp >= -10)
        .then(pl.lit(BANDS[2]))
        .when(temp >= -15)
        .then(pl.lit(BANDS[3]))
        .otherwise(pl.lit(BANDS[4]))
        .alias("temperature_band"),
        (pl.col("timestamp").dt.convert_time_zone("Europe/Helsinki").dt.weekday() >= 6).alias(
            "is_weekend"
        ),
        pl.when(consumption < 1)
        .then(pl.lit("below_1"))
        .when(consumption < 2)
        .then(pl.lit("1_to_2"))
        .when(consumption < 3)
        .then(pl.lit("2_to_3"))
        .otherwise(pl.lit("3_or_above"))
        .alias("consumption_band"),
    )


def winter_diagnostics(test: pl.DataFrame, predictions: dict, output: Path) -> dict:
    metrics = metrics_against_baselines(test["consumption_kwh"].to_numpy(), predictions)
    rows = winter_rows(test, predictions)
    rows.write_csv(output / "predictions.csv")
    groups = {}
    for group in ["hour_of_day", "is_weekend", "temperature_band", "consumption_band"]:
        table = (
            rows.group_by("model", group)
            .agg(
                pl.len().alias("n"),
                pl.col("consumption_kwh").mean().alias("mean_actual_kwh"),
                pl.col("absolute_error").mean().alias("mae_kwh"),
                pl.col("residual").pow(2).mean().sqrt().alias("rmse_kwh"),
            )
            .sort("model", group)
        )
        table.write_csv(output / f"errors_by_{group}.csv")
        groups[group] = table.to_dicts()
    largest = (
        rows.sort(["model", "absolute_error", "timestamp"], descending=[False, True, False])
        .group_by("model", maintain_order=True)
        .head(10)
    )
    largest.write_csv(output / "largest_residuals.csv")
    save_winter_plots(rows, metrics, groups["temperature_band"], output)
    return {
        "metrics": metrics,
        "strongest_baseline": min(BASELINES, key=lambda name: metrics[name]["mae_kwh"]),
        "weather_source_assumption": (
            "Weather source assumed FMI-derived; exact station/publication latency unverified."
        ),
        "property_location": "Viitasaari",
        "grouped_errors": groups,
        "largest_ten_underprediction_counts": {
            name: largest.filter((pl.col("model") == name) & (pl.col("residual") > 0)).height
            for name in predictions
        },
        "plot_week": (
            "2026-01-12 through 2026-01-18 Europe/Helsinki; "
            "fixed before fitting, not selected by errors"
        ),
        "temperature_bands": [
            "T > 0",
            "-5 <= T <= 0",
            "-10 <= T < -5",
            "-15 <= T < -10",
            "T < -15",
        ],
        "consumption_bands_kwh": ["0 <= y < 1", "1 <= y < 2", "2 <= y < 3", "y >= 3"],
    }


def save_winter_plots(rows: pl.DataFrame, metrics: dict, bands: list, output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["timezone"] = "Europe/Helsinki"
    names = ["persistence", "daily_naive", "weekly_naive", "ridge", "hist_gradient_boosting"]
    week = rows.filter(
        (pl.col("timestamp") >= datetime(2026, 1, 12, tzinfo=HELSINKI).astimezone(UTC))
        & (pl.col("timestamp") < datetime(2026, 1, 19, tzinfo=HELSINKI).astimezone(UTC))
    )
    fig, ax = plt.subplots(figsize=(12, 5))
    actual = week.filter(pl.col("model") == "persistence")
    ax.plot(actual["timestamp"].to_list(), actual["consumption_kwh"], label="actual", color="black")
    for name in names:
        part = week.filter(pl.col("model") == name)
        ax.plot(part["timestamp"].to_list(), part["prediction"], label=name, alpha=0.7)
    ax.set(
        title="Fixed week: January 12–18, 2026 (Europe/Helsinki)", ylabel="Hourly consumption (kWh)"
    )
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output / "actual_vs_predicted.png")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 5))
    for name in names:
        ax.hist(
            rows.filter(pl.col("model") == name)["residual"], bins=40, histtype="step", label=name
        )
    ax.set(xlabel="Actual minus predicted (kWh)", ylabel="Hours")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "residual_distribution.png")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 5))
    for name in names:
        lookup = {r["temperature_band"]: r["mae_kwh"] for r in bands if r["model"] == name}
        ax.plot(BANDS, [lookup.get(b, np.nan) for b in BANDS], marker="o", label=name)
    ax.set(ylabel="MAE (kWh)", title="Previous complete local day's mean temperature")
    ax.tick_params(axis="x", labelrotation=15)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "mae_by_temperature_band.png")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.barh(list(metrics), [m["mae_kwh"] for m in metrics.values()])
    ax.set(xlabel="MAE (kWh)", title="Winter: identical 1-hour-ahead test cohort")
    fig.tight_layout()
    fig.savefig(output / "baseline_comparison.png")
    plt.close(fig)
