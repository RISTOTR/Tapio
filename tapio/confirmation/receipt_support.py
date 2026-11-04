"""Receipt source facts can support suggestions, never human authority or tax treatment."""

import json
import re
from copy import deepcopy

from integrations.gmail.receipts import norm
from tapio.knowledge.models import digest

PURPOSE_TERMS = {
    "MAINTENANCE": ("car repair", "autohuolto", "auton korjaus", "katsastus"),
    "TRAVEL": ("bus ticket", "bussilippu", "matkalippu", "junamatka"),
    "INSURANCE": ("vakuutusmaksu", "insurance premium"),
    "SUBSCRIPTION": ("prepaid lataus", "prepaid top up"),
    "OTHER": ("apteekkiostos", "pharmacy purchase", "hammashoito"),
}


def purpose_category(candidate):
    text = " ".join(norm(f["value"]) for f in candidate["facts"] if f["field"] == "description")
    categories = {
        category
        for category, terms in PURPOSE_TERMS.items()
        if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)
    }
    return next(iter(categories)) if len(categories) == 1 else None


def integrate_receipt(card, receipt):
    card = deepcopy(card)
    card["receipt_evidence"] = receipt
    card["receipt_category_added"] = False
    card["pilot_tags"].append(receipt["status"])
    reasons = card["reasons"]
    if receipt["candidates"]:
        reasons.append(
            {
                "code": "RELATED_EMAIL_EVIDENCE",
                "explanation": (
                    "Read-only Gmail receipt evidence; candidate relationships "
                    "are not resolved purchases."
                ),
                "evidence_refs": [c["message_id"] for c in receipt["candidates"]],
            }
        )
    if receipt["status"] == "RECEIPT_MATCHED":
        candidate = receipt["candidates"][0]
        codes = ["RECEIPT_MATCHED"]
        if any(f["field"] == "merchant" for f in candidate["facts"]):
            codes.append("UNDERLYING_MERCHANT_IDENTIFIED")
        if "ORDER_REFERENCE_MATCH" in candidate["signals"]:
            codes.append("ORDER_REFERENCE_MATCH")
        category = purpose_category(candidate)
        if category:
            codes.append("RECEIPT_PURPOSE_TEXT")
        conflicts = []
        current = card["current_state"]
        existing = current.get("category") or card["suggestion"].get("category")
        if category and existing and existing != category:
            conflicts.append(
                "Receipt purpose category conflicts with existing human/source suggestion."
            )
        merchants = {norm(f["value"]) for f in candidate["facts"] if f["field"] == "merchant"}
        recipient = receipt["search"].get("merchant")
        if merchants and recipient and norm(recipient) not in merchants:
            conflicts.append(
                "Receipt merchant differs from bank recipient; review identity explicitly."
            )
        for document in card.get("document_evidence", []):
            vendor = document.get("document_summary", {}).get("vendor")
            if vendor and merchants and norm(vendor) not in merchants:
                conflicts.append("Receipt merchant differs from linked document vendor.")
        card["receipt_conflicts"] = conflicts
        if conflicts:
            card["warnings"].extend("RECEIPT_EVIDENCE_CONFLICT: " + c for c in conflicts)
            codes.append("RECEIPT_EVIDENCE_CONFLICT")
        elif category and current.get("authority", {}).get("category") != "HUMAN_CONFIRMED":
            card["receipt_category_added"] = not bool(card["suggestion"].get("category"))
            card["suggestion"]["category"] = category
        for code in codes:
            reasons.append(
                {
                    "code": code,
                    "explanation": (
                        "Explicit receipt evidence retained with Gmail message, source "
                        "location and matching signals. Category/context remain "
                        "suggestions only."
                    ),
                    "evidence_refs": [candidate["message_id"]],
                }
            )
        if not conflicts and (
            category or any(f["field"] == "description" for f in candidate["facts"])
        ):
            card["paytrail_purpose"] = "PURPOSE_VISIBLE"
        elif card.get("paytrail_purpose") == "STILL_OPAQUE" and not conflicts:
            card["paytrail_purpose"] = "PARTIAL_PURPOSE"
    # No receipt rule supplies business context, including a multi-context retailer.
    if card.get("paytrail_purpose") or card.get("multi_context"):
        card["suggestion"]["context"] = None
    card["pilot_tags"] = [
        t
        for t in card["pilot_tags"]
        if t not in {"BOTH", "CATEGORY_ONLY", "CONTEXT_ONLY", "ABSTENTION"}
        and not t.startswith("PAYTRAIL_")
    ]
    category, context = (card["suggestion"].get(f) for f in ("category", "context"))
    card["pilot_tags"].append(
        "BOTH"
        if category and context
        else "CATEGORY_ONLY"
        if category
        else "CONTEXT_ONLY"
        if context
        else "ABSTENTION"
    )
    if card.get("paytrail_purpose"):
        card["pilot_tags"].append("PAYTRAIL_" + card["paytrail_purpose"])
    if category or context:
        card["warnings"] = [
            w for w in card["warnings"] if not w.startswith("No supported suggestion")
        ]
    card["evidence_version"] = digest(
        {
            "receipt": receipt,
            "source": card["source_hash"],
            "suggestion": card["suggestion"],
            "documents": card.get("document_evidence", []),
        }
    )
    card["card_id"] = digest(card)[:32]
    return card


def receipt_fresh(card, root):
    receipt = card.get("receipt_evidence")
    if not receipt:
        return True
    try:
        stored = json.loads((root / "receipts" / (card["transaction"]["id"] + ".json")).read_text())
        if digest(stored) != digest(receipt):
            return False
        # A refreshed local Gmail evidence version invalidates the frozen card.
        # We do not silently fetch new mail or replace a receipt during a review.
        from integrations.gmail.auth import GmailSettings

        cache = GmailSettings().cache
        for candidate in receipt["candidates"] + receipt["insufficient"]:
            message_id = candidate["message_id"]
            pointer = json.loads((cache / ("message-" + message_id + ".json")).read_text())
            current = json.loads((cache / (pointer["key"] + ".json")).read_text())
            if any(f["content_hash"] != current["content_hash"] for f in candidate["facts"]):
                return False
        return True
    except (OSError, ValueError, KeyError):
        return False
