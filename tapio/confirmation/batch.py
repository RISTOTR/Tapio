"""Deterministic diverse-batch preparation; no classification writes or model calls."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal

from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.knowledge.bank_evidence import document_candidates, purpose_evidence
from tapio.knowledge.models import digest
from tapio.suggestions.full_fields import FullFieldGenerator, message_recipient


def prepare_candidates(tables, snapshot, observed_at, states):
    txs = tables["transactions"]
    reviews = {r["transaction_id"]: r for r in tables["transaction_label_reviews"]}
    confirmed = {r["transaction_id"] for r in tables.get("confirmation_revisions", [])}
    generator = FullFieldGenerator(snapshot, txs, list(reviews.values()), observed_at)
    reversal_ids = set()
    for r in tables.get("transaction_reversal_candidates", []):
        reversal_ids.update(str(r[k]) for k in ("debit_id", "credit_id") if r.get(k))
    candidates = []
    for tx in sorted(txs, key=lambda t: (t["booking_date"], t["id"])):
        review = reviews.get(tx["id"])
        if (
            not tx.get("source_transaction_id")
            or tx["id"] in confirmed
            or (review and review["review_status"] == "REVIEWED")
            or abs(Decimal(tx["amount"])) == Decimal("588.07")
            or tx["id"] in reversal_ids
        ):
            continue
        signals = generator.signals(tx)
        if signals["ambiguous_links"]:
            continue
        card = generator.card(tx, signals).model_dump(mode="json")
        merchant = card["transaction"]["merchant"]
        multi = bool(ambiguous_merchant(merchant)) or len(signals["contexts"]) > 1
        if multi:
            card["suggestion"]["context"] = None
        links = document_candidates(
            tx, tables.get("invoices", []), tables.get("transaction_invoice_allocations", [])
        )
        invoices = {i["id"]: i for i in tables.get("invoices", [])}
        for link in links:
            invoice = invoices[link["invoice_id"]]
            link["document_summary"] = {
                k: invoice.get(k)
                for k in ("vendor", "invoice_date", "total_eur", "invoice_number", "reference")
            }
        purpose = purpose_evidence(tx, links=links)
        paytrail = merchant == "Paytrail Oyj"
        purpose_class = None
        if paytrail:
            if purpose["classification"] in {
                "PURPOSE_VISIBLE_IN_BANK_SOURCE",
                "PURPOSE_VISIBLE_ONLY_IN_DOCUMENT",
            }:
                purpose_class = "PURPOSE_VISIBLE"
            elif message_recipient(tx) and card["suggestion"]["category"] not in (
                None,
                "UNKNOWN",
                "OTHER",
            ):
                purpose_class = "PARTIAL_PURPOSE"
            else:
                purpose_class = "STILL_OPAQUE"
                card["suggestion"]["category"] = None
            card["suggestion"]["context"] = None
        tags = []
        category, context = (card["suggestion"][k] for k in ("category", "context"))
        tags.append(
            "BOTH"
            if category and context
            else "CATEGORY_ONLY"
            if category
            else "CONTEXT_ONLY"
            if context
            else "ABSTENTION"
        )
        if paytrail:
            tags.append("PAYTRAIL_" + purpose_class)
        if multi:
            tags.append("MULTI_CONTEXT")
        if ambiguous_merchant(merchant) and not paytrail:
            tags.append("AMBIGUOUS_RETAILER")
        if links:
            tags.append("DOCUMENT")
        if card["conflicting_knowledge"]:
            tags.append("CONFLICT")
        codes = {r["code"] for r in card["reasons"]}
        if "RECURRING_PATTERN" in codes:
            tags.append("RECURRING")
        if "SOURCE_TEXT_MATCH" in codes:
            tags.append("SOURCE_TEXT")
        card.update(
            source_stable_id=tx["source_transaction_id"],
            source_hash=digest(tx),
            initial_state_hash=states[tx["id"]][1],
            current_state=states[tx["id"]][0],
            source_messages={
                **{k: (tx.get("raw_source") or {}).get(k) for k in ("Selitys", "Viesti")},
                "Recipient": tx.get("ultimate_recipient"),
                "Processor": tx.get("payment_intermediary"),
                "Reference": tx.get("reference"),
            },
            document_evidence=links,
            pilot_tags=tags,
            multi_context=multi,
            paytrail_purpose=purpose_class,
            purpose_basis=purpose,
        )
        if multi:
            card["warnings"].append(
                "MULTI_CONTEXT_MERCHANT: merchant identity cannot establish context."
            )
        if paytrail:
            card["warnings"].append(
                "Recipient visibility is not proof of purchase purpose; "
                "no processor-wide classification."
            )
        if not category and not context:
            card["warnings"].append("No supported suggestion is available. Use CHANGE or SKIP.")
        card["card_id"] = digest({"card": card, "contract": "GENERAL_CONFIRMATION_V1"})[:32]
        candidates.append(card)
    return candidates


def freeze_batch(candidates, knowledge_hash, source_fingerprints, baseline_revisions, size=20):
    if not 15 <= size <= 25 or len(candidates) < size:
        raise ValueError("INSUFFICIENT_BOUNDED_BATCH")
    chosen = []
    # Scarce document and partial-field cases first; overlap counts toward diversity.
    for tag, count in [
        ("DOCUMENT", 2),
        ("CONTEXT_ONLY", 2),
        ("AMBIGUOUS_RETAILER", 2),
        ("PAYTRAIL_PURPOSE_VISIBLE", 2),
        ("PAYTRAIL_PARTIAL_PURPOSE", 3),
        ("PAYTRAIL_STILL_OPAQUE", 2),
        ("MULTI_CONTEXT", 3),
        ("CONFLICT", 2),
        ("CATEGORY_ONLY", 3),
        ("BOTH", 3),
        ("SOURCE_TEXT", 2),
        ("RECURRING", 2),
        ("ABSTENTION", 3),
    ]:
        for card in candidates:
            if len(chosen) >= size or sum(tag in c["pilot_tags"] for c in chosen) >= count:
                break
            if tag in card["pilot_tags"] and card not in chosen:
                chosen.append(card)
    for card in candidates:
        if len(chosen) == size:
            break
        if card not in chosen:
            chosen.append(card)
    chosen = deepcopy(chosen)
    batch = {
        "version": "GENERAL_CONFIRMATION_V1",
        "cards": chosen,
        "cards_hash": digest(chosen),
        "knowledge_hash": knowledge_hash,
        "source_fingerprints": source_fingerprints,
        "baseline_revisions": baseline_revisions,
        "available_composition": dict(Counter(t for c in candidates for t in c["pilot_tags"])),
        "composition": dict(Counter(t for c in chosen for t in c["pilot_tags"])),
    }
    batch["batch_id"] = "GENERAL-" + digest(batch)[:16]
    return batch
