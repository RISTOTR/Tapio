"""Adapt the existing Phase 07 queue to the established human-review contract."""

import json

from data_pipeline.labels.contracts import FACT_FIELDS, ReviewError, encode_queue, parse_reviews

COLUMNS = FACT_FIELDS + [
    "reference",
    "weak_category",
    "weak_context",
    "linked_evidence",
    "recurrence_count_same_counterparty",
    "recurrence_dates",
    "reversal_evidence",
    "priority",
    "reasons",
    "confirmed_category",
    "confirmed_context",
    "human_decision",
    "policy",
]
DECISION_FIELDS = {"confirmed_category", "confirmed_context", "human_decision"}


def adapt(rows):
    converted = []
    for row in rows:
        converted.append(
            {
                **{key: row[key] for key in FACT_FIELDS},
                "suggested_category": (row["weak_category"] or "unknown").upper(),
                "suggested_business_context": (row["weak_context"] or "unknown").upper(),
                "sampling_reasons": row["reasons"],
                "review_hint": row["policy"],
                "reviewed_category": row["confirmed_category"],
                "reviewed_business_context": row["confirmed_context"],
                "review_status": "REVIEWED"
                if row["confirmed_category"] or row["confirmed_context"]
                else "UNREVIEWED",
                "review_notes": row["human_decision"],
            }
        )
    return parse_reviews(encode_queue(converted))


def validate_manifest(rows, manifest):
    """The frozen original queue registers identities without creating placeholders."""
    if manifest is None:
        raise ReviewError("phase07_original_queue_required")
    originals = {r["transaction_id"]: r for r in manifest}
    if len(originals) != len(manifest) or set(originals) != {r["transaction_id"] for r in rows}:
        raise ReviewError("phase07_queue_identity_mismatch")
    for line, row in enumerate(rows, 2):
        original = originals[row["transaction_id"]]
        for key in COLUMNS:
            if key in DECISION_FIELDS:
                continue
            value = original[key]
            expected = (
                json.dumps(value, ensure_ascii=False)
                if isinstance(value, (list, dict))
                else ""
                if value is None
                else str(value)
            )
            if row[key] != expected:
                raise ReviewError(f"phase07_read_only_fields_changed:line_{line}")
