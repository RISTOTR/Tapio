"""Strict local hourly FI spot CSV input. No network or database writes."""

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from .types import ZERO, CostError, D, Exact, Frozen, Reading


class SpotMetadata(Frozen):
    source: str
    market_area: Literal["FI"]
    currency: Literal["EUR"]
    resolution: Literal["PT1H"]
    timezone: Literal["UTC"]
    price_basis: Literal["NET", "GROSS"]
    vat_rate: Exact

    def gross(self, price):
        if not self.source.strip() or not ZERO <= self.vat_rate <= 100:
            raise CostError("INVALID_SPOT_METADATA")
        return price * (1 + self.vat_rate / 100) if self.price_basis == "NET" else price


class SpotPrices:
    def __init__(self, prices, metadata, digest, source_provenance=None):
        metadata.gross(ZERO)
        for tick, value in prices.items():
            if not isinstance(value, D) or not value.is_finite():
                raise CostError("EXACT_FINITE_SPOT_PRICE_REQUIRED")
            if tick.utcoffset() != timedelta(0):
                raise CostError("UTC_SPOT_TIMESTAMP_REQUIRED")
            Reading(timestamp=tick, consumption_kwh=ZERO, solar_export_kwh=ZERO)
        self.prices = MappingProxyType(dict(prices))
        self.metadata = metadata
        self.digest = digest
        self.source_provenance = source_provenance

    def require(self, readings):
        if any(r.timestamp not in self.prices for r in readings):
            raise CostError("MISSING_SPOT_INTERVAL")

    def gross(self, timestamp):
        try:
            return self.metadata.gross(self.prices[timestamp])
        except KeyError as exc:
            raise CostError("MISSING_SPOT_INTERVAL") from exc

    def provenance(self):
        return {
            **self.metadata.model_dump(mode="json"),
            "sha256": self.digest,
            "acquisition": self.source_provenance,
        }


def read_spot(path):
    path = Path(path)
    metadata = SpotMetadata.model_validate_json(path.with_suffix(".json").read_text())
    payload = path.read_bytes()
    prices = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["timestamp_utc", "market_area", "price_eur_per_mwh"]:
            raise CostError("INVALID_SPOT_COLUMNS")
        for row in reader:
            timestamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            if timestamp.utcoffset() != timedelta(0) or row["market_area"] != "FI":
                raise CostError("SPOT_REQUIRES_UTC_AND_FI")
            timestamp = Reading(
                timestamp=timestamp, consumption_kwh=ZERO, solar_export_kwh=ZERO
            ).timestamp
            if timestamp in prices:
                raise CostError("DUPLICATE_SPOT_INTERVAL")
            price = D(row["price_eur_per_mwh"])
            if not price.is_finite():
                raise CostError("NONFINITE_SPOT_PRICE")
            prices[timestamp] = price / 1000
    if not prices:
        raise CostError("EMPTY_SPOT_DATA")
    digest = hashlib.sha256(payload).hexdigest()
    provenance_path = path.with_suffix(".provenance.json")
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else None
    if provenance and provenance.get("canonical_sha256") != digest:
        raise CostError("CANONICAL_SPOT_HASH_MISMATCH")
    return SpotPrices(prices, metadata, digest, provenance)


def weighted_prices(readings, spot):
    spot.require(readings)
    quantity = sum((r.consumption_kwh for r in readings), ZERO)
    export = sum((r.solar_export_kwh for r in readings), ZERO)
    result = {
        "basis": "SOURCE_BASIS_EUR_PER_KWH",
        "simple_average": sum((spot.prices[r.timestamp] for r in readings), ZERO) / len(readings)
        if readings
        else None,
        "consumption_weighted": sum(
            (spot.prices[r.timestamp] * r.consumption_kwh for r in readings), ZERO
        )
        / quantity
        if quantity
        else None,
        "load_timing_effect": (
            sum((spot.prices[r.timestamp] * r.consumption_kwh for r in readings), ZERO) / quantity
            - sum((spot.prices[r.timestamp] for r in readings), ZERO) / len(readings)
        )
        if quantity
        else None,
        "export_weighted": sum(
            (spot.prices[r.timestamp] * r.solar_export_kwh for r in readings), ZERO
        )
        / export
        if export
        else None,
    }

    result["import_minus_export_weighted"] = (
        (result["consumption_weighted"] - result["export_weighted"])
        if quantity and export
        else None
    )
    result["gross_retail_basis"] = {
        key: spot.metadata.gross(value) if value is not None else None
        for key, value in result.items()
        if key != "basis"
    }
    return result
