"""Read-only forestry deduction-review candidates, never tax decisions."""

from decimal import Decimal

from sqlalchemy import select

from apps.api.app.domain.models import Transaction, TransactionLabelReview
from tapio.confirmation.projection import current_revisions, projected_review
from tapio.pilot.config import load_config, readonly_engine, readonly_session, source_fingerprints
from tapio.pilot.transaction_search import requested_dates

GUIDANCE = "https://www.vero.fi/henkiloasiakkaat/omaisuus/metsa/metsatalouden-vahennykset/"
VAT_GUIDANCE = "https://vero.fi/en/businesses-and-corporations/taxes-and-charges/vat/deducting-vat-on-purchases/"


def candidate(tx, review):
    if (
        not review
        or review.review_status != "REVIEWED"
        or review.confirmed_business_context != "FORESTRY"
        or tx.amount >= 0
    ):
        return None
    category = review.confirmed_category or "UNKNOWN"
    ordinary = category in {
        "FUEL",
        "MAINTENANCE",
        "INSURANCE",
        "FORESTRY_SERVICE",
        "FORESTRY_SERVICES",
        "SUPPLIES",
    }
    return {
        "transaction_id": str(tx.id),
        "booking_date": str(tx.booking_date),
        "counterparty": tx.normalized_counterparty or tx.raw_counterparty,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "category": category,
        "business_context": "FORESTRY",
        "suggestion": "Possible forestry expense deduction"
        if ordinary
        else "Review tax treatment separately",
        "reason": "Current human-confirmed forestry context"
        + (
            f" and {category.lower()} category."
            if ordinary
            else "; category alone does not establish deduction treatment."
        ),
        "check_next": (
            "Check receipt and income-producing forestry use; exclude private use. "
            "Check whether equipment requires depreciation."
        ),
        "vat_status": (
            "Not calculated: verify VAT registration, eligible business use and invoice VAT."
        ),
        "source": "Local bank transaction",
        "source_file": tx.source_file,
        "authority": "Suggestion only — not a tax decision",
    }


def forestry_candidates(question):
    bounds = requested_dates(question)
    config, _ = load_config()
    engine = readonly_engine()
    try:
        before = source_fingerprints(engine, config)
        with readonly_session(engine) as db:
            q = select(Transaction, TransactionLabelReview).outerjoin(
                TransactionLabelReview, TransactionLabelReview.transaction_id == Transaction.id
            )
            if bounds:
                q = q.where(
                    Transaction.booking_date >= bounds.date_from,
                    Transaction.booking_date <= bounds.date_to,
                )
            revisions = current_revisions(db)
            pairs = db.execute(
                q.order_by(Transaction.booking_date, Transaction.id).limit(10001)
            ).all()
            if len(pairs) > 10000:
                raise ValueError("NARROW_TAX_REVIEW_PERIOD")
            records = [
                r
                for tx, legacy in pairs
                if (r := candidate(tx, projected_review(tx, legacy, revisions)))
            ]
        if source_fingerprints(engine, config) != before:
            raise ValueError("SOURCE_CHANGED_DURING_QUESTION")
        totals = {}
        for r in records:
            totals[r["currency"]] = totals.get(r["currency"], Decimal(0)) - Decimal(r["amount"])
        return records, [
            f"Recorded forestry outflows: {v:.2f} {c}. This is not a deductible or VAT total."
            for c, v in sorted(totals.items())
        ]
    finally:
        engine.dispose()
