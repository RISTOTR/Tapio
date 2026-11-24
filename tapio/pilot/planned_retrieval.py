"""Read-only plan execution. Classification is current review state, never tax treatment."""

import calendar
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from apps.api.app.domain.models import Document, Invoice, TransactionInvoiceAllocation
from apps.api.app.services.tool_queries import Queries
from tapio.confirmation.projection import current_classified_transactions
from tapio.pilot.concepts import concept_plan
from tapio.pilot.subject_identity import REGISTRY, normalize_subject
from tapio.pilot.transaction_search import matching_terms, normalize_text, source_text_fields
from tapio.tools.schemas import EnergyQuery


def aliases(name):
    normalized = normalize_subject(name)
    for canonical, entry in REGISTRY.items():
        names = [canonical, *entry.aliases, *entry.bank_descriptors]
        if normalized in {normalize_subject(n) for n in names}:
            return names
    # Only legal company suffixes; preserve whole-token boundaries, not fuzzy names.
    base = re.sub(r"(?:\s+(?:oyj?|ab|ltd|limited|inc)\.?)+$", "", name.strip(), flags=re.I)
    return list(dict.fromkeys([name, base])) if base else [name]


def concept_terms(concept):
    # Semantic transport vocabulary is shared across questions, not a phrase router.
    transport = {
        "flight": ["flight", "airline", "finnair", "ryanair", "norwegian", "lento"],
        "train": ["train", "rail", "vr", "juna"],
        "bus": ["bus", "matkahuolto", "onnibus", "linja-auto"],
        "travel": [
            "travel",
            "journey",
            "trip",
            "matka",
            "flight",
            "airline",
            "finnair",
            "ryanair",
            "norwegian",
            "lento",
            "train",
            "rail",
            "vr",
            "juna",
            "bus",
            "matkahuolto",
            "onnibus",
            "hotel",
            "booking",
        ],
    }
    key = normalize_text(concept).rstrip("s")
    if key in transport:
        return transport[key]
    return concept_plan(concept).terms


def included(row, plan):
    """Independent post-retrieval scope check; do not broaden on zero matches."""
    day = date.fromisoformat(row["booking_date"])
    return (
        (any(p.date_from <= day <= p.date_to for p in plan.periods) or not plan.periods)
        and (not plan.contexts or row["business_context"] in plan.contexts)
        and (not plan.categories or row["category"] in plan.categories)
        and not any(
            (e.category is None or row["category"] == e.category)
            and (e.context is None or row["business_context"] == e.context)
            for e in plan.exclusions
        )
        and (not plan.expense_only or row["category"] not in {"TAX", "TRANSFER"})
        and (plan.action != "TAX_SUGGESTION" or Decimal(row["amount"]) < 0)
    )


def transactions(db, plan):
    records, unresolved = [], []
    pairs = current_classified_transactions(db, plan.periods)
    concept_words = [w for c in plan.concepts for w in concept_terms(c)]
    for tx, review in pairs:
        confirmed = review is not None and review.review_status == "REVIEWED"
        row = {
            "transaction_id": str(tx.id),
            "booking_date": str(tx.booking_date),
            "amount": str(tx.amount),
            "currency": tx.currency,
            "counterparty": tx.ultimate_recipient
            or tx.normalized_counterparty
            or tx.raw_counterparty,
            "category": review.confirmed_category if confirmed else "UNKNOWN",
            "business_context": review.confirmed_business_context if confirmed else "UNKNOWN",
            "authority": "Current human-confirmed classification" if confirmed else "Unreviewed",
            "classification_provenance": str(review.id) if confirmed else None,
            "field_authority": getattr(review, "field_authority", None) if confirmed else None,
            "source": "Local bank transaction",
            "source_file": tx.source_file,
            "source_system": (tx.raw_source or {}).get("source_system"),
            "source_account": (tx.raw_source or {}).get("source_account"),
            "tax_treatment": None,
            "message": tx.message,
            "payment_reference": tx.reference,
        }
        if not included(row, plan):
            continue
        if plan.metric == "OUTFLOW" and tx.amount >= 0:
            continue
        if plan.metric == "INFLOW" and tx.amount <= 0:
            continue
        fields = source_text_fields(tx)
        if plan.merchants and not any(matching_terms(fields, aliases(m)) for m in plan.merchants):
            continue
        evidence = []
        for allocation, invoice, doc in db.execute(
            select(TransactionInvoiceAllocation, Invoice, Document)
            .join(Invoice, Invoice.id == TransactionInvoiceAllocation.invoice_id)
            .join(Document, Document.id == Invoice.document_id)
            .where(
                TransactionInvoiceAllocation.transaction_id == tx.id,
                TransactionInvoiceAllocation.status != "REJECTED",
            )
        ):
            evidence.append(
                {
                    "source": "Linked invoice",
                    "reference": str(doc.id),
                    "filename": doc.source_filename,
                    "sha256": doc.sha256,
                    "invoice_number": invoice.invoice_number,
                    "vendor": invoice.vendor,
                    "date": str(invoice.invoice_date),
                    "total_eur": str(invoice.total_eur),
                    "link_status": allocation.status,
                    "link_evidence": allocation.evidence,
                }
            )
        row["supporting_evidence"] = evidence
        evidence_fields = {**fields, "documents": str(evidence)}
        if concept_words and not matching_terms(evidence_fields, concept_words):
            unresolved.append({**row, "missing": "Requested travel mode/concept is not evidenced."})
            continue
        if plan.locations and not all(
            matching_terms(evidence_fields, [loc]) for loc in plan.locations
        ):
            unresolved.append(
                {**row, "missing": "Destination is not evidenced: " + ", ".join(plan.locations)}
            )
            continue
        row["reason"] = "Matches " + "; ".join(
            filter(
                None,
                [
                    ", ".join(plan.contexts),
                    ", ".join(plan.categories),
                    ", ".join(plan.merchants),
                    ", ".join(plan.concepts),
                    ", ".join(plan.locations),
                    "requested booking dates",
                ],
            )
        )
        if plan.action == "TAX_SUGGESTION":
            row["suggestion"] = "Tax review candidate"
            if row["category"] in {"UNKNOWN", "TRANSFER", "TAX"}:
                row["check_next"] = (
                    "The recorded category does not establish the underlying expense; "
                    "check its purpose."
                )
        if evidence and any(e["link_status"] != "CONFIRMED" for e in evidence):
            row["check_next"] = "The invoice link is a candidate and has not been confirmed."
        records.append(row)
    assert all(included(r, plan) for r in records)
    return records, unresolved


def monthly_periods(period):
    start = period.date_from
    while start <= period.date_to:
        end = min(
            date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]),
            period.date_to,
        )
        yield start, end
        start = date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def energy(plan, session_factory):
    from tapio.tools.errors import ErrorCode, ToolFailure

    queries = Queries(session_factory=session_factory)
    records, missing = [], []
    metric = "consumption_kwh" if plan.metric == "CONSUMPTION" else "solar_export_kwh"
    for p in plan.periods:
        for start, end in monthly_periods(p):
            try:
                value = queries.energy(EnergyQuery(date_from=start, date_to=end, metric=metric))
            except ToolFailure as exc:
                if exc.code not in {ErrorCode.INCOMPLETE_COVERAGE, ErrorCode.NOT_FOUND}:
                    raise
                missing.append(f"{start} to {end}")
                continue
            if value.date_from != start or value.date_to != end:
                raise ValueError("Returned energy period differs from requested period")
            records.append({"source": "Local energy readings", **value.model_dump(mode="json")})
    return records, missing
