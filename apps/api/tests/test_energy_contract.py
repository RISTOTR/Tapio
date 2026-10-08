from datetime import UTC, datetime

import pandera as pa
import polars as pl
import pytest

from data_pipeline.validate.energy import energy_schema


def frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [datetime(2026, 1, 1, tzinfo=UTC)],
            "consumption_kwh": [1.25],
            "solar_export_kwh": [0.0],
            "temperature_c": [-12.0],
        }
    )


def test_valid_energy_and_missing_temperature() -> None:
    assert energy_schema.validate(frame()).equals(frame())
    energy_schema.validate(
        frame().with_columns(pl.lit(None, dtype=pl.Float64).alias("temperature_c"))
    )


@pytest.mark.parametrize(
    "column,value",
    [
        ("consumption_kwh", -1.0),
        ("solar_export_kwh", -0.01),
        ("temperature_c", -61.0),
        ("temperature_c", 61.0),
        ("consumption_kwh", float("inf")),
        ("solar_export_kwh", float("nan")),
    ],
)
def test_invalid_measurements(column: str, value: float) -> None:
    with pytest.raises(pa.errors.SchemaError):
        energy_schema.validate(frame().with_columns(pl.lit(value).alias(column)))


def test_duplicate_timestamps_rejected() -> None:
    with pytest.raises(pa.errors.SchemaError):
        energy_schema.validate(pl.concat([frame(), frame()]))


@pytest.mark.parametrize("timestamp", [None, "not a date", datetime(2026, 1, 1)])
def test_invalid_or_naive_timestamps_rejected(timestamp: object) -> None:
    with pytest.raises(pa.errors.SchemaError):
        energy_schema.validate(frame().with_columns(pl.lit(timestamp).alias("timestamp")))


def test_missing_required_field() -> None:
    with pytest.raises(pa.errors.SchemaError):
        energy_schema.validate(frame().drop("solar_export_kwh"))
