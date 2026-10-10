"""Aligned regression metrics, baseline-relative skill and residual diagnostics."""

from typing import TypedDict

import numpy as np
import polars as pl
from numpy.typing import ArrayLike, NDArray


class RegressionMetrics(TypedDict):
    n: int
    mae_kwh: float
    rmse_kwh: float
    skill_mae: float | None


def regression_metrics(
    actual: ArrayLike, predicted: ArrayLike, baseline_mae: float
) -> RegressionMetrics:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.ndim != 1 or predicted.shape != actual.shape or actual.size == 0:
        raise ValueError("Nonempty, aligned one-dimensional arrays required")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics require finite values")
    if not np.isfinite(baseline_mae) or baseline_mae < 0:
        raise ValueError("Invalid baseline MAE")
    residual = actual - predicted
    mae = float(np.mean(np.abs(residual)))
    return {
        "n": len(actual),
        "mae_kwh": mae,
        "rmse_kwh": float(np.sqrt(np.mean(residual**2))),
        "skill_mae": 1 - mae / baseline_mae if baseline_mae > 0 else None,
    }


def seasonal_naive(test: pl.DataFrame) -> NDArray[np.float64]:
    values = test["consumption_lag_168h"].to_numpy()
    if not np.isfinite(values).all():
        raise ValueError("Seasonal-naive history must exist on every evaluated row")
    return values


def evaluation_rows(
    test: pl.DataFrame, predictions: dict[str, NDArray[np.float64]]
) -> pl.DataFrame:
    parts = []
    for name, predicted in predictions.items():
        if len(predicted) != test.height or not np.isfinite(predicted).all():
            raise ValueError("Predictions must align with the test cohort")
        part = test.select("timestamp", "hour_of_day", "temperature_c", "consumption_kwh")
        part = part.with_columns(pl.Series("prediction", predicted), pl.lit(name).alias("model"))
        parts.append(
            part.with_columns(
                (pl.col("consumption_kwh") - pl.col("prediction")).alias("residual"),
                pl.col("timestamp")
                .dt.convert_time_zone("Europe/Helsinki")
                .dt.strftime("%Y-%m")
                .alias("month"),
                pl.when(pl.col("temperature_c") < 0)
                .then(pl.lit("below_0"))
                .when(pl.col("temperature_c") < 10)
                .then(pl.lit("0_to_10"))
                .when(pl.col("temperature_c") < 17)
                .then(pl.lit("10_to_17"))
                .otherwise(pl.lit("17_or_above"))
                .alias("temperature_band"),
            ).with_columns(pl.col("residual").abs().alias("absolute_error"))
        )
    return pl.concat(parts)


def grouped_errors(
    rows: pl.DataFrame, group: str, baseline_name: str = "seasonal_naive"
) -> pl.DataFrame:
    summary = rows.group_by("model", group).agg(
        pl.len().alias("n"),
        pl.col("absolute_error").mean().alias("mae_kwh"),
        pl.col("residual").pow(2).mean().sqrt().alias("rmse_kwh"),
    )
    baseline = summary.filter(pl.col("model") == baseline_name).select(
        group, pl.col("mae_kwh").alias("baseline_mae")
    )
    return (
        summary.join(baseline, on=group, how="left")
        .with_columns(
            pl.when(pl.col("baseline_mae") > 0)
            .then(1 - pl.col("mae_kwh") / pl.col("baseline_mae"))
            .otherwise(None)
            .alias("skill_mae")
        )
        .sort("model", group)
    )
