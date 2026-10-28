"""Bank-message evidence and conservative imported-document candidates, never confirmations."""

import re
from datetime import date
from decimal import Decimal

from data_pipeline.reconcile.invoices import reference_key
from tapio.knowledge.fields import source_text_fields
from tapio.pilot.transaction_search import normalize_text


def document_candidates(tx, invoices, accepted_allocations=()):
    fields = source_text_fields(tx)
    normalized = " " + normalize_text(" ".join(v for v in fields.values() if v)) + " "
    accepted = {
        a["invoice_id"]: a
        for a in accepted_allocations
        if a["transaction_id"] == tx["id"] and a["status"] == "CONFIRMED"
    }
    matches = []
    for invoice in invoices:
        date_text = invoice.get("due_date") or invoice.get("invoice_date")
        days = (
            abs((date.fromisoformat(tx["booking_date"]) - date.fromisoformat(date_text)).days)
            if date_text
            else None
        )
        amount = invoice.get("total_eur") is not None and abs(Decimal(tx["amount"])) == Decimal(
            invoice["total_eur"]
        )
        ref = invoice.get("reference") or invoice.get("invoice_number")
        reference = bool(ref) and (
            reference_key(ref) == reference_key(tx.get("reference"))
            or (" " + normalize_text(ref) + " ") in normalized
        )
        name = normalize_text(invoice.get("vendor"))
        merchant = bool(name) and (" " + name + " ") in normalized
        if invoice["id"] in accepted or (
            days is not None and days <= 31 and amount and (reference or merchant)
        ):
            matches.append(
                {
                    "invoice_id": invoice["id"],
                    "status": "CONFIRMED" if invoice["id"] in accepted else "CANDIDATE",
                    "evidence": {
                        "amount_exact": amount,
                        "days_apart": days,
                        "reference_literal": reference,
                        "merchant_literal": merchant,
                    },
                    "source_fields": list(fields),
                }
            )
    pending = [m for m in matches if m["status"] == "CANDIDATE"]
    if len(pending) > 1:
        for m in pending:
            m["status"] = "AMBIGUOUS"
    return matches


def purpose_evidence(tx, review=None, links=()):
    message = (tx.get("raw_source") or {}).get("Viesti") or ""
    # Only explicit purchase/service words; a named recipient alone is not purchase purpose.
    tokens = re.findall(r"prepaid|matkalipp\w*|vakuutusmaks\w*|korjaus\w*", normalize_text(message))
    if tokens:
        return {
            "classification": "PURPOSE_VISIBLE_IN_BANK_SOURCE",
            "purpose_terms": tokens,
            "field": "raw_source.Viesti",
            "recipient_visible": "lopullinen saaja" in normalize_text(message),
        }
    if any(link["status"] == "CONFIRMED" for link in links):
        return {
            "classification": "PURPOSE_VISIBLE_ONLY_IN_DOCUMENT",
            "purpose_terms": [],
            "recipient_visible": bool(message),
        }
    if (
        review
        and review.get("review_status") == "REVIEWED"
        and review.get("confirmed_category") not in (None, "UNKNOWN", "OTHER")
    ):
        return {
            "classification": "PURPOSE_VISIBLE_ONLY_IN_OTHER_EVIDENCE",
            "purpose_terms": [],
            "basis": "Existing transaction-specific human-reviewed category",
            "recipient_visible": bool(message),
        }
    return {
        "classification": "STILL_OPAQUE",
        "purpose_terms": [],
        "recipient_visible": "lopullinen saaja" in normalize_text(message),
        "limitation": "Recipient may be visible while purchase purpose remains unproven.",
    }
