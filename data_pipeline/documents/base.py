"""Typed source facts. Financial calculations never use binary floating point."""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(max_digits=20, decimal_places=6, allow_inf_nan=False)]
Quantity = Annotated[Money, Field(ge=0)]
Rate = Annotated[Money, Field(ge=0, le=100)]
NUM = r"-?(?:\d{1,3}(?: \d{3})+|\d+)[,.]\d+"
DATE = r"\d{1,2}\.\d{1,2}\.\d{4}"


class DocumentError(ValueError):
    """Messages are stable privacy-safe error codes only."""


def dec(value):
    return Decimal(value.replace(" ", "").replace("\xa0", "").replace(",", "."))


def day(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def cents(value):
    return value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def require(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    if not match:
        raise DocumentError("unsupported_layout_missing_field")
    return match


def flat(text):
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Line(Facts):
    description: str = Field(min_length=1)
    product_code: str | None = None
    quantity: Quantity | None = None
    unit: str | None = None
    unit_price_eur: Money | None = None
    vat_rate: Rate | None = None
    net_amount_eur: Money | None = None
    vat_amount_eur: Money | None = None
    gross_amount_eur: Money
    page: int = Field(ge=1)
    usage_point: str | None = Field(default=None, pattern=r"^\d{18}$")
    price_basis: Literal["net", "gross"] = "net"
    printed_price_quantum: Quantity | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def arithmetic(self):
        if self.net_amount_eur is not None and self.vat_amount_eur is not None:
            if self.net_amount_eur + self.vat_amount_eur != self.gross_amount_eur:
                raise ValueError("line_total_mismatch")
            if self.vat_rate is not None:
                delta = abs(cents(self.net_amount_eur * self.vat_rate / 100) - self.vat_amount_eur)
                if delta > Decimal(".01"):
                    raise ValueError("line_vat_mismatch")
                if delta:
                    self.warnings.append("vat_rounding_difference_one_cent")
        if self.quantity is not None and self.unit_price_eur is not None:
            target = self.net_amount_eur if self.price_basis == "net" else self.gross_amount_eur
            if target is not None and cents(self.quantity * self.unit_price_eur) != target:
                # Printed utility average rates may have fewer decimals than billing rates.
                if self.price_basis == "net":
                    raise ValueError("line_quantity_price_mismatch")
                quantum = self.printed_price_quantum or Decimal(1).scaleb(
                    self.unit_price_eur.as_tuple().exponent
                )
                tolerance = self.quantity * quantum / 2 + Decimal(".01")
                if abs(self.quantity * self.unit_price_eur - target) > tolerance:
                    raise ValueError("line_printed_rate_outside_rounding_tolerance")
                self.warnings.append("printed_gross_rate_rounding_difference")
        return self


class Energy(Facts):
    usage_point: str = Field(pattern=r"^\d{18}$")
    period_start: date
    period_end: date
    consumption_kwh: Quantity | None = None
    solar_export_kwh: Quantity | None = None
    energy_price_eur_per_kwh: Money | None = None
    base_fee_eur: Money | None = None
    export_price_eur_per_kwh: Money | None = None
    export_margin_eur_per_kwh: Money | None = None
    product: str
    fuse_size: str | None = None
    page: int = Field(ge=1)

    @model_validator(mode="after")
    def dates(self):
        if self.period_end < self.period_start:
            raise ValueError("invalid_period")
        return self


class Bill(Facts):
    vendor: str = Field(min_length=1)
    invoice_number: str = Field(min_length=1)
    invoice_date: date
    due_date: date
    customer: str = Field(min_length=1)
    reference: str | None = None
    order_number: str | None = None
    subtotal_eur: Money
    vat_eur: Money
    total_eur: Money
    lines: list[Line] = Field(min_length=1)
    energy: list[Energy] = Field(default_factory=list)

    @model_validator(mode="after")
    def totals(self):
        if self.due_date < self.invoice_date:
            raise ValueError("due_date_before_invoice")
        if self.subtotal_eur + self.vat_eur != self.total_eur:
            raise ValueError("invoice_total_mismatch")
        if sum((line.gross_amount_eur for line in self.lines), Decimal(0)) != self.total_eur:
            raise ValueError("invoice_lines_mismatch")
        for field, expected in [
            ("net_amount_eur", self.subtotal_eur),
            ("vat_amount_eur", self.vat_eur),
        ]:
            if all(getattr(line, field) is not None for line in self.lines):
                if sum(getattr(line, field) for line in self.lines) != expected:
                    raise ValueError("invoice_net_vat_lines_mismatch")
        return self


class SaleLine(Facts):
    harvest_type: str
    timber_product: str
    estimated_volume_m3: Quantity | None = None
    estimated_price_eur_per_m3: Money | None = None
    estimated_value_eur: Money | None = None
    actual_volume_m3: Quantity
    actual_price_eur_per_m3: Money
    actual_value_eur: Money
    page: int = Field(ge=1)


class Sale(Facts):
    buyer: str
    association: str
    contract_number: str
    sale_date: date
    total_area_ha: Quantity
    estimated_volume_m3: Quantity
    actual_volume_m3: Quantity
    estimated_value_eur: Money
    actual_value_eur: Money
    lines: list[SaleLine] = Field(min_length=1)
    differences: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reconcile(self):
        for field in (
            "estimated_volume_m3",
            "actual_volume_m3",
            "estimated_value_eur",
            "actual_value_eur",
        ):
            self.differences[field] = str(
                sum((getattr(line, field) or Decimal(0) for line in self.lines), Decimal(0))
                - getattr(self, field)
            )
        for i, line in enumerate(self.lines):
            for side in ("estimated", "actual"):
                q, p, v = (
                    getattr(line, f"{side}_{suffix}")
                    for suffix in ("volume_m3", "price_eur_per_m3", "value_eur")
                )
                if q is not None and p is not None and v is not None:
                    delta = cents(q * p) - v
                    if delta:
                        self.differences[f"line_{i + 1}_{side}_value"] = str(delta)
        return self


class ParsedDocument(Facts):
    kind: Literal[
        "ENERGY_INVOICE",
        "GRID_INVOICE",
        "GRID_CONTRACT",
        "FORESTRY_INVOICE",
        "FORESTRY_SALE_SUMMARY",
    ]
    vendor: str
    parser_version: str
    document_date: date
    page_count: int = Field(ge=1)
    bill: Bill | None = None
    sale: Sale | None = None
    contract: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def provenance(self):
        if sum(x is not None for x in (self.bill, self.sale, self.contract)) != 1:
            raise ValueError("document_payload_count")
        lines = self.bill.lines if self.bill else self.sale.lines if self.sale else []
        if any(line.page > self.page_count for line in lines):
            raise ValueError("invalid_source_page")
        return self
