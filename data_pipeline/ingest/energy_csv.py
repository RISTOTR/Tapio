"""The two inspected Finnish energy export formats; no delimiter/encoding guessing."""

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Literal

import polars as pl

from data_pipeline.normalize.energy import EnergyInputError, normalize_energy

SOURCE_TYPE = "finnish_energy_csv"
PARSER_VERSION = "1.0.0"
ANNUAL_COLUMNS = [
    "Aika",
    "Kulutus (netotettu) kWh",
    "Tuotanto (netotettu) kWh",
    "Vuorokauden keskilämpötila",
]
DAY_COLUMNS = ["Aika", "Kulutus Wh", "Tuotanto Wh"]
CANONICAL_COLUMNS = ["timestamp", "consumption_kwh", "solar_export_kwh", "temperature_c"]


@dataclass(frozen=True)
class ParsedEnergy:
    frame: pl.DataFrame
    unit: Literal["kWh", "Wh"]
    require_offset: bool


def parse_energy_csv(raw: bytes) -> ParsedEnergy:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
        records = list(csv.reader(StringIO(text), delimiter=";", strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise EnergyInputError("invalid_csv_encoding_or_structure") from exc
    if not records or records[0] not in (ANNUAL_COLUMNS, DAY_COLUMNS):
        raise EnergyInputError("unsupported_source_columns")
    columns = records[0]
    if len(records) == 1:
        raise EnergyInputError("empty_source")
    if any(len(row) != len(columns) for row in records[1:]):
        raise EnergyInputError("invalid_csv_row_width")
    try:
        # Read all fields as text: explicit normalization decides what is missing/invalid.
        frame = pl.read_csv(
            StringIO(text), separator=";", infer_schema=False, encoding="utf8", raise_if_empty=True
        )
    except pl.exceptions.PolarsError as exc:
        raise EnergyInputError("invalid_csv_structure") from exc
    if frame.columns != columns or frame.height != len(records) - 1:
        raise EnergyInputError("invalid_csv_structure")
    frame = frame.rename(dict(zip(columns, CANONICAL_COLUMNS, strict=False)))
    annual = columns == ANNUAL_COLUMNS
    if not annual:
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias("temperature_c"))
    return ParsedEnergy(frame, "kWh" if annual else "Wh", annual)


def canonical_energy(raw: bytes) -> pl.DataFrame:
    parsed = parse_energy_csv(raw)
    return normalize_energy(parsed.frame, unit=parsed.unit, require_offset=parsed.require_offset)
