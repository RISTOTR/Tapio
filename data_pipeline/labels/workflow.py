"""Human review persistence and read-only ground-truth projections."""

from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import polars as pl
from sqlalchemy import func, select

from apps.api.app.domain.models import Transaction, TransactionLabelReview
from data_pipeline.ingest.bank_csv import SOURCE_TYPE
from data_pipeline.labels.contracts import (
    CATEGORIES,
    CONTEXTS,
    FACT_FIELDS,
    ReviewError,
    encode_queue,
    review_facts,
)
from data_pipeline.labels.review_input import parse_import
from data_pipeline.labels.sampling import sample_transactions
from data_pipeline.verify_bank import read_transactions

LABEL_LOCK = int.from_bytes(
    sha256(b"tapio:human-classification-reviews:v1").digest()[:8], signed=True
)


def source_identifiers(session):
    """Redact known banking identifiers even when mentioned on another transaction."""
    keys = ("Saajan tilinumero", "Saajan pankin BIC", "Arkistointitunnus")
    return {
        raw[key]
        for raw in session.scalars(select(Transaction.raw_source))
        if raw
        for key in keys
        if raw.get(key)
    }


def prepare_queue(factory, account_key: str, *, target=100, seed=42):
    """Create only UNREVIEWED placeholders and frozen snapshots; never human labels."""
    with factory.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LABEL_LOCK)))
        secrets = source_identifiers(session)
        frame = read_transactions(session, account_key)
        objects = session.scalars(
            select(Transaction).where(
                Transaction.source_namespace == f"{SOURCE_TYPE}:{account_key}"
            )
        ).all()
        by_archive = {r.source_transaction_id: r for r in objects}
        existing = {
            str(r.transaction_id): r for r in session.scalars(select(TransactionLabelReview)).all()
        }
        frame = frame.with_columns(
            pl.Series(
                "transaction_id", [str(by_archive[k].id) for k in frame["source_transaction_id"]]
            ),
            pl.Series(
                "source_description",
                [
                    (by_archive[k].raw_source or {}).get("Selitys", "")
                    for k in frame["source_transaction_id"]
                ],
            ),
        )
        # Final reviews are not put back into a new blank queue.
        frame = frame.filter(
            ~pl.col("transaction_id").is_in(
                [key for key, review in existing.items() if review.review_status != "UNREVIEWED"]
            )
        )
        sampled, report = sample_transactions(frame, target=target, seed=seed)
        queue = []
        for row in sampled:
            transaction = by_archive[row["source_transaction_id"]]
            review = existing.get(str(transaction.id))
            if review is None:
                review = TransactionLabelReview(
                    transaction_id=transaction.id,
                    suggested_category_snapshot=(transaction.category or "unknown").upper(),
                    suggested_context_snapshot=(
                        transaction.business_context.value
                        if transaction.business_context
                        else "unknown"
                    ).upper(),
                )
                session.add(review)
            queue.append(
                {
                    **review_facts(transaction, secrets),
                    "suggested_category": review.suggested_category_snapshot,
                    "suggested_business_context": review.suggested_context_snapshot,
                    "sampling_reasons": ";".join(sorted(row["tags"])),
                    "review_hint": row["review_hint"],
                    "reviewed_category": "",
                    "reviewed_business_context": "",
                    "review_status": "UNREVIEWED",
                    "review_notes": "",
                }
            )
    return encode_queue(queue), report


def import_reviews(raw: bytes, *, reviewer: str, factory) -> dict:
    if not reviewer.strip() or reviewer != reviewer.strip() or len(reviewer) > 100:
        raise ReviewError("invalid_reviewer")
    rows, label_source = parse_import(raw)
    digest = sha256(raw).hexdigest()
    result = {
        "reviewed_rows_inserted": 0,
        "ambiguous_skipped": 0,
        "unreviewed": 0,
        "unchanged": 0,
        "validation_failures": 0,
    }
    with factory.begin() as session:
        session.execute(select(func.pg_advisory_xact_lock(LABEL_LOCK)))
        secrets = source_identifiers(session)
        for line, row in enumerate(rows, 2):
            identity = UUID(row["transaction_id"])
            transaction = session.get(Transaction, identity)
            if transaction is None:
                raise ReviewError(f"unknown_transaction_id:line_{line}")
            review = session.scalar(
                select(TransactionLabelReview).where(
                    TransactionLabelReview.transaction_id == identity
                )
            )
            if review is None:
                raise ReviewError(f"transaction_not_in_registered_queue:line_{line}")
            expected = review_facts(transaction, secrets)
            if any(row[key] != expected[key] for key in FACT_FIELDS):
                raise ReviewError(f"read_only_fields_changed:line_{line}")
            if (
                row["suggested_category"] != review.suggested_category_snapshot
                or row["suggested_business_context"] != review.suggested_context_snapshot
            ):
                raise ReviewError(f"suggestion_snapshot_changed:line_{line}")
            status = row["review_status"]
            category = row["reviewed_category"] or None
            context = row["reviewed_business_context"] or None
            notes = row["review_notes"] or None
            if review.review_status != "UNREVIEWED":
                unchanged = (
                    review.review_status == status
                    and review.confirmed_category == category
                    and review.confirmed_business_context == context
                    and review.review_notes == notes
                    and review.reviewer == reviewer
                )
                if not unchanged:
                    raise ReviewError(f"existing_review_conflict:line_{line}")
                result["unchanged"] += 1
                continue
            if status == "UNREVIEWED":
                result["unreviewed"] += 1
                continue
            review.confirmed_category = category
            review.confirmed_business_context = context
            review.review_status = status
            review.reviewer = reviewer
            review.reviewed_at = datetime.now(UTC)
            review.review_notes = notes
            review.label_source = label_source
            review.taxonomy_version = "2"
            review.review_file_sha256 = digest
            result["reviewed_rows_inserted" if status == "REVIEWED" else "ambiguous_skipped"] += 1
            session.flush()
    return result


GROUND_TRUTH_SCHEMA = {
    "transaction_id": pl.String,
    "normalized_counterparty": pl.String,
    "ultimate_recipient": pl.String,
    "message": pl.String,
    "transaction_type_code": pl.String,
    "amount": pl.Decimal(20, 6),
    "direction": pl.String,
    "month": pl.Int8,
    "day_of_week": pl.Int8,
    "confirmed_category": pl.String,
    "confirmed_business_context": pl.String,
}


def reviewed_pairs(session, account_key):
    return session.execute(
        select(Transaction, TransactionLabelReview)
        .join(TransactionLabelReview, TransactionLabelReview.transaction_id == Transaction.id)
        .where(Transaction.source_namespace == f"{SOURCE_TYPE}:{account_key}")
        .order_by(Transaction.id)
    ).all()


def ground_truth(session, account_key: str) -> pl.DataFrame:
    secrets = source_identifiers(session)
    rows = []
    for transaction, review in reviewed_pairs(session, account_key):
        if review.review_status != "REVIEWED":
            continue
        facts = review_facts(transaction, secrets)
        rows.append(
            {
                **{
                    key: facts[key]
                    for key in [
                        "transaction_id",
                        "normalized_counterparty",
                        "ultimate_recipient",
                        "message",
                        "transaction_type_code",
                        "direction",
                    ]
                },
                "amount": transaction.amount,
                "month": transaction.booking_date.month,
                "day_of_week": transaction.booking_date.weekday(),
                "confirmed_category": review.confirmed_category,
                "confirmed_business_context": review.confirmed_business_context,
            }
        )
    return pl.DataFrame(rows, schema=GROUND_TRUTH_SCHEMA)


def quality_report(session, account_key: str) -> dict:
    pairs = reviewed_pairs(session, account_key)
    reviewed = [(t, r) for t, r in pairs if r.review_status == "REVIEWED"]
    n = len(reviewed)
    category_counts = Counter(r.confirmed_category for _, r in reviewed)
    context_counts = Counter(r.confirmed_business_context for _, r in reviewed)

    def agreement(snapshot, confirmed):
        matches = sum(getattr(r, snapshot) == getattr(r, confirmed) for _, r in reviewed)
        covered = [r for _, r in reviewed if getattr(r, snapshot) != "UNKNOWN"]
        return {
            "name": "rule agreement on reviewed subset",
            "denominator": n,
            "matches": matches,
            "rate": matches / n if n else None,
            "non_unknown_suggestion_denominator": len(covered),
            "non_unknown_suggestion_rate": sum(
                getattr(r, snapshot) == getattr(r, confirmed) for r in covered
            )
            / len(covered)
            if covered
            else None,
        }

    return {
        "total_queue_rows": len(pairs),
        "ground_truth_rows": n,
        "total_reviewed": n,
        "total_ambiguous_skipped": sum(r.review_status == "SKIPPED_AMBIGUOUS" for _, r in pairs),
        "total_unreviewed": sum(r.review_status == "UNREVIEWED" for _, r in pairs),
        "category_counts": {key: category_counts[key] for key in CATEGORIES},
        "context_counts": {key: context_counts[key] for key in CONTEXTS},
        "credits": sum(t.amount > 0 for t, _ in reviewed),
        "debits": sum(t.amount < 0 for t, _ in reviewed),
        "paytrail_reviewed_count": sum(
            t.payment_intermediary == "Paytrail Oyj" for t, _ in reviewed
        ),
        "forestry_reviewed_count": context_counts["FORESTRY"],
        "property_reviewed_count": context_counts["PROPERTY"],
        "personal_reviewed_count": context_counts["PERSONAL"],
        "unknown_category_count": category_counts["UNKNOWN"],
        "unknown_context_count": context_counts["UNKNOWN"],
        "class_balance": {
            "category": class_balance({key: category_counts[key] for key in CATEGORIES}),
            "business_context": class_balance({key: context_counts[key] for key in CONTEXTS}),
        },
        "unknown_confirmed_count": sum(
            r.confirmed_category == "UNKNOWN" or r.confirmed_business_context == "UNKNOWN"
            for _, r in reviewed
        ),
        "category_rule_agreement": agreement("suggested_category_snapshot", "confirmed_category"),
        "context_rule_agreement": agreement(
            "suggested_context_snapshot", "confirmed_business_context"
        ),
    }


def class_balance(counts):
    return {
        "represented_classes": sum(n > 0 for n in counts.values()),
        "examples_per_class": counts,
        "absent_classes": [k for k, n in counts.items() if n == 0],
        **{
            f"fewer_than_{limit}": {k: n for k, n in counts.items() if n < limit}
            for limit in (2, 5, 10)
        },
    }
