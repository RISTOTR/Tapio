"""Exact canonical conversion and conservative weak labels; no tax decisions."""

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import polars as pl

from data_pipeline.ingest.bank_csv import BankInputError, parse_bank_csv

RULE_VERSION = "bank-rules-1"


def name_key(value: str) -> str:
    return " ".join(value.casefold().replace(".", "").split())


# Exact aliases only. Legal suffixes are not removed from arbitrary merchants.
ALIASES = {
    name_key(alias): name
    for name, aliases in {
        "Vattenfall Oy": ["Vattenfall Oy"],
        "Elenia Verkko Oyj": ["Elenia Verkko Oy", "Elenia Verkko Oyj"],
        "Metsänhoitoyhdistys Keski-Suomi": [
            "Metsänhoitoyhdistys Keski-Suomi",
            "Metsänhoitoyhdistys Keski-Suomi ry",
        ],
        "Stora Enso Oyj": ["Stora Enso Oyj"],
        "Verohallinto": ["Verohallinto"],
        "Paytrail Oyj": ["Paytrail Oyj"],
    }.items()
    for alias in aliases
}
CONTEXT_RULES = {
    "Vattenfall Oy": "property",
    "Elenia Verkko Oyj": "property",
    "Metsänhoitoyhdistys Keski-Suomi": "forestry",
    "Stora Enso Oyj": "forestry",
}
CATEGORY_RULES = {
    "Vattenfall Oy": "electricity",
    "Elenia Verkko Oyj": "grid_distribution",
    "Metsänhoitoyhdistys Keski-Suomi": "forestry_service",
    "Verohallinto": "tax",
}


def optional(value: str) -> str | None:
    return value if value.strip() else None


def normalize_name(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    key = name_key(value)
    return ALIASES.get(key, key)


def counterparty_fields(raw: str | None, message: str | None) -> dict:
    key = name_key(raw or "")
    intermediary = "Paytrail Oyj" if re.match(r"^paytrail oyj(?: |$)", key) else None
    normalized = intermediary or normalize_name(raw)
    recipient = None
    if intermediary and message and message.count("Lopullinen saaja:") == 1:
        # One terminal recipient field; reject extra fields and control characters.
        tail = message.split("Lopullinen saaja:", 1)[1].strip()
        if (
            2 <= len(tail) <= 160
            and any(c.isalpha() for c in tail)
            and not any(c in tail for c in "\n\r\t:;|")
        ):
            recipient = normalize_name(tail)
    return {
        "normalized_counterparty": normalized,
        "payment_intermediary": intermediary,
        "ultimate_recipient": recipient,
    }


def suggest(counterparty: str | None, direction: str) -> dict:
    context = CONTEXT_RULES.get(counterparty, "unknown")
    category = CATEGORY_RULES.get(counterparty, "unknown")
    if counterparty == "Stora Enso Oyj" and direction == "incoming":
        category = "timber_income"
    return {
        "category": category,
        "business_context": context,
        "rule_metadata": json.dumps(
            {
                "version": RULE_VERSION,
                "label_kind": "weak_suggestion",
                "context_rule": f"merchant:{counterparty}" if context != "unknown" else None,
                "category_rule": f"merchant_direction:{counterparty}:{direction}"
                if category != "unknown"
                else None,
                "confidence": "high_precision_rule" if context != "unknown" else "unassigned",
            },
            ensure_ascii=False,
        ),
    }


def parse_date(value: str, *, nullable: bool = False):
    if not value.strip() and nullable:
        return None
    # These Finnish exports actually use ISO dates, not dd.mm.yyyy.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BankInputError("malformed_date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise BankInputError("malformed_date") from None


def parse_amount(value: str) -> Decimal:
    if not re.fullmatch(r"[+-]?\d{1,14},\d{2}", value):
        raise BankInputError("malformed_amount")
    amount = Decimal(value.replace(",", "."))
    if amount == 0:
        # Existing enum has no neutral direction; do not invent incoming/outgoing for zero.
        raise BankInputError("zero_amount_unsupported")
    return amount


def canonical_bank(raw: bytes, source_file: str) -> pl.DataFrame:
    from data_pipeline.validate.bank import bank_schema

    parsed = parse_bank_csv(raw)
    rows = []
    for source in parsed.iter_rows(named=True):
        amount = parse_amount(source["Määrä EUROA"])
        direction = "incoming" if amount > 0 else "outgoing"
        archive_id = source["Arkistointitunnus"]
        if not archive_id.strip() or archive_id != archive_id.strip():
            raise BankInputError("missing_or_invalid_archive_id")
        rows.append(
            {
                "booking_date": parse_date(source["Kirjauspäivä"]),
                "value_date": parse_date(source["Arvopäivä"], nullable=True),
                "amount": amount,
                "currency": "EUR",
                "direction": direction,
                "raw_counterparty": optional(source["Saaja/Maksaja"]),
                "reference": optional(source["Viite"].removeprefix("ref=")),
                "message": optional(source["Viesti"]),
                "transaction_type_code": optional(source["Laji"]),
                "source_file": Path(source_file).name,
                "source_transaction_id": archive_id,
                "raw_source": json.dumps(source, ensure_ascii=False),
            }
        )
    frame = pl.DataFrame(
        rows,
        schema_overrides={
            "booking_date": pl.Date,
            "value_date": pl.Date,
            "amount": pl.Decimal(20, 6),
            **{
                k: pl.String
                for k in ["raw_counterparty", "reference", "message", "transaction_type_code"]
            },
        },
    )
    # Validate typed source facts before rule enrichment, and again at the loader boundary.
    bank_schema.validate(frame)
    enriched = []
    for row in frame.iter_rows(named=True):
        fields = counterparty_fields(row["raw_counterparty"], row["message"])
        effective = (
            fields["ultimate_recipient"]
            if fields["payment_intermediary"]
            else fields["normalized_counterparty"]
        )
        enriched.append({**row, **fields, **suggest(effective, row["direction"])})
    return pl.DataFrame(
        enriched,
        schema_overrides={
            **frame.schema,
            **{
                key: pl.String
                for key in ["normalized_counterparty", "payment_intermediary", "ultimate_recipient"]
            },
        },
    )
