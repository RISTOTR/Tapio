"""Explicit human-approved supplier mapping; no structured PDF parser claim."""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .types import Component, CostError, D, Exact, Frozen, ReviewedSource, Tariff

DEFAULT_PATH = Path("data/interim/energy_cost/accepted_supplier_contracts.json")


class AcceptedSupplier(Frozen):
    authority: Literal["HUMAN_CONFIRMED"]
    meter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supplier: str
    product: str
    pricing_type: Literal["FIXED"]
    contract_type: Literal["FIXED_TERM"]
    start_date: date
    end_date: date  # Inclusive source date; converted only at the projection boundary.
    price_valid_from: date
    price_valid_to: date
    previous_end_date: date
    duration_months: int = Field(gt=0)
    energy_snt_per_kwh: Exact
    monthly_fee_eur: Exact
    vat_percent: Exact
    vat_basis: Literal["INCLUDED"]
    review_path: str
    reviewed_source: ReviewedSource

    @model_validator(mode="after")
    def consistent(self):
        if not (self.previous_end_date < self.start_date <= self.end_date):
            raise ValueError("invalid_contract_boundaries")
        if (self.start_date, self.end_date) != (self.price_valid_from, self.price_valid_to):
            raise ValueError("contract_price_interval_requires_explicit_review")
        if self.monthly_fee_eur < 0 or not D(0) <= self.vat_percent <= D(100):
            raise ValueError("invalid_fee_or_vat")
        return self

    def tariffs(self):
        common = dict(
            provider=self.supplier,
            product=self.product,
            effective_from=self.start_date,
            effective_to=self.end_date + timedelta(days=1),
            price_basis="GROSS",
            vat_rate=self.vat_percent,
            source_document_id=None,
            source_version=self.reviewed_source.mapping_version,
            source_kind="REVIEWED_CONTRACT",
            reviewed_source=self.reviewed_source,
        )
        return [
            Tariff(
                **common,
                component=Component.ENERGY_IMPORT,
                unit="EUR_PER_KWH",
                unit_price=self.energy_snt_per_kwh / D(100),
            ),
            Tariff(
                **common,
                component=Component.SUPPLIER_FIXED_FEE,
                unit="EUR_PER_MONTH",
                unit_price=self.monthly_fee_eur,
            ),
        ]


def verify_review(contract, review):
    """An offer-only field or edited review cannot silently become accepted pricing."""
    fields = (
        "supplier",
        "product",
        "pricing_type",
        "contract_type",
        "start_date",
        "end_date",
        "price_valid_from",
        "price_valid_to",
        "duration_months",
        "energy_snt_per_kwh",
        "monthly_fee_eur",
        "vat_percent",
        "vat_basis",
    )
    rows = review["evidence_matrix"]
    expected = {"new_contract." + f: str(getattr(contract, f)) for f in fields}
    expected["previous_contract.end_date"] = str(contract.previous_end_date)
    for field, value in expected.items():
        matches = [r for r in rows if r["field"] == field]
        if len(matches) != 1:
            raise CostError("REVIEWED_FACT_MISSING_OR_AMBIGUOUS")
        row = matches[0]
        if (
            row["status"] not in ("CONFIRMED", "SUPPORTED_BY_ONE_SOURCE")
            or row["accepted_value"] != value
        ):
            raise CostError("REVIEWED_FACT_NOT_ACCEPTED")
        support = [
            o
            for o in row["observations"]
            if o["value"] == value
            and (
                o["source_kind"] in ("CONFIRMATION", "CONTRACT_PDF")
                or (field == "previous_contract.end_date" and o["source_kind"] == "EXPIRY_NOTICE")
            )
        ]
        if not support:
            raise CostError("REVIEWED_FACT_REQUIRES_AUTHORITATIVE_SOURCE")
    sources = review["sources"]
    if tuple(s["message_id"] for s in sources) != contract.reviewed_source.source_message_ids:
        raise CostError("REVIEWED_MESSAGE_PROVENANCE_MISMATCH")
    pdfs = [
        s
        for s in sources
        if s.get("download_sha256") == contract.reviewed_source.pdf_download_sha256
    ]
    if (
        len(pdfs) != 1
        or pdfs[0].get("document_id") is not None
        or pdfs[0].get("parser_version") is not None
    ):
        raise CostError("REVIEWED_PDF_PROVENANCE_MISMATCH")


def load_reviewed(usage_point, path=DEFAULT_PATH):
    path = Path(path)
    if not path.exists():
        return []
    values = []
    meter_hash = hashlib.sha256(usage_point.encode()).hexdigest()
    for item in json.loads(path.read_text()):
        contract = AcceptedSupplier.model_validate(item)
        if contract.meter_sha256 != meter_hash:
            continue
        payload = Path(contract.review_path).read_bytes()
        if hashlib.sha256(payload).hexdigest() != contract.reviewed_source.review_sha256:
            raise CostError("REVIEWED_SOURCE_HASH_MISMATCH")
        verify_review(contract, json.loads(payload))
        values.extend(contract.tariffs())
    return values
