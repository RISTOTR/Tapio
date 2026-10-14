"""Cached external adapter. Calculation modules never fetch network data."""

import argparse
import csv
import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .types import ZERO, CostError, D


class SpotPriceProvider(Protocol):
    def fetch(self, start: datetime, end: datetime, refresh: bool = False): ...


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_sahkotin(payload, start, end, retrieved_at):
    """quarter requested; source slots remain quarter slots even in hourly market era."""
    data = json.loads(payload, parse_float=D, parse_int=D)
    observations = []
    seen = set()
    for item in data["prices"]:
        tick = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
        if (
            tick.utcoffset() != timedelta(0)
            or tick.minute not in (0, 15, 30, 45)
            or tick.second
            or tick.microsecond
        ):
            raise CostError("INVALID_SOURCE_QUARTER_TIMESTAMP")
        if tick in seen:
            raise CostError("DUPLICATE_SOURCE_INTERVAL")
        seen.add(tick)
        value = D(item["value"])
        if not value.is_finite():
            raise CostError("NONFINITE_SPOT_PRICE")
        if start <= tick < end:
            observations.append(
                dict(
                    timestamp_utc=tick,
                    interval_end_utc=tick + timedelta(minutes=15),
                    market_area="FI",
                    price_eur_per_mwh=value,
                    price_eur_per_kwh=value / 1000,
                    vat_included=False,
                    source="https://sahkotin.fi/api",
                    retrieved_at=retrieved_at,
                    source_resolution="PT15M",
                )
            )
    return sorted(observations, key=lambda o: o["timestamp_utc"])


def aggregate_hours(observations):
    groups = defaultdict(list)
    for observation in observations:
        groups[observation["timestamp_utc"].replace(minute=0)].append(observation)
    prices = {}
    for tick, group in sorted(groups.items()):
        wanted = {tick + timedelta(minutes=m) for m in (0, 15, 30, 45)}
        if len(group) != 4 or {o["timestamp_utc"] for o in group} != wanted:
            continue
        prices[tick] = sum((o["price_eur_per_mwh"] for o in group), ZERO) / 4
    return prices


class SahkotinProvider:
    def __init__(self, cache):
        self.cache = Path(cache)

    def fetch(self, start, end, refresh=False):
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise CostError("INVALID_FETCH_RANGE")
        params = urlencode({"quarter": "", "start": iso(start), "end": iso(end)})
        url = "https://sahkotin.fi/prices?" + params
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        self.cache.mkdir(parents=True, exist_ok=True)
        raw = self.cache / (key + ".raw.json")
        meta = self.cache / (key + ".request.json")
        if not refresh and not (raw.exists() and meta.exists()):
            for candidate in sorted(self.cache.glob("*.request.json")):
                saved = json.loads(candidate.read_text())
                query = parse_qs(urlparse(saved["url"]).query)
                lower = datetime.fromisoformat(query["start"][0].replace("Z", "+00:00"))
                upper = datetime.fromisoformat(query["end"][0].replace("Z", "+00:00"))
                cached_raw = candidate.with_name(
                    candidate.name.replace(".request.json", ".raw.json")
                )
                if lower <= start and end <= upper and cached_raw.exists():
                    raw, meta = cached_raw, candidate
                    break
        if refresh or not (raw.exists() and meta.exists()):
            request = Request(url, headers={"User-Agent": "TAPIO/0.1 historical personal analysis"})
            for attempt in range(3):
                try:
                    with urlopen(request, timeout=45) as response:
                        payload = response.read()
                    retrieved = datetime.now(UTC).isoformat()
                    normalize_sahkotin(payload, start, end, retrieved)
                    raw.write_bytes(payload)
                    meta.write_text(
                        json.dumps(
                            {
                                "url": url,
                                "retrieved_at": retrieved,
                                "sha256": hashlib.sha256(payload).hexdigest(),
                            },
                            indent=2,
                        )
                    )
                    break
                except (URLError, TimeoutError) as exc:
                    if isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429:
                        raise CostError("SPOT_PROVIDER_HTTP_ERROR") from exc
                    if attempt == 2:
                        raise CostError("SPOT_PROVIDER_UNAVAILABLE") from exc
                    time.sleep(2**attempt)
        metadata = json.loads(meta.read_text())
        payload = raw.read_bytes()
        if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
            raise CostError("SPOT_CACHE_HASH_MISMATCH")
        observations = normalize_sahkotin(payload, start, end, metadata["retrieved_at"])
        return observations, metadata


def export_cache(observations, metadata, path, vat_rate):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prices = aggregate_hours(observations)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp_utc", "market_area", "price_eur_per_mwh"])
        writer.writerows((iso(t), "FI", str(p)) for t, p in prices.items())
    path.with_suffix(".json").write_text(
        json.dumps(
            dict(
                source="https://sahkotin.fi/api",
                market_area="FI",
                currency="EUR",
                resolution="PT1H",
                timezone="UTC",
                price_basis="NET",
                vat_rate=str(vat_rate),
            ),
            indent=2,
        )
    )
    path.with_suffix(".observations.json").write_text(json.dumps(observations, default=str))
    path.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                **metadata,
                "canonical_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_resolution": "PT15M",
                "hourly_conversion": (
                    "Arithmetic mean of exactly four UTC quarters; "
                    "unknown within-hour consumption distribution"
                ),
                "observation_count": len(observations),
                "hour_count": len(prices),
            },
            indent=2,
        )
    )
    return prices


def main():
    from datetime import date

    from .cli import output
    from .types import boundaries, hours

    p = argparse.ArgumentParser(
        description="Fetch/cache net Finnish spot prices; no measurement data sent."
    )
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--cache", type=Path, default=Path("data/processed/energy_cost/spot/raw"))
    p.add_argument(
        "--output", type=Path, default=Path("data/processed/energy_cost/spot/fi_hourly.csv")
    )
    p.add_argument(
        "--vat-rate",
        type=D,
        required=True,
        help="Percentage applied to net prices by retail calculations, e.g. 25.5",
    )
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    start, end = boundaries(a.start, a.end)
    observations, metadata = SahkotinProvider(a.cache).fetch(start, end, a.refresh)
    prices = export_cache(observations, metadata, a.output, a.vat_rate)
    from .coverage import ranges

    output(
        {
            "source": metadata,
            "source_observations": len(observations),
            "source_resolution": "PT15M",
            "hourly_prices": len(prices),
            "first_hour": min(prices) if prices else None,
            "last_hour": max(prices) if prices else None,
            "duplicates": 0,
            "missing_ranges": ranges(set(hours(a.start, a.end)) - set(prices)),
        }
    )


if __name__ == "__main__":
    main()
