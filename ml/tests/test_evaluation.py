from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from ml.evaluation.metrics import evaluation_rows, grouped_errors, regression_metrics
from ml.experiments.temperature_consumption import make_models
from ml.features.energy import CALENDAR, FEATURES


def test_metrics_and_skill() -> None:
    metrics = regression_metrics([1, 2, 3], [1, 4, 1], baseline_mae=2)
    assert metrics["mae_kwh"] == pytest.approx(4 / 3)
    assert metrics["rmse_kwh"] == pytest.approx(np.sqrt(8 / 3))
    assert metrics["skill_mae"] == pytest.approx(1 / 3)
    assert regression_metrics([0], [2], 1)["skill_mae"] == -1
    assert regression_metrics([0], [0], 0)["skill_mae"] is None


@pytest.mark.parametrize("actual,predicted", [([], []), ([1], [1, 2]), ([float("nan")], [0])])
def test_invalid_metrics_rejected(actual: list, predicted: list) -> None:
    with pytest.raises(ValueError):
        regression_metrics(actual, predicted, 1)


def test_grouped_metrics_use_aligned_baseline() -> None:
    test = pl.DataFrame(
        {
            "timestamp": [datetime(2026, 7, 31, 21, tzinfo=UTC)] * 2,
            "hour_of_day": [0, 0],
            "temperature_c": [10.0, 10.0],
            "consumption_kwh": [1.0, 3.0],
        }
    )
    rows = evaluation_rows(
        test, {"seasonal_naive": np.array([0.0, 1.0]), "model": np.array([1.0, 2.0])}
    )
    result = grouped_errors(rows, "month").filter(pl.col("model") == "model").row(0, named=True)
    assert result["month"] == "2026-08"
    assert result["skill_mae"] == pytest.approx(1 - 0.5 / 1.5)


def test_preprocessing_fits_only_training_and_hgb_disables_random_validation() -> None:
    models = make_models(FEATURES)
    train = np.zeros((40, len(FEATURES)))
    train[:, FEATURES.index("month")] = 1
    train[:, len(CALENDAR) :] = np.arange(40)[:, None]
    ridge = models["ridge"].fit(train, np.arange(40))
    scaler = ridge.named_steps["preprocess"].named_transformers_["numeric"]
    assert np.allclose(scaler.mean_, 19.5)
    future = train.copy()
    future[:, len(CALENDAR) :] = 100000
    ridge.predict(future)
    assert np.allclose(scaler.mean_, 19.5)
    assert models["hist_gradient_boosting"].early_stopping is False
