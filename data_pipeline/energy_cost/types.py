"""Immutable calculation contracts; timestamps denote hourly interval starts."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HELSINKI = ZoneInfo("Europe/Helsinki")
D = Decimal
ZERO = D(0)
HOUR = timedelta(hours=1)
Exact = Annotated[Decimal, Field(allow_inf_nan=False)]


class CostError(ValueError):
    """Stable error code, no private values in exception messages."""


class Component(StrEnum):
    ENERGY_IMPORT = "ENERGY_IMPORT"
    GRID_TRANSFER = "GRID_TRANSFER"
    ELECTRICITY_TAX = "ELECTRICITY_TAX"
    GRID_FIXED_FEE = "GRID_FIXED_FEE"
    SUPPLIER_FIXED_FEE = "SUPPLIER_FIXED_FEE"
    SOLAR_EXPORT_CREDIT = "SOLAR_EXPORT_CREDIT"
    OTHER_BILLED_COMPONENT = "OTHER_BILLED_COMPONENT"


class Window(StrEnum):
    WINTER_DAY = "WINTER_DAY"
    OTHER_TIME = "OTHER_TIME"
    ALL = "ALL"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def no_floats(cls, value):
        def visit(item):
            if isinstance(item, float):
                raise ValueError("binary_float_not_allowed")
            if isinstance(item, dict):
                for v in item.values():
                    visit(v)
            if isinstance(item, (list, tuple)):
                for v in item:
                    visit(v)

        visit(value)
        return value


class Reading(Frozen):
    timestamp: datetime
    consumption_kwh: Annotated[Exact, Field(ge=0)]
    solar_export_kwh: Annotated[Exact, Field(ge=0)]

    @field_validator("timestamp")
    @classmethod
    def utc_hour(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone_required")
        value = value.astimezone(UTC)
        if value.minute or value.second or value.microsecond:
            raise ValueError("hour_start_required")
        return value


class Season(Frozen):
    start_month: int = Field(ge=1, le=12)
    start_day: int = Field(ge=1, le=31)
    end_month: int = Field(ge=1, le=12)
    end_day: int = Field(ge=1, le=31)
    weekdays: tuple[int, ...]
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def valid(self):
        date(2000, self.start_month, self.start_day)
        date(2000, self.end_month, self.end_day)
        if not self.weekdays or any(d not in range(7) for d in self.weekdays):
            raise ValueError("invalid_weekday_rule")
        if self.start_time >= self.end_time:
            raise ValueError("overnight_tariff_not_supported")
        return self


class Tariff(Frozen):
    provider: str = Field(min_length=1)
    product: str = Field(min_length=1)
    effective_from: date
    effective_to: date | None = None  # Exclusive Helsinki calendar boundary.
    component: Component
    window: Window = Window.ALL
    unit: Literal["EUR_PER_KWH", "EUR_PER_MONTH"]
    unit_price: Exact
    price_basis: Literal["NET", "GROSS"]
    vat_rate: Annotated[Exact, Field(ge=0, le=100)]
    source_document_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_kind: Literal["CONTRACT", "INVOICE_PERIOD", "BILLED_EXPORT_AVERAGE"]
    season: Season | None = None
    export_spot_rate: Exact | None = None
    export_margin: Exact | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("empty_tariff_period")
        if self.component == Component.GRID_TRANSFER and self.season is None:
            raise ValueError("grid_schedule_required")
        if self.component == Component.SOLAR_EXPORT_CREDIT and (
            self.export_spot_rate is None or self.export_margin is None
        ):
            raise ValueError("export_components_required")
        if self.component == Component.GRID_TRANSFER and self.window not in (
            Window.WINTER_DAY,
            Window.OTHER_TIME,
        ):
            raise ValueError("grid_window_required")
        fixed = self.component in (Component.GRID_FIXED_FEE, Component.SUPPLIER_FIXED_FEE)
        if fixed != (self.unit == "EUR_PER_MONTH"):
            raise ValueError("component_unit_mismatch")
        return self

    @property
    def gross_rate(self):
        return (
            self.unit_price * (1 + self.vat_rate / 100)
            if self.price_basis == "NET"
            else self.unit_price
        )

    def covers(self, day):
        return self.effective_from <= day and (self.effective_to is None or day < self.effective_to)


def boundaries(start: date, end: date):
    """CLI dates inclusive; internal interval is [local midnight, next midnight)."""
    if end < start:
        raise CostError("INVALID_DATE_RANGE")
    return (
        datetime.combine(start, time(), HELSINKI).astimezone(UTC),
        datetime.combine(end + timedelta(days=1), time(), HELSINKI).astimezone(UTC),
    )


def hours(start, end):
    a, b = boundaries(start, end)
    result = []
    while a < b:
        result.append(a)
        a += HOUR
    return result


def classify_grid_tariff(timestamp, definition: Season):
    if timestamp.tzinfo is None:
        raise CostError("TIMEZONE_REQUIRED")
    local = timestamp.astimezone(HELSINKI)
    md = (local.month, local.day)
    a = (definition.start_month, definition.start_day)
    b = (definition.end_month, definition.end_day)
    winter = a <= md <= b if a <= b else md >= a or md <= b
    active = (
        winter
        and local.weekday() in definition.weekdays
        and definition.start_time <= local.time() < definition.end_time
    )
    return Window.WINTER_DAY if active else Window.OTHER_TIME


def validate_readings(readings, start, end):
    ticks = [r.timestamp for r in readings]
    if len(ticks) != len(set(ticks)):
        raise CostError("DUPLICATE_ENERGY_INTERVAL")
    if set(ticks) != set(hours(start, end)):
        raise CostError("MISSING_OR_EXTRA_ENERGY_INTERVAL")
    return sorted(readings, key=lambda r: r.timestamp)
