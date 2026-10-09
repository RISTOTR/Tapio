from datetime import UTC, datetime
from pathlib import Path

import pandera as pa
import polars as pl
import pytest

from data_pipeline.ingest.energy_csv import canonical_energy, parse_energy_csv
from data_pipeline.normalize.energy import EnergyInputError
from data_pipeline.validate.energy import energy_schema

SAMPLE = Path(__file__).resolve().parents[3] / "data" / "sample"


@pytest.fixture
def raw() -> bytes:
    return (SAMPLE / "synthetic_energy_hourly.csv").read_bytes()


def test_annual_format_bom_decimal_comma_and_null(raw: bytes) -> None:
    parsed = parse_energy_csv(b"\xef\xbb\xbf" + raw)
    assert parsed.frame.schema["consumption_kwh"] == pl.String
    frame = energy_schema.validate(canonical_energy(b"\xef\xbb\xbf" + raw))
    assert frame["consumption_kwh"].to_list() == [1.125, 2.25]
    assert frame["solar_export_kwh"].to_list() == [0.05, 0.0]
    assert frame["temperature_c"].to_list() == [12.5, None]
    assert frame["timestamp"][0] == datetime(2026, 7, 31, 21, tzinfo=UTC)


def test_day_wh_conversion_and_absent_temperature() -> None:
    frame = energy_schema.validate(
        canonical_energy((SAMPLE / "synthetic_energy_day.csv").read_bytes())
    )
    assert frame["consumption_kwh"].to_list() == [1.2, 2.5]
    assert frame["solar_export_kwh"].to_list() == [0.025, 0.125]
    assert frame["temperature_c"].null_count() == 2
    assert frame["timestamp"][0] == datetime(2026, 10, 4, 21, tzinfo=UTC)


@pytest.mark.parametrize("old,new", [(b"1,125", b"-1,125"), (b"0,050", b"-0,050")])
def test_negative_energy_rejected(raw: bytes, old: bytes, new: bytes) -> None:
    with pytest.raises(pa.errors.SchemaError):
        energy_schema.validate(canonical_energy(raw.replace(old, new)))


@pytest.mark.parametrize(
    "old,new",
    [
        (b"1,125", b""),
        (b"1,125", b"garbage"),
        (b"1,125", b"NaN"),
        (b"2026-08-01", b"2026-02-30"),
        (b"+03:00", b""),
        (b"+03:00", b"+02:00"),
        (b"00:00:00.000", b"00:30:00.000"),
    ],
)
def test_malformed_required_fields_rejected(raw: bytes, old: bytes, new: bytes) -> None:
    with pytest.raises(EnergyInputError):
        canonical_energy(raw.replace(old, new))


def test_duplicate_instants_rejected(raw: bytes) -> None:
    with pytest.raises(pa.errors.SchemaError):
        energy_schema.validate(canonical_energy(raw + raw.splitlines(keepends=True)[1]))


@pytest.mark.parametrize("suffix", [b"\n", b"extra;columns\n", b"\xff"])
def test_invalid_structure_and_encoding(raw: bytes, suffix: bytes) -> None:
    with pytest.raises(EnergyInputError):
        canonical_energy(raw + suffix)


def test_autumn_offsets_and_spring_transition(raw: bytes) -> None:
    header = raw.splitlines()[0] + b"\n"
    autumn = header + (
        b"2025-10-26T03:00:00.000+03:00;1;0;5\n2025-10-26T03:00:00.000+02:00;1;0;5\n"
    )
    frame = energy_schema.validate(canonical_energy(autumn))
    assert (frame["timestamp"][1] - frame["timestamp"][0]).total_seconds() == 3600
    spring = header + (
        b"2026-03-29T02:00:00.000+02:00;1;0;5\n2026-03-29T04:00:00.000+03:00;1;0;5\n"
    )
    frame = energy_schema.validate(canonical_energy(spring))
    assert (frame["timestamp"][1] - frame["timestamp"][0]).total_seconds() == 3600


@pytest.mark.parametrize("stamp", ["2025-10-26T03:00:00", "2026-03-29T03:00:00"])
def test_naive_day_dst_is_rejected(stamp: str) -> None:
    raw = f"Aika;Kulutus Wh;Tuotanto Wh\n{stamp};1000;0\n".encode()
    with pytest.raises(EnergyInputError):
        canonical_energy(raw)
