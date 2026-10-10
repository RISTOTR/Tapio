"""Experiment 01: fixed chronological, rolling one-hour-ahead consumption prediction."""

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session
from threadpoolctl import threadpool_limits

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import EnergyReading, MeteringPoint
from ml.evaluation.descriptive import describe_energy
from ml.evaluation.metrics import (
    evaluation_rows,
    grouped_errors,
    regression_metrics,
    seasonal_naive,
)
from ml.evaluation.plots import save_plots
from ml.features.energy import (
    CALENDAR,
    FEATURES,
    HELSINKI,
    HISTORY,
    build_features,
    chronological_split,
)

DATA_START = datetime(2025, 1, 1, tzinfo=HELSINKI)
TEST_START = datetime(2026, 8, 1, tzinfo=HELSINKI)
TEST_END = datetime(2026, 10, 6, tzinfo=HELSINKI)  # exclusive
RIDGE_CONFIG = {"alpha": 1.0, "solver": "svd"}
HGB_CONFIG = {
    "learning_rate": 0.05,
    "max_iter": 200,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 42,
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_energy(session: Session, meter: str, *, end: datetime = TEST_END) -> pl.DataFrame:
    statement = (
        select(
            EnergyReading.timestamp,
            EnergyReading.consumption_kwh,
            EnergyReading.solar_export_kwh,
            EnergyReading.temperature_c,
        )
        .join(MeteringPoint)
        .where(
            MeteringPoint.external_code == meter,
            EnergyReading.source_grain == "hourly",
            EnergyReading.timestamp >= DATA_START,
            EnergyReading.timestamp < end,
        )
        .order_by(EnergyReading.timestamp)
    )
    rows = session.execute(statement).all()
    if not rows:
        raise ValueError("No hourly readings in the fixed experiment period")
    return pl.DataFrame(
        {
            "timestamp": [row.timestamp for row in rows],
            "consumption_kwh": [float(row.consumption_kwh) for row in rows],
            "solar_export_kwh": [float(row.solar_export_kwh) for row in rows],
            "temperature_c": [
                float(row.temperature_c) if row.temperature_c is not None else None for row in rows
            ],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "consumption_kwh": pl.Float64,
            "solar_export_kwh": pl.Float64,
            "temperature_c": pl.Float64,
        },
    )


def make_models(features: list[str]) -> dict[str, Pipeline | HistGradientBoostingRegressor]:
    calendar_positions = [features.index(name) for name in CALENDAR]
    numeric_positions = [i for i, name in enumerate(features) if name not in CALENDAR]
    preprocessing = ColumnTransformer(
        [
            (
                "calendar",
                OneHotEncoder(
                    categories=[list(range(24)), list(range(7)), list(range(1, 13)), [0, 1]],
                    handle_unknown="error",
                    sparse_output=False,
                ),
                calendar_positions,
            ),
            ("numeric", StandardScaler(), numeric_positions),
        ]
    )
    return {
        "ridge": Pipeline([("preprocess", preprocessing), ("regressor", Ridge(**RIDGE_CONFIG))]),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            **HGB_CONFIG, categorical_features=calendar_positions
        ),
    }


def _write_json(path: Path, content: object) -> None:
    path.write_text(json.dumps(content, indent=2, default=str, allow_nan=False) + "\n")


def run_experiment(raw: pl.DataFrame, output: Path, *, winter: bool = False) -> dict:
    """No test-set fit, tuning, early-stopping selection, or prediction clipping."""
    test_start = datetime(2026, 1, 1, tzinfo=HELSINKI) if winter else TEST_START
    test_end = datetime(2026, 3, 1, tzinfo=HELSINKI) if winter else TEST_END
    raw = raw.filter(
        (pl.col("timestamp") >= DATA_START.astimezone(UTC))
        & (pl.col("timestamp") < test_end.astimezone(UTC))
    )
    features = build_features(raw)
    split = chronological_split(features, test_start=test_start, test_end=test_end)
    # Descriptive outputs are produced before fitting; configurations above are fixed.
    descriptions, daily = describe_energy(raw)
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "descriptive.json", descriptions)
    train, test = split.train, split.test
    y_train = train["consumption_kwh"].to_numpy()
    y_test = test["consumption_kwh"].to_numpy()
    predictions = {"seasonal_naive": seasonal_naive(test)}
    if winter:
        from ml.evaluation.winter import naive_predictions

        predictions = naive_predictions(test)
    coefficients = {}
    with threadpool_limits(limits=1):
        for suffix, selected in [("", FEATURES), ("_without_temperature", CALENDAR + HISTORY)]:
            x_train = train.select(selected).to_numpy()
            x_test = test.select(selected).to_numpy()
            for name, model in make_models(selected).items():
                model.fit(x_train, y_train)
                predictions[name + suffix] = model.predict(x_test)
                if name == "ridge":
                    coefficients[name + suffix] = dict(
                        zip(
                            model.named_steps["preprocess"].get_feature_names_out(),
                            model.named_steps["regressor"].coef_.tolist(),
                            strict=True,
                        )
                    )
    baseline_mae = float(
        np.abs(y_test - predictions["weekly_naive" if winter else "seasonal_naive"]).mean()
    )
    metrics = {
        name: regression_metrics(y_test, predicted, baseline_mae)
        for name, predicted in predictions.items()
    }
    rows = evaluation_rows(test, predictions)
    error_tables = {
        group: grouped_errors(rows, group, "weekly_naive" if winter else "seasonal_naive")
        for group in ["month", "hour_of_day", "temperature_band"]
    }
    for group, table in error_tables.items():
        table.write_csv(output / f"errors_by_{group}.csv")
    rows.write_csv(output / "predictions.csv")
    rows.sort(["model", "absolute_error", "timestamp"], descending=[False, True, False]).group_by(
        "model", maintain_order=True
    ).head(10).write_csv(output / "largest_residuals.csv")
    # Private spot-check rows at first eligible hour, split, and last test hour.
    features.filter(
        pl.col("timestamp").is_in(
            [
                train["timestamp"][0],
                train["timestamp"][-1],
                test["timestamp"][0],
                test["timestamp"][-1],
            ]
        )
    ).write_csv(output / "feature_spot_checks.csv")
    _write_json(output / "ridge_coefficients.json", coefficients)
    summary = {
        "experiment": "02_winter" if winter else "01_temperature_consumption",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol": "rolling_one_hour_ahead_fixed_fit",
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "polars_version": pl.__version__,
        "numpy_version": np.__version__,
        "dataset_sha256": hashlib.sha256(raw.write_csv().encode()).hexdigest(),
        "source_code_sha256": hashlib.sha256(
            b"".join(
                path.relative_to(PROJECT_ROOT).as_posix().encode() + path.read_bytes()
                for path in sorted((PROJECT_ROOT / "ml").rglob("*.py"))
                if "output" not in path.relative_to(PROJECT_ROOT).parts
            )
        ).hexdigest(),
        "uv_lock_sha256": hashlib.sha256((PROJECT_ROOT / "uv.lock").read_bytes()).hexdigest(),
        "period": {
            "start_inclusive": DATA_START.isoformat(),
            "test_start_inclusive": test_start.isoformat(),
            "end_exclusive": test_end.isoformat(),
        },
        "rows": {
            "raw": raw.height,
            "warmup_dropped": split.warmup_rows,
            "other_missing_dropped": split.other_missing_rows,
            "train": train.height,
            "test": test.height,
        },
        "actual_bounds_utc": {
            "train_first": train["timestamp"][0],
            "train_last": train["timestamp"][-1],
            "test_first": test["timestamp"][0],
            "test_last": test["timestamp"][-1],
        },
        "features": FEATURES,
        "ablation_features": CALENDAR + HISTORY,
        "weather_policy": "Previous complete local day mean; assumed available next midnight.",
        "weather_granularity": "Daily mean, never hourly weather or current-day realized mean.",
        "configs": {
            "ridge": RIDGE_CONFIG,
            "hist_gradient_boosting": HGB_CONFIG,
            "threads": 1,
            "numeric_preprocessing": "Ridge: train-fitted StandardScaler; HGB: unscaled",
            "calendar_preprocessing": "Ridge: one-hot fixed calendar domains; HGB: categorical",
        },
        "metrics": metrics,
        "negative_prediction_counts": {
            name: int((pred < 0).sum()) for name, pred in predictions.items()
        },
        "best_test_mae_model": min(metrics, key=lambda name: metrics[name]["mae_kwh"]),
        "interpretation": "Best on this test period only; no test-set tuning.",
    }
    if winter:
        from ml.evaluation.winter import winter_diagnostics

        summary.update(winter_diagnostics(test, predictions, output))
    else:
        save_plots(rows, daily, error_tables["hour_of_day"], output)
    _write_json(output / "metrics.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metering-point", required=True)
    parser.add_argument("--winter", action="store_true", help="Fixed Experiment 02 protocol")
    args = parser.parse_args()
    output = (
        PROJECT_ROOT
        / "ml/evaluation/output"
        / datetime.now(UTC).strftime(
            ("experiment_02_" if args.winter else "experiment_01_") + "%Y%m%dT%H%M%S%fZ"
        )
    )
    with SessionLocal() as session:
        raw = read_energy(
            session,
            args.metering_point,
            end=datetime(2026, 3, 1, tzinfo=HELSINKI) if args.winter else TEST_END,
        )
    summary = run_experiment(raw, output, winter=args.winter)
    print(
        json.dumps(
            {"output": str(output), "rows": summary["rows"], "metrics": summary["metrics"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
