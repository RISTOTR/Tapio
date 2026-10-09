from datetime import UTC, datetime

import pytest

from data_pipeline.normalize.energy import EnergyInputError, normalize_number, to_utc


def test_decimal_comma_and_null() -> None:
    assert normalize_number("1,234567") == 1.234567
    assert normalize_number("0") == 0.0
    assert normalize_number("", nullable=True) is None
    assert normalize_number(None, nullable=True) is None
    assert normalize_number("-1,2") == -1.2  # Pandera rejects negative energy later.


@pytest.mark.parametrize("value", [None, "", "NaN", "inf", "1,2.3", "1 kWh", "0.0000001"])
def test_invalid_numbers_not_coerced(value: str | None) -> None:
    with pytest.raises(EnergyInputError):
        normalize_number(value)


@pytest.mark.parametrize("month,utc_hour", [(1, 10), (8, 9)])
def test_helsinki_conversion(month: int, utc_hour: int) -> None:
    assert to_utc(datetime(2026, month, 1, 12)) == datetime(2026, month, 1, utc_hour, tzinfo=UTC)


@pytest.mark.parametrize(
    "value,code",
    [(datetime(2026, 3, 29, 3), "nonexistent"), (datetime(2025, 10, 26, 3), "ambiguous")],
)
def test_naive_dst_requires_evidence(value: datetime, code: str) -> None:
    with pytest.raises(EnergyInputError, match=code):
        to_utc(value)


def test_explicit_offsets_distinguish_autumn_hours() -> None:
    first = to_utc(datetime.fromisoformat("2025-10-26T03:00:00+03:00"))
    second = to_utc(datetime.fromisoformat("2025-10-26T03:00:00+02:00"))
    assert first == datetime(2025, 10, 26, 0, tzinfo=UTC)
    assert second == datetime(2025, 10, 26, 1, tzinfo=UTC)
