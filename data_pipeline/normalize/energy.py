"""Format-independent normalization rules; source grammar belongs in ingest."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

import polars as pl

HELSINKI = ZoneInfo("Europe/Helsinki")


class EnergyInputError(ValueError):
    """Sanitized input error: messages must not contain raw source values."""


def normalize_number(value: str | None, *, nullable: bool = False) -> float | None:
    """Accept plain decimal text, with comma or dot; never infer units or zeroes."""
    if value is None or not value.strip():
        if nullable:
            return None
        raise EnergyInputError("missing_energy")
    text = value.strip()
    if not re.fullmatch(r"[+-]?[0-9]+(?:[.,][0-9]+)?", text):
        raise EnergyInputError("malformed_number")
    number = Decimal(text.replace(",", "."))
    if abs(number) >= Decimal("100000000000000"):
        raise EnergyInputError("numeric_out_of_range")
    if number != number.quantize(Decimal("0.000001")):
        raise EnergyInputError("unsupported_numeric_precision")
    result = float(number)
    if Decimal(str(result)) != number:
        raise EnergyInputError("lossy_float_conversion")
    return result


def to_utc(value: datetime) -> datetime:
    """Resolve an already-parsed timestamp; ambiguous naive instants are errors."""
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=HELSINKI, fold=fold).astimezone(UTC)
        if candidate.astimezone(HELSINKI).replace(tzinfo=None) == value:
            candidates.add(candidate)
    if not candidates:
        raise EnergyInputError("nonexistent_local_timestamp")
    if len(candidates) > 1:
        raise EnergyInputError("ambiguous_local_timestamp")
    return candidates.pop()


def parse_timestamp(value: str | None, *, require_offset: bool) -> datetime:
    if value is None or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:[+-]\d{2}:\d{2})?", value
    ):
        raise EnergyInputError("malformed_timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EnergyInputError("malformed_timestamp") from exc
    if require_offset and parsed.tzinfo is None:
        raise EnergyInputError("missing_timestamp_offset")
    if parsed.minute or parsed.second or parsed.microsecond:
        raise EnergyInputError("non_hourly_timestamp")
    utc = to_utc(parsed)
    if parsed.tzinfo is not None:
        # An offset must describe the stated Finnish wall clock, including its DST fold.
        if utc.astimezone(HELSINKI).replace(tzinfo=None) != parsed.replace(tzinfo=None):
            raise EnergyInputError("timestamp_offset_not_helsinki")
    return utc


def normalize_energy(
    frame: pl.DataFrame, *, unit: Literal["kWh", "Wh"], require_offset: bool
) -> pl.DataFrame:
    timestamps = [
        parse_timestamp(value, require_offset=require_offset) for value in frame["timestamp"]
    ]
    columns: dict[str, list[float | None]] = {}
    for name in ("consumption_kwh", "solar_export_kwh", "temperature_c"):
        values = [
            normalize_number(value, nullable=name == "temperature_c") for value in frame[name]
        ]
        if unit == "Wh" and name != "temperature_c":
            # Preserve decimal scale through unit conversion rather than binary division.
            values = [
                float(Decimal(str(value)) / 1000) if value is not None else None for value in values
            ]
        columns[name] = values
    return pl.DataFrame(
        {"timestamp": timestamps, **columns},
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "consumption_kwh": pl.Float64,
            "solar_export_kwh": pl.Float64,
            "temperature_c": pl.Float64,
        },
    )
