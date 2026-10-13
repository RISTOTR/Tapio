"""Explicit source-only features and conservative effective-merchant identity."""

import hashlib
import json
import re
import unicodedata
from collections import Counter

import numpy as np
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from data_pipeline.normalize.bank import name_key, normalize_name, suggest

SEED = 42
TEXT_FIELDS = ("normalized_counterparty", "ultimate_recipient", "message", "transaction_type_code")
STRUCTURED_FIELDS = ("amount", "direction", "month", "day_of_week")
CONTEXT_CLASSES = ("PERSONAL", "PROPERTY", "FORESTRY")


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def combined_text(row):
    return " | ".join(f"{key}: {row.get(key) or ''}" for key in TEXT_FIELDS)


def feature_rows(rows):
    return [{key: row.get(key) for key in TEXT_FIELDS + STRUCTURED_FIELDS} for row in rows]


def texts(rows):
    return [combined_text(row) for row in rows]


def structured(rows):
    return [
        {
            "signed_log_amount": float(
                np.sign(float(r["amount"])) * np.log1p(abs(float(r["amount"])))
            ),
            "direction": r["direction"],
            "month": float(r["month"]),
            "day_of_week": float(r["day_of_week"]),
        }
        for r in rows
    ]


def merchant(row):
    value = (row.get("ultimate_recipient") or "").strip()
    if not value or not any(c.isalpha() for c in value):
        value = row.get("normalized_counterparty") or ""
    value = unicodedata.normalize("NFKC", value)
    canonical = name_key(normalize_name(value) or "(missing merchant)")
    ascii_name = "".join(
        c for c in unicodedata.normalize("NFKD", canonical) if not unicodedata.combining(c)
    )
    # Conservative known brand/entity families, independent of targets. Grouping
    # multiple related entities together is safer than leaking spelling aliases.
    if re.match(r"^dna\b", ascii_name):
        return "dna"
    if "liikenne" in ascii_name and "viestintavirasto" in ascii_name:
        return "traficom"
    if re.match(r"^(lahi|lhi)tapiola\b", ascii_name):
        return "lahitapiola-family"
    if ascii_name.startswith("r_") and "lentoas" in ascii_name:
        return "airport-r-kiosk-family"
    return canonical


def rule_predictions(rows, target):
    key = "business_context" if target == "context" else "category"
    result = []
    for row in rows:
        name = normalize_name(merchant(row))
        label = suggest(name, row["direction"].lower())[key].upper()
        result.append(label if label != "UNKNOWN" else "NEEDS_REVIEW")
    return np.array(result)


def cohort(rows, target):
    field = "confirmed_business_context" if target == "context" else "confirmed_category"
    counts = Counter(r[field] for r in rows)
    allowed = (
        set(CONTEXT_CLASSES)
        if target == "context"
        else {label for label, count in counts.items() if count >= 4 and label != "UNKNOWN"}
    )
    selected = np.array([i for i, r in enumerate(rows) if r[field] in allowed], dtype=int)
    excluded = np.array([i for i, r in enumerate(rows) if r[field] not in allowed], dtype=int)
    return selected, excluded


def split_indices(labels, groups, view):
    indices = np.arange(len(labels))
    if view == "ordinary":
        train, test = train_test_split(indices, test_size=0.2, random_state=SEED, stratify=labels)
    elif view == "grouped":
        train, test = next(
            GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED).split(
                indices, labels, groups
            )
        )
        assert not set(np.asarray(groups)[train]) & set(np.asarray(groups)[test])
    else:
        raise ValueError("Unknown evaluation view")
    if len(set(np.asarray(labels)[train])) < 2:
        raise ValueError("Training requires at least two classes")
    return np.sort(train), np.sort(test)
