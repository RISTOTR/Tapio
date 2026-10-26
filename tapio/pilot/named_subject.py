"""Read-only pilot subject evidence, separate from the frozen agent/evaluation path."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select

from apps.api.app.domain.models import Document, Invoice, Transaction, TransactionLabelReview
from apps.api.app.services.tool_queries import Queries
from tapio.pilot.subject_identity import extract_subject, resolve_subject, subject_intent
from tapio.tools.schemas import TransactionSummary

LIMIT = 1000


def bounded(rows):
    rows = list(rows)
    if len(rows) > LIMIT:
        raise ValueError("NAMED_SUBJECT_EVIDENCE_LIMIT")
    return rows


def retrieve_subject(question, session_factory):
    """Use normalized payee/recipient and issuer identities, never message substrings.

    No context/category/review/document requirement filters. Explicit years only;
    undated subject discovery searches all imported dates. Complete rows precede sums.
    """
    request = extract_subject(question)
    if request is None:
        return None
    t, r = Transaction, TransactionLabelReview
    fields = [t.normalized_counterparty, t.ultimate_recipient, t.payment_intermediary]
    with session_factory() as db:
        names = set()
        for field in [*fields, Invoice.vendor, Document.document_metadata["vendor"].astext]:
            names.update(
                bounded(
                    db.scalars(select(field).where(field.is_not(None)).distinct().limit(LIMIT + 1))
                )
            )
        resolved = resolve_subject(request["text"], names)
        result = {
            **resolved,
            "request": request,
            "intent": subject_intent(question),
            "trace": {
                "resolver": "tapio.pilot.subject_identity.resolve_subject",
                "resolver_version": "subject-identity-v2",
                "inventory_queried": True,
                "bank_query_invoked": False,
                "document_query_invoked": False,
                "invoice_query_invoked": False,
                "rows_returned": {"bank": 0, "documents": 0, "invoices": 0},
            },
            "transactions": [],
            "documents": [],
            "invoices": [],
            "totals": [],
            "filters": {
                "year": request["year"],
                "context": None,
                "category": None,
                "review_state": None,
            },
            "identity_fields": [
                "normalized_counterparty",
                "ultimate_recipient",
                "payment_intermediary",
                "invoice.vendor",
                "document.vendor",
            ],
        }
        if resolved["status"] != "MATCH_FOUND":
            return result
        names = resolved["names"]

        def dated(query, column):
            if request["year"]:
                query = query.where(
                    column >= date(int(request["year"]), 1, 1),
                    column <= date(int(request["year"]), 12, 31),
                )
            return query

        query = select(t, r).outerjoin(
            r, (r.transaction_id == t.id) & (r.review_status == "REVIEWED")
        )
        query = dated(query.where(or_(*(f.in_(names) for f in fields))), t.booking_date)
        result["trace"]["bank_query_invoked"] = True
        rows = bounded(db.execute(query.order_by(t.booking_date, t.id).limit(LIMIT + 1)).all())
        result["transactions"] = [
            TransactionSummary(
                id=row.id,
                booking_date=row.booking_date,
                amount=row.amount,
                currency=row.currency,
                direction=row.direction,
                counterparty=resolved["canonical_subject"],
                category=review.confirmed_category if review else None,
                business_context=review.confirmed_business_context if review else None,
                label_authority="HUMAN_REVIEWED" if review else "UNREVIEWED",
            ).model_dump(mode="json")
            for row, review in rows
        ]
        # All matching rows have been retrieved; never total a truncated page or mix currencies.
        for currency in sorted({row.currency for row, _ in rows}):
            debits = [
                row for row, _ in rows if row.currency == currency and row.direction == "outgoing"
            ]
            if any(row.amount > 0 for row in debits):
                raise ValueError("NAMED_SUBJECT_DEBIT_SIGN")
            result["totals"].append(
                {
                    "currency": currency,
                    "payment_count": len(debits),
                    "debit_total": str(-sum((row.amount for row in debits), Decimal(0))),
                }
            )
        result["trace"]["document_query_invoked"] = True
        docs = bounded(
            db.scalars(
                dated(
                    select(Document).where(Document.document_metadata["vendor"].astext.in_(names)),
                    Document.document_date,
                ).limit(LIMIT + 1)
            )
        )
        result["trace"]["invoice_query_invoked"] = True
        invoices = bounded(
            db.scalars(
                dated(select(Invoice).where(Invoice.vendor.in_(names)), Invoice.invoice_date).limit(
                    LIMIT + 1
                )
            )
        )
        queries = Queries(session_factory=session_factory)
        result["documents"] = [queries.document(d).model_dump(mode="json") for d in docs]
        result["invoices"] = [
            queries.invoice_summary(db, i).model_dump(mode="json") for i in invoices
        ]
        result["identity"]["matched_source_identifiers"] = {
            "bank_transactions": [str(row.id) for row, _ in rows],
            "documents": [str(d.id) for d in docs],
            "invoices": [str(i.id) for i in invoices],
        }
        roles = set()
        for row, _ in rows:
            for field, role in [
                ("normalized_counterparty", "BANK_PAYEE"),
                ("ultimate_recipient", "RECIPIENT"),
                ("payment_intermediary", "PAYMENT_PROCESSOR"),
            ]:
                if getattr(row, field) in names:
                    roles.add(role)
        if docs or invoices:
            roles.add("DOCUMENT_ISSUER")
        result["identity"]["subject_types"] = sorted(roles)
        result["trace"]["rows_returned"] = {
            "bank": len(rows),
            "documents": len(docs),
            "invoices": len(invoices),
        }
        coverage_query = dated(
            select(func.min(t.booking_date), func.max(t.booking_date), func.count()), t.booking_date
        )
        first, last, count = db.execute(coverage_query).one()
        result["coverage"] = {
            "observed_from": str(first) if first else None,
            "observed_to": str(last) if last else None,
            "imported_rows": count,
            "complete_statement": False,
        }
        if not rows and not docs and not invoices:
            result["status"] = "NO_MATCH"
        return result


def subject_cards(question, evidence):
    """Present only the separately verified subject evidence; preserve private IDs in audit."""
    from tapio.pilot.answer_cards import (
        DOC_FIELDS,
        REC_FIELDS,
        ROW_FIELDS,
        amount,
        document_inventory,
        project,
        transaction_line,
    )
    from tapio.pilot.subject_identity import eligible_subject

    if not eligible_subject(question, evidence):
        raise ValueError("NAMED_SUBJECT_NOT_ELIGIBLE")
    intent = subject_intent(question)
    tax = intent == "TAX_BOUNDARY"
    financial = intent == "FINANCIAL_TOTAL"
    mode = "TAX_BOUNDARY" if tax else "FINANCIAL_TOTAL" if financial else "NAMED_SUBJECT"
    rows = evidence["transactions"]
    docs = document_inventory(evidence["documents"] + evidence["invoices"])
    state = evidence["status"]
    label = evidence["canonical_subject"] or evidence["request"]["text"]
    breakdown, review = [], ""
    if state == "AMBIGUOUS_IDENTITY":
        direct = "The name matches multiple stored identities. Please specify the legal name."
    elif financial and evidence["canonical_subject"] and not rows:
        period = evidence["request"]["year"] or "all imported dates"
        direct = (
            f"{label}: 0 matching bank payments in the imported period ({period}); "
            "matching bank debit total 0."
        )
    elif state == "NO_MATCH":
        direct = (
            "No matching bank or document evidence was found for this subject "
            "in the requested imported period."
        )
    elif financial and len(evidence["totals"]) == 1:
        total = evidence["totals"][0]
        period = evidence["request"]["year"] or "all imported dates"
        direct = (
            f"You paid {label} {amount(total['debit_total'], total['currency'])} "
            f"across {total['payment_count']} matching bank payments "
            f"in the supported imported period ({period})."
        )
    else:
        direct = f"{label}: {len(rows)} matching bank transaction(s) and {len(docs)} document(s)."
    if state == "MATCH_FOUND":
        breakdown = [transaction_line(r) for r in rows[:10]]
        if len(rows) > 10:
            breakdown.append("Additional matching transactions are retained in optional details.")
        confirmed = sorted(
            {
                r["business_context"]
                for r in rows
                if r["label_authority"] == "HUMAN_REVIEWED" and r["business_context"]
            }
        )
        if confirmed:
            breakdown.append("Human-confirmed contexts: " + ", ".join(confirmed) + ".")
        if any(
            r["label_authority"] != "HUMAN_REVIEWED" or r["business_context"] in (None, "UNKNOWN")
            for r in rows
        ):
            review = (
                "Context remains unresolved for unconfirmed rows; "
                "merchant identity does not assign purpose."
            )
    if tax:
        direct += " Tapio does not decide tax deductibility."
        review = (
            "Tax treatment requires a separate human decision; "
            "confirmed context is not a tax conclusion."
        )
    coverage = evidence.get("coverage", {})
    period = evidence["request"]["year"] or "all imported dates"
    note = f"Search scope: {period}."
    if coverage:
        note += f" Imported booking dates: {coverage['observed_from']}–{coverage['observed_to']}."
    note += " Imported evidence does not prove a complete bank statement or calendar year."
    return {
        "presentation_mode": mode,
        "direct_answer": direct,
        "relevant_breakdown": breakdown,
        "coverage_note": note,
        "human_review_note": review,
        "evidence_summary": [
            "Bank and document search results; retrieved details are available below."
        ],
        "optional_details": {
            "named_subject": {
                "status": state,
                "canonical_subject": evidence["canonical_subject"],
                "match_method": evidence["method"],
                "coverage": coverage,
            },
            "transactions": [project(r, ROW_FIELDS) for r in rows],
            "documents": [project(d, DOC_FIELDS) for d in docs],
            "reconciliation": [
                project(i["reconciliation"], REC_FIELDS) for i in evidence["invoices"]
            ],
            "main_limitations": []
            if docs
            else ["No matching document found; this does not prove no receipt exists."],
        },
    }
