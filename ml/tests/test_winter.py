from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal
from threadpoolctl import threadpool_limits

from ml.evaluation.winter import (
    BANDS,
    BASELINES,
    metrics_against_baselines,
    naive_predictions,
    winter_rows,
)
from ml.experiments.temperature_consumption import make_models
from ml.features.energy import (
    CALENDAR,
    FEATURES,
    HELSINKI,
    HISTORY,
    WEATHER,
    build_features,
    chronological_split,
)
from ml.tests.test_features import synthetic


def test_winter_split_and_all_baseline_alignment():
    raw = synthetic(datetime(2025, 1, 1, tzinfo=HELSINKI).astimezone(UTC), 10176)
    frame = build_features(raw)
    split = chronological_split(
        frame,
        test_start=datetime(2026, 1, 1, tzinfo=HELSINKI),
        test_end=datetime(2026, 3, 1, tzinfo=HELSINKI),
    )
    assert (split.train.height, split.test.height, split.warmup_rows) == (8592, 1416, 168)
    assert split.train["timestamp"][-1] < split.test["timestamp"][0]
    predictions = naive_predictions(split.test)
    for name, lag in BASELINES.items():
        np.testing.assert_array_equal(predictions[name], np.arange(8760 - lag, 10176 - lag))
    rows = winter_rows(split.test, predictions)
    for name in BASELINES:
        assert_frame_equal(
            rows.filter(pl.col("model") == name).select("timestamp"), split.test.select("timestamp")
        )


def test_skills_against_every_baseline():
    predictions = {
        "persistence": np.array([0.0, 0.0]),
        "daily_naive": np.array([1.0, 1.0]),
        "weekly_naive": np.array([0.0, 1.0]),
        "model": np.array([1.0, 2.0]),
    }
    result = metrics_against_baselines([2.0, 2.0], predictions)["model"]
    assert result["skill_vs_persistence"] == 0.75
    assert result["skill_vs_daily_naive"] == 0.5
    assert result["skill_vs_weekly_naive"] == pytest.approx(2 / 3)


def test_band_boundaries_and_ablation():
    frame = (
        build_features(synthetic())
        .tail(7)
        .with_columns(pl.Series("temperature_c", [1.0, 0.0, -5.0, -5.1, -10.0, -15.0, -15.1]))
    )
    rows = winter_rows(frame, {"persistence": np.zeros(7)})
    assert rows["temperature_band"].to_list() == [BANDS[i] for i in [0, 1, 1, 2, 2, 3, 4]]
    assert [f for f in FEATURES if f not in WEATHER] == CALENDAR + HISTORY


def test_fixed_models_repeat_deterministically():
    frame = build_features(synthetic(hours=400)).drop_nulls(FEATURES)
    with threadpool_limits(limits=1):
        for selected in [FEATURES, CALENDAR + HISTORY]:
            a, b = make_models(selected), make_models(selected)
            train, test = frame.head(180), frame.tail(52)
            for name in a:
                results = [
                    models[name]
                    .fit(train.select(selected).to_numpy(), train["consumption_kwh"].to_numpy())
                    .predict(test.select(selected).to_numpy())
                    for models in [a, b]
                ]
                np.testing.assert_array_equal(*results)
