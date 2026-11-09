"""Explainable review effort planning. Suggestions never constitute human decisions."""

from collections import Counter, defaultdict
from copy import deepcopy

from integrations.gmail.receipts import norm
from tapio.confirmation.receipt_support import purpose_category
from tapio.knowledge.models import digest

FIELDS = ("category", "context")
DEFAULT_REVIEW_BUDGET = 5


def unresolved(card):
    state = card["current_state"]
    return [
        f
        for f in FIELDS
        if state.get("authority", {}).get(f) != "HUMAN_CONFIRMED" or state.get(f) is None
    ]


def novelty_audit(card):
    """Explain recognition separately from eligibility to reuse a label proposal."""
    a = card["review_analysis"]
    prior = a["history"]
    name = card.get("identity_resolution", {}).get("matched_identity", card["identity_key"])
    alias = any(norm(r.get("identity", r["identity_key"])) != norm(name) for r in prior)
    reason = (
        "PROCESSOR_AMBIGUOUS"
        if a["reason"] == "PROCESSOR_AMBIGUOUS"
        else "CONFLICTING_HISTORY"
        if a["conflicts"] or a["reason"] == "CONFLICTING_HISTORY"
        else "FALSE_NOVEL_ALIAS"
        if alias
        else "FALSE_NOVEL_USER_RULE"
        if card.get("user_rules")
        else "FALSE_NOVEL_SEMANTIC_RULE"
        if card.get("semantic_category_used")
        else "KNOWN_ENTITY_NEW_PURPOSE"
        if a["reason"] == "KNOWN_ENTITY_NEW_PURPOSE"
        else "FALSE_NOVEL_EXACT_HISTORY"
        if prior
        else "TRUE_NOVEL"
        if a["reason"] in {"GENUINELY_NOVEL", "REPEATED_IDENTICAL_PATTERN"}
        else "INSUFFICIENT_EVIDENCE"
    )
    return {
        "transaction_id": card["transaction"]["id"],
        "class": a.get("novelty_transition", reason),
        "recognition_reason": a["reason"],
        "proposal": a["proposal"],
        "prior_review_ids": sorted({r.get("review_id", "") for r in prior}),
        "identity_resolution": card.get("identity_resolution"),
        "purpose_review_required": bool(card.get("purpose_review_required")),
    }


def analyze(cards, history, budget=DEFAULT_REVIEW_BUDGET):
    """Use distinct current human observations, never repeated revision counts."""
    cards = deepcopy(cards)
    by_entity = defaultdict(list)
    for observation in history:
        by_entity[observation["identity_key"]].append(observation)
    repeats = Counter(c["identity_key"] for c in cards if c["identity_key"])
    buckets = defaultdict(list)
    for c in cards:
        key = c["identity_key"]
        prior = [h for h in by_entity[key] if h["transaction_id"] != c["transaction"]["id"]]
        values = {f: {h["value"] for h in prior if h["field"] == f} for f in FIELDS}
        support = {f: [h for h in prior if h["field"] == f] for f in FIELDS}
        stable = {
            f: next(iter(values[f]))
            for f in FIELDS
            if len({h["transaction_id"] for h in support[f]}) >= 3
            and len(values[f]) == 1
            and "UNKNOWN" not in values[f]
        }
        if (
            len(stable) == 2
            and len(
                {h["transaction_id"] for h in support["category"]}
                & {h["transaction_id"] for h in support["context"]}
            )
            < 3
        ):
            stable.pop("context")
        conflicts = [f for f in FIELDS if len(values[f]) > 1 or "UNKNOWN" in values[f]]
        hard = bool(
            c.get("receipt_conflicts")
            or c.get("user_rule_conflicts")
            or c.get("conflicting_knowledge")
            or c.get("document_evidence")
            or c.get("receipt_evidence", {}).get("status")
            in {"MULTIPLE_RECEIPTS", "RECEIPT_CANDIDATE", "INSUFFICIENT_RECEIPT_EVIDENCE"}
        )
        warnings = " ".join(c.get("warnings", [])).upper()
        hard = hard or "TAX_AMBIGUITY" in warnings or "CONFLICT" in warnings
        hard = hard or bool(c.get("tax_ambiguity") or c.get("document_conflicts"))
        hard = hard or any("CONFLICT" in code for code in c.get("blocked_generalizations", []))
        opaque = (
            c.get("paytrail_purpose") == "STILL_OPAQUE"
            or not key
            or key in {"stripe", "mobilepay", "paytrail", "paytrail oyj"}
        )
        rules = c.get("user_rules", [])
        semantic = c.get("semantic_concepts", []) if c.get("semantic_category_used") else []
        known_semantic = c.get("known_semantic_concepts", []) or c.get("semantic_concepts", [])
        known = bool(
            prior
            or rules
            or known_semantic
            or "HUMAN_CONFIRMED" in c["current_state"].get("authority", {}).values()
        )
        proposal = {}
        basis = None
        reason = "INSUFFICIENT_EVIDENCE"
        if opaque:
            reason = "PROCESSOR_AMBIGUOUS" if c.get("paytrail_purpose") or key else reason
        elif hard or "category" in conflicts:
            reason = "CONFLICTING_HISTORY" if conflicts else "INSUFFICIENT_EVIDENCE"
        else:
            if rules:
                basis = ("USER_RULE", tuple(sorted(r["event_id"] for r in rules)))
                proposal = {f: c["suggestion"].get(f) for f in unresolved(c)}
                reason = "ACTIVE_USER_RULE_MATCH"
            elif stable:
                basis = ("EXACT", key)
                proposal = {f: stable[f] for f in unresolved(c) if f in stable}
                reason = "ALREADY_KNOWN_EXACT_PATTERN"
            elif semantic:
                basis = ("SEMANTIC", tuple(sorted(digest(s) for s in semantic)))
                proposal = {"category": c["suggestion"].get("category")}
                reason = "SEMANTIC_RULE_MATCH"
            if c.get("multi_context") or "context" in conflicts:
                proposal.pop("context", None)
                reason = "HIGH_RISK_CONTEXT"
            # Any transaction-specific competing suggestion splits the transaction out.
            if any(c["suggestion"].get(f) not in (None, v) for f, v in proposal.items()):
                proposal = {}
                reason = "KNOWN_ENTITY_NEW_PURPOSE"
            receipt = c.get("receipt_evidence", {})
            if receipt.get("status") == "RECEIPT_MATCHED" and receipt.get("candidates"):
                receipt_category = purpose_category(receipt["candidates"][0])
                if receipt_category and proposal.get("category") not in (None, receipt_category):
                    proposal = {}
                    reason = "INSUFFICIENT_EVIDENCE"
            proposal = {
                f: v for f, v in proposal.items() if v and v != "UNKNOWN" and f in unresolved(c)
            }
            if c.get("purpose_review_required"):
                proposal = {}
                reason = "KNOWN_ENTITY_NEW_PURPOSE"
        if not proposal and reason == "INSUFFICIENT_EVIDENCE" and not hard and not opaque:
            reason = "GENUINELY_NOVEL" if not known else "INSUFFICIENT_EVIDENCE"
            if known_semantic and "PURCHASE_PURPOSE_SUPPORT_REQUIRED" in c.get(
                "blocked_generalizations", []
            ):
                reason = "KNOWN_ENTITY_NEW_PURPOSE"
            elif repeats[key] > 1 and not known:
                reason = "REPEATED_IDENTICAL_PATTERN"
        components = {}
        if not known:
            components["unseen_entity"] = 5
        if conflicts or hard:
            components["conflicting_evidence"] = 5
        if c.get("multi_context") or "context" in conflicts:
            components["context_boundary"] = 4
        if c.get("paytrail_purpose") and not known:
            components["new_processor_recipient"] = 4
        if c.get("concept_candidates") and not semantic:
            components["new_semantic_concept"] = 3
        if c.get("blocked_generalizations"):
            components["rule_boundary"] = 3
        if prior:
            components["repeated_entity"] = 1
        if len(stable) == 2 and proposal:
            components["stable_exact_pattern"] = -5
        if rules and proposal:
            components["active_user_rule"] = -5
        if repeats[key] > 1:
            components["duplicate_pending_entity"] = -4
        c["review_analysis"] = {
            "reason": reason,
            "proposal": proposal,
            "novelty_components": components,
            "novelty_score": sum(components.values()),
            "conflicts": conflicts,
            "history": prior,
            "basis": basis,
            "known_entity": known,
            "entity_status": "KNOWN_ENTITY" if known else "UNKNOWN_ENTITY",
            "why_review": (
                "Processor opacity: the actual recipient or purchase is not established."
                if opaque
                else "Conflicting prior human history or transaction evidence must be reconciled."
                if conflicts or hard
                else "Multi-context ambiguity: this entity is used in more than one context."
                if c.get("multi_context")
                else "New purchase purpose for a known entity needs transaction-specific evidence."
                if reason == "KNOWN_ENTITY_NEW_PURPOSE"
                else "Genuinely unseen entity/purpose: no supporting human decision exists."
                if not known
                else "Rule boundary case: " + ", ".join(c["blocked_generalizations"])
                if c.get("blocked_generalizations") and not prior
                else "Missing evidence: supported fields are "
                + ", ".join(sorted(proposal))
                + "; remaining fields need independent support."
                if proposal and set(proposal) != set(unresolved(c))
                else "Explicit confirmation of supported fields; no new judgment required."
                if proposal
                else f"Missing evidence: {len({h['transaction_id'] for h in prior})} prior reviewed"
                " "
                "transactions; three consistent observations or an applicable rule are required."
            ),
        }
        if proposal:
            c["suggestion"].update(proposal)
            # Different purpose evidence, signs, or pending fields must never share a group.
            purpose = c.get("purpose_basis", {})
            partition = (
                basis,
                tuple(sorted(proposal.items())),
                str(c["transaction"]["amount"]).startswith("-"),
                digest(purpose)
                if purpose.get("classification") not in (None, "PURPOSE_NOT_VISIBLE")
                else None,
            )
            buckets[partition].append(c)
    groups = []
    covered = {}
    for members in buckets.values():
        if len(members) < 2 and set(members[0]["review_analysis"]["proposal"]) != set(
            unresolved(members[0])
        ):
            continue
        members.sort(key=lambda c: c["transaction"]["id"])
        fields = members[0]["review_analysis"]["proposal"]
        group = {
            "card_ids": [c["card_id"] for c in members],
            "fields": fields,
            "reason": members[0]["review_analysis"]["reason"],
            "entities": sorted({c["identity_key"] for c in members}),
            "transaction_ids": [c["transaction"]["id"] for c in members],
            "date_range": [
                min(c["transaction"]["date"] for c in members),
                max(c["transaction"]["date"] for c in members),
            ],
            "amounts": [c["transaction"]["amount"] for c in members],
            "conflict_status": "No conflicts in selected fields; other fields untouched",
            "evidence": [c["review_analysis"] for c in members],
        }
        group["id"] = digest(group)[:32]
        groups.append(group)
        covered.update({c["card_id"]: set(fields) for c in members})
    individuals = [c for c in cards if set(unresolved(c)) - covered.get(c["card_id"], set())]
    individuals.sort(key=lambda c: (-c["review_analysis"]["novelty_score"], c["card_id"]))
    # Diversify the first budget by evidence problem, while retaining every unresolved item.
    seen, informative, deferred = set(), [], []
    for c in individuals:
        problem = (
            c["identity_key"],
            c["review_analysis"]["reason"],
            digest(c.get("purpose_basis")),
            digest(c.get("receipt_evidence")),
        )
        (deferred if problem in seen else informative).append(c)
        seen.add(problem)
    individuals = informative + deferred
    full = sum(set(unresolved(c)) <= covered.get(c["card_id"], set()) for c in cards)
    before = sum(len(unresolved(c)) + 2 for c in cards)
    after = 2 * len(groups) + sum(
        len(set(unresolved(c)) - covered.get(c["card_id"], set())) + 2 for c in individuals
    )
    return {
        "cards": cards,
        "groups": groups,
        "individual_ids": [c["card_id"] for c in individuals],
        "minimal_review_ids": [c["card_id"] for c in individuals[:budget]],
        "budget": budget,
        "novelty_audit": [novelty_audit(c) for c in cards],
        "summary": {
            "total_pending": len(cards),
            "groupable_transactions": len(covered),
            "groups": len(groups),
            "multi_transaction_groups": sum(len(g["card_ids"]) > 1 for g in groups),
            "known_single_confirmations": sum(len(g["card_ids"]) == 1 for g in groups),
            "individual_reviews_remaining": len(individuals),
            "genuinely_novel_individuals": sum(
                c["review_analysis"]["reason"] == "GENUINELY_NOVEL" for c in individuals
            ),
            "truly_novel_transactions": sum(
                novelty_audit(c)["class"] == "TRUE_NOVEL" for c in individuals
            ),
            "other_ambiguous_individuals": sum(
                novelty_audit(c)["class"] != "TRUE_NOVEL" for c in individuals
            ),
            "cards_avoided": max(0, full - len(groups)),
            "REPEATED_CONFIRMATION_AVOIDED": sum(len(g["card_ids"]) - 1 for g in groups),
            "manual_actions_before": before,
            "manual_actions_after": after,
            "estimated_actions_saved": before - after,
            "estimated_reduction_percent": round(100 * (before - after) / before, 1)
            if before
            else 0,
            "action_assumption": "One selection per unresolved field, one preview, one apply; "
            "groups require one preview and one apply. Includes residual fields.",
            "reason_counts": dict(Counter(c["review_analysis"]["reason"] for c in cards)),
        },
    }
