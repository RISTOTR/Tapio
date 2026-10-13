"""Compact taxonomy, private projections and strict human CSV validation."""

import csv
import io
import re
from uuid import UUID

from apps.api.app.domain.enums import LabelReviewStatus, TransactionCategory

CATEGORIES = tuple(c.value for c in TransactionCategory)
CONTEXTS = ("PERSONAL", "PROPERTY", "FORESTRY", "UNKNOWN")
STATUSES = tuple(s.value for s in LabelReviewStatus)
REVIEW_FIELDS = ["reviewed_category", "reviewed_business_context", "review_status", "review_notes"]
FACT_FIELDS = [
    "transaction_id",
    "booking_date",
    "amount",
    "direction",
    "normalized_counterparty",
    "ultimate_recipient",
    "message",
    "transaction_type_code",
]
SNAPSHOT_FIELDS = ["suggested_category", "suggested_business_context"]
QUEUE_COLUMNS = FACT_FIELDS + SNAPSHOT_FIELDS + ["sampling_reasons", "review_hint"] + REVIEW_FIELDS


class ReviewError(ValueError):
    """Sanitized validation code plus CSV line; no private field contents."""


def safe_text(value: str | None, secrets: list[str] = ()) -> str:
    text = value or ""
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret and len(secret) >= 6:
            # Account numbers may appear spaced in free text.
            pattern = r"\s*".join(re.escape(c) for c in secret.replace(" ", ""))
            text = re.sub(pattern, "[REDACTED]", text, flags=re.I)
    text = re.sub(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", "[REDACTED IBAN]", text, flags=re.I)
    # Keep spreadsheet review text from becoming a formula. Amount stays a numeric field.
    if text.lstrip().startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text


def review_facts(transaction, extra_secrets=()) -> dict[str, str]:
    raw = transaction.raw_source or {}
    secrets = [
        raw.get(key, "")
        for key in [
            "Saajan tilinumero",
            "Saajan pankin BIC",
            "Arkistointitunnus",
        ]
    ]
    return {
        "transaction_id": str(transaction.id),
        "booking_date": transaction.booking_date.isoformat(),
        "amount": format(transaction.amount, ".6f"),
        "direction": transaction.direction.value.upper(),
        **{
            key: safe_text(getattr(transaction, key), [*secrets, *extra_secrets])
            for key in [
                "normalized_counterparty",
                "ultimate_recipient",
                "message",
                "transaction_type_code",
            ]
        },
    }


def encode_queue(rows: list[dict]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, QUEUE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def parse_reviews(raw: bytes) -> list[dict]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != QUEUE_COLUMNS:
            raise ReviewError("invalid_review_columns")
        rows = list(reader)
    except (UnicodeError, csv.Error):
        raise ReviewError("invalid_review_csv") from None
    if not rows:
        raise ReviewError("empty_review_file")
    seen = set()
    for line, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            raise ReviewError(f"malformed_row:line_{line}")
        try:
            identity = UUID(row["transaction_id"])
        except ValueError:
            raise ReviewError(f"invalid_transaction_id:line_{line}") from None
        if identity in seen:
            raise ReviewError(f"duplicate_transaction_id:line_{line}")
        seen.add(identity)
        status = row["review_status"]
        if status not in STATUSES:
            raise ReviewError(f"invalid_review_status:line_{line}")
        category, context = row["reviewed_category"], row["reviewed_business_context"]
        if status == "REVIEWED":
            if category not in CATEGORIES:
                raise ReviewError(f"invalid_category:line_{line}")
            if context not in CONTEXTS:
                raise ReviewError(f"invalid_context:line_{line}")
        elif category or context:
            raise ReviewError(f"labels_require_reviewed_status:line_{line}")
        if status == "SKIPPED_AMBIGUOUS" and not row["review_notes"].strip():
            raise ReviewError(f"ambiguous_review_requires_note:line_{line}")
    return rows
