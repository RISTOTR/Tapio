"""Read-only, same-row migration of a human-edited v1 review queue to draft v2."""

import argparse
import csv
import io
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import Transaction, TransactionLabelReview
from data_pipeline.labels.contracts import (
    CATEGORIES,
    CONTEXTS,
    FACT_FIELDS,
    QUEUE_COLUMNS,
    REVIEW_FIELDS,
    ReviewError,
    encode_queue,
    parse_reviews,
    review_facts,
    safe_text,
)
from data_pipeline.labels.review_transactions import output_path
from data_pipeline.labels.workflow import source_identifiers

EVIDENCE_STATUSES = ("NOT_REQUIRED", "AVAILABLE", "NEEDS_DOCUMENT", "UNAVAILABLE", "UNKNOWN")
EVIDENCE_FIELDS = ["evidence_status", "supporting_document_id", "supporting_document_note"]
V2_COLUMNS = [
    "booking_date",
    "amount_display",
    "direction",
    "normalized_counterparty",
    "ultimate_recipient",
    "message",
    "transaction_type_code",
    "suggested_category",
    "suggested_business_context",
    *REVIEW_FIELDS,
    *EVIDENCE_FIELDS,
    "review_group",
    "review_hint",
    "transaction_id",
    "amount",
    "sampling_reasons",
]


def amount_display(value: str, currency: str = "EUR") -> str:
    """At least two decimals, retaining any nonzero sub-cent precision exactly."""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ReviewError("invalid_amount") from None
    if not amount.is_finite() or currency != "EUR":
        raise ReviewError("invalid_amount_or_currency")
    precision = max(2, len(format(amount, "f").partition(".")[2].rstrip("0")))
    # A signed numeric literal followed by the fixed EUR suffix is not executable
    # spreadsheet input; arbitrary strings never enter this display field.
    return f"{amount:+,.{precision}f} EUR"


def encode_v2(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, V2_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def parse_v2(raw, *, strict_labels=True):
    """Validate draft v2 without importing it or inferring any human labels."""
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames not in (V2_COLUMNS, [k for k in V2_COLUMNS if k != "review_group"]):
            raise ReviewError("invalid_v2_columns")
        rows = list(reader)
    except (UnicodeError, csv.Error):
        raise ReviewError("invalid_review_csv") from None
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ReviewError("malformed_row")
    for row in rows:
        row.setdefault("review_group", "")
    legacy = encode_queue([{k: r[k] for k in QUEUE_COLUMNS} for r in rows])
    (parse_reviews if strict_labels else parse_draft_v1)(legacy)
    for line, row in enumerate(rows, 2):
        if row["evidence_status"] not in EVIDENCE_STATUSES:
            raise ReviewError(f"invalid_evidence_status:line_{line}")
        if row["amount_display"] != amount_display(row["amount"]):
            raise ReviewError(f"amount_display_mismatch:line_{line}")
        for key in REVIEW_FIELDS + ["supporting_document_note", "review_group"]:
            if safe_text(row[key]) != row[key]:
                raise ReviewError(f"unsafe_text_requires_manual_edit:line_{line}:{key}")
        if row["supporting_document_id"]:
            try:
                UUID(row["supporting_document_id"])
            except ValueError:
                raise ReviewError(f"invalid_supporting_document_id:line_{line}") from None
    return rows


def normalize_input(raw, delimiter=","):
    """Numbers may export semicolon-separated CSV under a European locale."""
    if delimiter not in (",", ";"):
        raise ReviewError("invalid_input_delimiter")
    try:
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=delimiter, strict=True
        )
        if reader.fieldnames != QUEUE_COLUMNS:
            raise ReviewError("invalid_review_columns")
        rows = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ReviewError("malformed_row")
        return encode_queue(rows)
    except (UnicodeError, csv.Error):
        raise ReviewError("invalid_review_csv") from None


def parse_draft_v1(raw):
    """Preserve noncanonical draft labels; still validate structure, IDs and status shape."""
    normalized = normalize_input(raw)
    rows = list(csv.DictReader(io.StringIO(normalized.decode("utf-8-sig"), newline="")))
    validation_rows = [dict(r) for r in rows]
    for row in validation_rows:
        if row["reviewed_category"] and row["reviewed_category"] not in CATEGORIES:
            row["reviewed_category"] = "UNKNOWN"
        if row["reviewed_business_context"] and row["reviewed_business_context"] not in CONTEXTS:
            row["reviewed_business_context"] = "UNKNOWN"
    parse_reviews(encode_queue(validation_rows))
    return rows


def upgrade_rows(raw, expected, secrets=()):
    """Verify every source cell before copying human cells, without normalizing edits."""
    rows = parse_draft_v1(raw)
    output = []
    for line, row in enumerate(rows, 2):
        source = expected.get(row["transaction_id"])
        if source is None:
            raise ReviewError(f"unknown_or_unregistered_transaction:line_{line}")
        if any(row[k] != source[k] for k in FACT_FIELDS):
            raise ReviewError(f"read_only_fields_changed:line_{line}")
        for key in ("suggested_category", "suggested_business_context"):
            if row[key] != source[key]:
                raise ReviewError(f"suggestion_snapshot_changed:line_{line}")
        # Do not silently rewrite private or formula-like user edits. If unsafe,
        # stop and leave the original intact so the human can resolve the cell.
        for key in REVIEW_FIELDS + ["review_hint", "sampling_reasons"]:
            if safe_text(row[key], secrets) != row[key]:
                raise ReviewError(f"unsafe_text_requires_manual_edit:line_{line}:{key}")
        output.append(
            {
                **row,
                "amount_display": amount_display(row["amount"], source["currency"]),
                "evidence_status": "UNKNOWN",
                "supporting_document_id": "",
                "supporting_document_note": "",
                "review_group": "",
            }
        )
    result = encode_v2(output)
    parse_v2(result, strict_labels=False)
    edited = [
        r
        for r in rows
        if any(r[k] != ("UNREVIEWED" if k == "review_status" else "") for k in REVIEW_FIELDS)
    ]
    return result, {
        "rows": len(rows),
        "label_validation_issue_lines": [
            line
            for line, r in enumerate(rows, 2)
            if (r["reviewed_category"] and r["reviewed_category"] not in CATEGORIES)
            or (r["reviewed_business_context"] and r["reviewed_business_context"] not in CONTEXTS)
        ],
        "same_transaction_ids_and_order": True,
        "edited_rows_preserved": len(edited),
        "edited_cells_preserved": sum(
            r[k] != ("UNREVIEWED" if k == "review_status" else "")
            for r in rows
            for k in REVIEW_FIELDS
        ),
    }


def upgrade_queue(raw, factory):
    rows = parse_draft_v1(raw)
    identities = [UUID(r["transaction_id"]) for r in rows]
    with factory() as session:
        secrets = source_identifiers(session)
        pairs = session.execute(
            select(Transaction, TransactionLabelReview)
            .join(TransactionLabelReview, TransactionLabelReview.transaction_id == Transaction.id)
            .where(Transaction.id.in_(identities))
        ).all()
        expected = {
            str(t.id): {
                **review_facts(t, secrets),
                "currency": t.currency,
                "suggested_category": r.suggested_category_snapshot,
                "suggested_business_context": r.suggested_context_snapshot,
            }
            for t, r in pairs
        }
        return upgrade_rows(raw, expected, secrets)


def extend_v2(raw, factory, delimiter=","):
    """Add optional columns while preserving every cell from an existing v2 draft."""
    try:
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=delimiter, strict=True
        )
        columns = reader.fieldnames
        if columns not in (V2_COLUMNS, [k for k in V2_COLUMNS if k != "review_group"]):
            raise ReviewError("invalid_v2_columns")
        rows = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ReviewError("malformed_row")
    except (UnicodeError, csv.Error):
        raise ReviewError("invalid_review_csv") from None
    for row in rows:
        row.setdefault("review_group", "")
    result = encode_v2(rows)
    parse_v2(result, strict_labels=False)
    _, report = upgrade_queue(
        encode_queue([{k: r[k] for k in QUEUE_COLUMNS} for r in rows]), factory
    )
    with factory() as session:
        secrets = source_identifiers(session)
    for line, row in enumerate(rows, 2):
        for key in ["supporting_document_note", "review_group"]:
            if safe_text(row[key], secrets) != row[key]:
                raise ReviewError(f"unsafe_text_requires_manual_edit:line_{line}:{key}")
    return result, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--output-name", default="review_queue_v2.csv")
    parser.add_argument("--delimiter", choices=[",", ";"], default=",")
    parser.add_argument("--from-v2", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = output_path(args.output_name)
        if path.exists():
            raise FileExistsError
        raw = args.file.read_bytes()
        if args.from_v2:
            upgraded, report = extend_v2(raw, SessionLocal, args.delimiter)
        else:
            upgraded, report = upgrade_queue(normalize_input(raw, args.delimiter), SessionLocal)
        if args.file.read_bytes() != raw:
            raise ReviewError("source_changed_during_merge")
        with path.open("xb") as file:
            file.write(upgraded)
    except ReviewError as error:
        print(json.dumps({"status": "failed", "error_code": str(error)}))
        return 1
    except FileExistsError:
        print(json.dumps({"status": "failed", "error_code": "output_exists_choose_new_name"}))
        return 1
    except (OSError, ValueError, SQLAlchemyError):
        print(json.dumps({"status": "failed", "error_code": "queue_upgrade_failed"}))
        return 1
    print(json.dumps({"path": str(path), **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
