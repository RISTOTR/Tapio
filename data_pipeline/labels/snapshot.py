"""Read-only review coverage and immutable private evaluation snapshots."""

import json
import os
from collections import Counter
from hashlib import sha256

from sqlalchemy import select

from apps.api.app.domain.models import Transaction, TransactionLabelReview
from apps.api.app.services.financial_summary import authoritative_label
from data_pipeline.labels.contracts import CATEGORIES, CONTEXTS


def fingerprint(rows):
    rows = sorted(rows, key=lambda r: json.dumps(r, default=str, sort_keys=True))
    return {
        "count": len(rows),
        "sha256": sha256(
            json.dumps(rows, default=str, sort_keys=True, indent=2).encode()
        ).hexdigest(),
    }


def review_coverage(session, year=2026):
    reviews = {r.transaction_id: r for r in session.scalars(select(TransactionLabelReview))}
    transactions = [t for t in session.scalars(select(Transaction)) if t.booking_date.year == year]
    categories, contexts = Counter(), Counter()
    reviewed = unresolved = income = 0
    for t in transactions:
        context, category, human = authoritative_label(reviews.get(t.id))
        reviewed += int(human)
        unresolved += int(not human or context == "UNKNOWN" or category == "UNKNOWN")
        if human:
            categories[category] += 1
            contexts[context] += 1
            income += int(t.amount > 0)
        else:
            contexts["UNKNOWN"] += 1
    return {
        "year": year,
        "total": len(transactions),
        "human_reviewed": reviewed,
        "unresolved": unresolved,
        "reviewed_percentage": 100 * reviewed / len(transactions) if transactions else 0,
        "categories": {k: categories[k] for k in CATEGORIES},
        "contexts_including_unreviewed_as_unknown": {k: contexts[k] for k in CONTEXTS},
        "electricity": categories["ELECTRICITY"],
        "grid_distribution": categories["GRID_DISTRIBUTION"],
        "forestry_related": contexts["FORESTRY"],
        "income_related": income,
        "income_definition": (
            "Positive-amount transactions with human-confirmed classification; "
            "includes transfers/refunds, not taxable income inference."
        ),
        "year_status": "PARTIAL_YEAR",
        "coverage_status": "UNKNOWN_COVERAGE",
    }


def freeze(path, payload):
    """Exclusive creation: never replace any historical snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(payload, indent=2, sort_keys=True, default=str).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    return sha256(raw).hexdigest()
