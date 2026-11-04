"""Explicit candidate concepts; reusable category evidence never creates context authority."""

import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Literal

from pydantic import Field

from data_pipeline.labels.merchant_policy import ambiguous_merchant
from integrations.gmail.receipts import norm
from tapio.knowledge.category_mappings import derive_mappings
from tapio.knowledge.models import Typed, digest

ConceptName = Literal[
    "PHARMACY",
    "CAFE",
    "BAR",
    "ALCOHOL_RETAILER",
    "AIRLINE",
    "TRAIN_OPERATOR",
    "AIRPORT_FOOD_SERVICE",
    "DEPARTMENT_STORE",
    "HOME_GOODS",
    "GOVERNMENT_AGENCY",
    "GROCERY_RETAILER",
    "RESTAURANT",
    "VEHICLE_INSPECTION",
    "VEHICLE_SERVICE",
    "INSURANCE_COMPANY",
    "BUS_OPERATOR",
    "ELECTRICITY_SUPPLIER",
    "HARDWARE_RETAILER",
    "GENERAL_RETAILER",
    "RECREATION_PERMIT",
]
# These are candidate interpretation seeds, not accepted facts or live classification rules.
SEEDS = [
    ("alepa", "GROCERY_RETAILER", "CHAIN_PREFIX"),
    ("k-supermarket", "GROCERY_RETAILER", "CHAIN_PREFIX"),
    ("k-market", "GROCERY_RETAILER", "CHAIN_PREFIX"),
    ("s-market", "GROCERY_RETAILER", "CHAIN_PREFIX"),
    ("lidl", "GROCERY_RETAILER", "CHAIN_PREFIX"),
    ("ravintola", "RESTAURANT", "TOKEN"),
    ("restaurant", "RESTAURANT", "TOKEN"),
    ("restaurante", "RESTAURANT", "TOKEN"),
    ("kahvila", "RESTAURANT", "TOKEN"),
    ("a-katsastus", "VEHICLE_INSPECTION", "CHAIN_PREFIX"),
    ("katsastus", "VEHICLE_INSPECTION", "TOKEN"),
    ("autohuolto", "VEHICLE_SERVICE", "TOKEN"),
    ("lähitapiola", "INSURANCE_COMPANY", "CHAIN_PREFIX"),
    ("onnibus", "BUS_OPERATOR", "CHAIN_PREFIX"),
    ("vattenfall", "ELECTRICITY_SUPPLIER", "CHAIN_PREFIX"),
    ("tokmanni", "GENERAL_RETAILER", "CHAIN_PREFIX"),
    ("k-rauta", "HARDWARE_RETAILER", "CHAIN_PREFIX"),
    ("eräluvat", "RECREATION_PERMIT", "TOKEN"),
]


def words(text):
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", norm(text)) if not unicodedata.combining(c)
    )
    folded = re.sub(r"^(?:vfi|sumup|izettle)\s*\*\s*", "", folded)
    return " ".join(re.sub(r"[^\w-]+", " ", folded).split())


def matches(term, mode, text):
    term, text = words(term), words(text)
    if not term or term == "paytrail":
        return False
    if mode == "EXACT_IDENTITY":
        return term == text
    if mode == "CHAIN_PREFIX":
        return bool(re.match(re.escape(term) + r"(?:\b|$)", text))
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))


def identity(tx):
    processor = "paytrail" in norm(
        tx.get("payment_intermediary") or tx.get("normalized_counterparty", "")
    )
    return (
        (tx.get("ultimate_recipient") or "")
        if processor
        else (tx.get("normalized_counterparty") or tx.get("raw_counterparty") or "")
    )


class ConceptCandidate(Typed):
    id: str
    kind: Literal[
        "MERCHANT_TYPE",
        "VOCABULARY_CONCEPT",
        "RECIPIENT_CONCEPT",
        "BUSINESS_TYPE",
        "PURCHASE_PURPOSE_CONCEPT",
    ]
    term: str = Field(min_length=2, max_length=120)
    match_mode: Literal["TOKEN", "CHAIN_PREFIX", "EXACT_IDENTITY"]
    concept: ConceptName
    authority: Literal["SUGGESTED"] = "SUGGESTED"
    support: list[dict] = Field(min_length=1)
    observed_labels: dict
    limitations: str = (
        "Candidate only. No reusable authority until explicit concept review; context is blocked."
    )


def generate_candidates(tables, states):
    reviews = {r["transaction_id"]: r for r in tables["transaction_label_reviews"]}
    revisions = defaultdict(list)
    for row in tables.get("confirmation_revisions", []):
        revisions[row["transaction_id"]].append(row)
    groups = defaultdict(dict)
    for tx in tables["transactions"]:
        state = states[tx["id"]][0]
        if state.get("authority", {}).get("category") != "HUMAN_CONFIRMED":
            continue
        value = identity(tx)
        if not value or words(value) == "paytrail oyj":
            continue
        rows = sorted(revisions[tx["id"]], key=lambda r: r["sequence"])
        source = next(
            (r for r in reversed(rows) if "category" in r["fields"]), None
        ) or reviews.get(tx["id"])
        if not source:
            continue
        notes = [r["audit"].get("correction_reason", "") for r in rows]
        for term, concept, mode in SEEDS:
            found = matches(term, mode, value)
            note = next((n for n in notes if matches(term, "TOKEN", n)), "")
            if not found and not note:
                continue
            processor = "paytrail" in norm(tx.get("normalized_counterparty", ""))
            kind = (
                "VOCABULARY_CONCEPT"
                if mode == "TOKEN" or note
                else "RECIPIENT_CONCEPT"
                if processor
                else "MERCHANT_TYPE"
            )
            key = kind, term, mode, concept
            groups[key][tx["id"]] = {
                "transaction_id": tx["id"],
                "identity": value,
                "category": state["category"],
                "context": state.get("context"),
                "transaction_hash": digest(tx),
                "review_id": source["id"],
                "review_hash": digest(source),
                "note": note[:500],
                "source_type": "confirmation_revisions"
                if "sequence" in source
                else "transaction_label_reviews",
            }
    candidates = []
    for (kind, term, mode, concept), observations in sorted(groups.items()):
        support = sorted(observations.values(), key=lambda r: r["transaction_id"])
        if len(support) < 2 and not any(s["note"] for s in support):
            continue
        value = {
            "kind": kind,
            "term": term,
            "match_mode": mode,
            "concept": concept,
            "support": support,
            "observed_labels": {
                "category": dict(Counter(s["category"] for s in support)),
                "context": dict(Counter(str(s["context"]) for s in support)),
            },
        }
        candidates.append(ConceptCandidate(id=digest(value)[:24], **value).model_dump(mode="json"))
    return candidates[:50]


def apply_concepts(card, tx, candidates, decisions, *, exclude_identity=None, mappings=None):
    card = deepcopy(card)
    mappings = derive_mappings(candidates) if mappings is None else mappings
    used, blocked = [], []
    proposals = set()
    grouped = defaultdict(list)
    target_identity = identity(tx)
    receipt = card.get("receipt_evidence", {})
    if (
        not target_identity
        and receipt.get("status") == "RECEIPT_MATCHED"
        and not card.get("receipt_conflicts")
    ):
        names = {
            f["value"]
            for c in receipt.get("candidates", [])
            for f in c["facts"]
            if f["field"] == "merchant"
        }
        if len(names) == 1:
            target_identity = next(iter(names))
    for candidate in candidates:
        if matches(candidate["term"], candidate["match_mode"], target_identity):
            grouped[(candidate["term"], candidate["match_mode"])].append(candidate)
    for rows in grouped.values():
        confirmed = [
            (c, decisions.get(c["id"], {}))
            for c in rows
            if decisions.get(c["id"], {}).get("action") in {"CONFIRM_CONCEPT", "EDIT_CONCEPT"}
        ]
        concepts = {d.get("concept", c["concept"]) for c, d in confirmed}
        if len(concepts) > 1:
            blocked.append("CONTRADICTORY_CONCEPTS")
            continue
        for candidate, decision in confirmed:
            mapping = next(
                (
                    m
                    for m in mappings
                    if m["candidate_id"] == candidate["id"]
                    and m["concept"] == decision.get("concept", candidate["concept"])
                ),
                None,
            )
            if not mapping or not mapping["eligible"] or mapping["conflicts"]:
                blocked.extend(mapping["blocked"] if mapping else ["NO_SUPPORTED_CATEGORY_MAPPING"])
                continue
            support = [
                s
                for s in mapping["support"]
                if s["transaction_id"] != tx["id"]
                and (exclude_identity is None or words(s["identity"]) != words(exclude_identity))
            ]
            category = mapping["category"]
            if len(support) < 2 or {s["category"] for s in support} != {category}:
                blocked.append("CONFLICTING_OR_INSUFFICIENT_CONFIRMED_CATEGORY_HISTORY")
                continue
            receipt = card.get("receipt_evidence", {})
            if receipt.get("status") in {
                "MULTIPLE_RECEIPTS",
                "RECEIPT_CANDIDATE",
                "INSUFFICIENT_RECEIPT_EVIDENCE",
            } or card.get("receipt_conflicts"):
                blocked.append("CONFLICTING_PROCESSOR_EVIDENCE")
                continue
            if decision.get("concept", candidate["concept"]) == "HARDWARE_RETAILER" and not (
                card.get("receipt_category_added")
                or any(d.get("status") == "CONFIRMED" for d in card.get("document_evidence", []))
            ):
                blocked.append("INSUFFICIENT_TRANSACTION_SPECIFIC_EVIDENCE")
                continue
            # Entity identity alone cannot establish the purpose of a specific purchase.
            concept = decision.get("concept", candidate["concept"])
            if concept in {
                "AIRLINE",
                "AIRPORT_FOOD_SERVICE",
                "DEPARTMENT_STORE",
                "GENERAL_RETAILER",
                "HOME_GOODS",
            } and not (
                card.get("receipt_category_added")
                and card["suggestion"].get("category") == category
                and not card.get("receipt_conflicts")
            ):
                blocked.append("PURCHASE_PURPOSE_SUPPORT_REQUIRED")
                continue
            if card["current_state"].get("authority", {}).get("category") == "HUMAN_CONFIRMED":
                continue
            proposals.add(category)
            used.append(
                {
                    "candidate_id": candidate["id"],
                    "term": candidate["term"],
                    "concept": decision.get("concept", candidate["concept"]),
                    "kind": candidate["kind"],
                    "authority": "HUMAN_CONFIRMED",
                    "confirmation_id": decision["id"],
                    "category_mapping": mapping,
                    "entity_support_level": "ENTITY_TYPE_SUPPORT",
                    "purchase_support_level": "PURCHASE_PURPOSE_SUPPORT",
                    "support": support,
                }
            )
    current = card["suggestion"].get("category")
    if len(proposals) > 1 or (current and proposals and current not in proposals):
        blocked.append("CONFLICTING_CATEGORY_EVIDENCE")
    elif len(proposals) == 1 and not blocked:
        card["suggestion"]["category"] = next(iter(proposals))
        if card.get("paytrail_purpose") == "STILL_OPAQUE":
            card["paytrail_purpose"] = "PARTIAL_PURPOSE"
    multi = ambiguous_merchant(card["transaction"]["merchant"]) or card.get("multi_context")
    if multi:
        card["suggestion"]["context"] = None
    context_reason = (
        "MULTI_CONTEXT_MERCHANT" if multi else "INSUFFICIENT_TRANSACTION_SPECIFIC_EVIDENCE"
    )
    card["concept_candidates"] = [
        {"id": c["id"], "term": c["term"], "concept": c["concept"], "authority": "SUGGESTED"}
        for rows in grouped.values()
        for c in rows
        if c["id"] not in decisions
    ]
    card["semantic_category_used"] = bool(
        used and not blocked and proposals and card["suggestion"].get("category") in proposals
    )
    card["semantic_concepts"] = used
    card["blocked_generalizations"] = sorted(set(blocked + [context_reason]))
    if used:
        for code in (
            "SEMANTIC_CONCEPT_MATCH",
            "HUMAN_CONFIRMED_CONCEPT",
            "CONCEPT_CATEGORY_MAPPING",
            "RECIPIENT_CONCEPT_MATCH"
            if "paytrail" in norm(tx.get("normalized_counterparty", ""))
            else "VOCABULARY_CONCEPT_MATCH",
        ):
            card["reasons"].append(
                {
                    "code": code,
                    "explanation": (
                        "Explicit concept review and agreeing prior category observations "
                        "support only a category suggestion."
                    ),
                    "evidence_refs": [c["confirmation_id"] for c in used],
                }
            )
    card["reasons"].append(
        {
            "code": "CONTEXT_GENERALIZATION_BLOCKED",
            "explanation": context_reason
            + ": no context is inferred from semantic type or vocabulary.",
            "evidence_refs": [],
        }
    )
    card["semantic_category_added"] = bool(not current and card["suggestion"].get("category"))
    if "pilot_tags" in card:
        category, context = (card["suggestion"][k] for k in ("category", "context"))
        tags = [
            t
            for t in card["pilot_tags"]
            if t
            not in {
                "BOTH",
                "CATEGORY_ONLY",
                "CONTEXT_ONLY",
                "ABSTENTION",
                "SEMANTIC_GENERALIZATION",
            }
            and not t.startswith("PAYTRAIL_")
        ]
        tags.append(
            "BOTH"
            if category and context
            else "CATEGORY_ONLY"
            if category
            else "CONTEXT_ONLY"
            if context
            else "ABSTENTION"
        )
        if card.get("paytrail_purpose"):
            tags.append("PAYTRAIL_" + card["paytrail_purpose"])
        if card["semantic_category_used"]:
            tags.append("SEMANTIC_GENERALIZATION")
        card["pilot_tags"] = tags
        if category or context:
            card["warnings"] = [
                w
                for w in card.get("warnings", [])
                if w != "No supported suggestion is available. Use CHANGE or SKIP."
            ]
    card["card_id"] = digest(card)[:32]
    return card
