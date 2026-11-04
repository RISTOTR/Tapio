"""Explainable review effort planning. Suggestions never constitute human decisions."""

from collections import Counter, defaultdict
from copy import deepcopy

from tapio.knowledge.models import digest

FIELDS = ("category", "context")
DEFAULT_REVIEW_BUDGET = 10


def unresolved(card):
    state = card["current_state"]
    return [
        f
        for f in FIELDS
        if state.get("authority", {}).get(f) != "HUMAN_CONFIRMED" or state.get(f) is None
    ]


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
        hard = hard or "TAX" in warnings or "CONFLICT" in warnings
        opaque = c.get("paytrail_purpose") == "STILL_OPAQUE" or not key
        rules = c.get("user_rules", [])
        semantic = c.get("semantic_concepts", []) if c.get("semantic_category_used") else []
        proposal = {}
        basis = None
        reason = "INSUFFICIENT_EVIDENCE"
        if opaque:
            reason = "PROCESSOR_AMBIGUOUS" if c.get("paytrail_purpose") else reason
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
                reason = "CONFLICTING_HISTORY"
            proposal = {
                f: v for f, v in proposal.items() if v and v != "UNKNOWN" and f in unresolved(c)
            }
        if not proposal and reason == "INSUFFICIENT_EVIDENCE" and not hard and not opaque:
            reason = "GENUINELY_NOVEL" if not prior else "INSUFFICIENT_EVIDENCE"
            if repeats[key] > 1:
                reason = "REPEATED_IDENTICAL_PATTERN"
        components = {}
        if not prior:
            components["unseen_entity"] = 5
        if conflicts or hard:
            components["conflicting_evidence"] = 5
        if c.get("multi_context") or "context" in conflicts:
            components["context_boundary"] = 4
        if c.get("paytrail_purpose") and not prior:
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
            "why_review": "Explicit human confirmation required"
            if proposal
            else "Unresolved evidence or context requires individual judgment",
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
        if len(members) < 2:
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
        "summary": {
            "total_pending": len(cards),
            "groupable_transactions": len(covered),
            "groups": len(groups),
            "individual_reviews_remaining": len(individuals),
            "genuinely_novel_individuals": sum(
                not c["review_analysis"]["history"] for c in individuals
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
