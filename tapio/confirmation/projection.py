"""Current field-authority view for live pilot retrieval; legacy review rows stay unchanged."""

from types import SimpleNamespace

from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision


def current_revisions(db):
    result = {}
    rows = db.scalars(
        select(ConfirmationRevision).order_by(ConfirmationRevision.sequence).limit(10001)
    )
    count = 0
    for row in rows:
        count += 1
        if count > 10000:
            raise ValueError("CONFIRMATION_PROJECTION_LIMIT")
        result[row.transaction_id] = row
    return result


def projected_review(tx, legacy, revisions):
    revision = revisions.get(tx.id)
    if revision is None:
        return legacy
    from tapio.confirmation.service import row_data
    from tapio.knowledge.models import digest

    if revision.audit["legacy_review_hash"] != digest(row_data(legacy) if legacy else None):
        raise ValueError("LEGACY_REVIEW_CHANGED_REQUIRES_RECONCILIATION")
    state = revision.state
    return SimpleNamespace(
        review_status="REVIEWED",
        confirmed_category=state["category"],
        confirmed_business_context=state["context"],
        field_authority=state["authority"],
    )


def project_review_rows(reviews, revisions):
    """Generator-only current-state projection; never feed partial rows to legacy accrual."""
    from tapio.knowledge.models import digest

    result = {r["transaction_id"]: r for r in reviews}
    for row in sorted(revisions, key=lambda r: r["sequence"]):
        tx = str(row["transaction_id"])
        result[tx] = {
            "id": str(row["id"]),
            "transaction_id": tx,
            "review_status": "REVIEWED",
            "confirmed_category": row["state"]["category"],
            "confirmed_business_context": row["state"]["context"],
            "review_file_sha256": digest(row),
            "field_authority": row["state"]["authority"],
        }
    return list(result.values())
