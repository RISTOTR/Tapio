"""Strict Sampo card export adapter; external labels are evidence, not confirmations."""

import csv
import io
import json
import re
from hashlib import sha256

import polars as pl

from data_pipeline.ingest.bank_csv import BankInputError
from data_pipeline.normalize.bank import (
    canonical_bank,
    counterparty_fields,
    parse_amount,
    parse_date,
    suggest,
)

SOURCE_TYPE = "sampo_csv"
PARSER_VERSION = "sampo-csv-1"
HEADERS = (
    "transaction_date merchant description amount currency sampo_category "
    "source_account source_transaction_id source_system"
).split()


def canonical_sampo(raw: bytes, source_file: str) -> pl.DataFrame:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != HEADERS:
            raise BankInputError("unsupported_sampo_headers")
        sources = list(reader)
    except (UnicodeError, csv.Error):
        raise BankInputError("invalid_sampo_csv") from None
    if not sources:
        raise BankInputError("empty_source")
    rows = []
    for source in sources:
        if set(source) != set(HEADERS) or any(v is None for v in source.values()):
            raise BankInputError("incomplete_source_row")
        for field in ("source_account", "source_transaction_id", "merchant"):
            if not source[field].strip() or source[field] != source[field].strip():
                raise BankInputError("invalid_sampo_identity")
        if source["source_system"] != "SAMPO" or source["currency"] != "EUR":
            raise BankInputError("unsupported_sampo_currency_or_source")
        if not re.fullmatch(r"[+-]?\d{1,14}\.\d{2}", source["amount"]):
            raise BankInputError("malformed_amount")
        amount = parse_amount(source["amount"].replace(".", ","))
        direction = "incoming" if amount > 0 else "outgoing"
        fields = counterparty_fields(source["merchant"], source["description"])
        rows.append(
            {
                "booking_date": parse_date(source["transaction_date"]),
                "value_date": None,
                "amount": amount,
                "currency": "EUR",
                "direction": direction,
                "raw_counterparty": source["merchant"],
                "reference": None,
                "message": source["description"] or None,
                "transaction_type_code": None,
                "source_file": source_file,
                "source_transaction_id": source["source_transaction_id"],
                "raw_source": json.dumps(source, ensure_ascii=False),
                **fields,
                **suggest(fields["normalized_counterparty"], direction),
            }
        )
    if len({s["source_account"] for s in sources}) != 1:
        raise BankInputError("multiple_sampo_accounts")
    strings = [
        "raw_counterparty",
        "reference",
        "message",
        "transaction_type_code",
        "normalized_counterparty",
        "payment_intermediary",
        "ultimate_recipient",
    ]
    return pl.DataFrame(
        rows,
        schema_overrides={
            "booking_date": pl.Date,
            "value_date": pl.Date,
            "amount": pl.Decimal(20, 6),
            **{k: pl.String for k in strings},
        },
    )


def sampo_account(frame):
    name = json.loads(frame["raw_source"][0])["source_account"]
    return name, sha256(name.encode()).hexdigest()


def adapter(source_type):
    from data_pipeline.ingest.bank_csv import PARSER_VERSION as bank_version
    from data_pipeline.ingest.bank_csv import SOURCE_TYPE as bank_type

    if source_type == bank_type:
        return bank_version, canonical_bank
    if source_type == SOURCE_TYPE:
        return PARSER_VERSION, canonical_sampo
    raise BankInputError("unsupported_import_source")
