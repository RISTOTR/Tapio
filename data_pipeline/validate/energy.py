"""Normalized contract for a single metering point and source grain.

Callers must resolve Europe/Helsinki DST offsets before converting to UTC.
Duplicates are rejected, never silently aggregated or removed.
"""

import pandera.polars as pa
import polars as pl

energy_schema = pa.DataFrameSchema(
    {
        "timestamp": pa.Column(pl.Datetime("us", "UTC"), nullable=False, unique=True),
        "consumption_kwh": pa.Column(
            pl.Float64, checks=[pa.Check.ge(0), pa.Check.lt(float("inf"))], nullable=False
        ),
        "solar_export_kwh": pa.Column(
            pl.Float64, checks=[pa.Check.ge(0), pa.Check.lt(float("inf"))], nullable=False
        ),
        "temperature_c": pa.Column(pl.Float64, checks=pa.Check.in_range(-60, 60), nullable=True),
    },
    strict=True,
    coerce=False,
)
