"""Read-only historical exit checks and explicitly defined review-effort metrics."""

from collections import Counter

from tapio.confirmation.service import review_state_data


def authoritative_states(tables):
    legacy = {r["transaction_id"]: r for r in tables.get("transaction_label_reviews", [])}
    latest = {}
    for r in sorted(tables.get("confirmation_revisions", []), key=lambda r: r["sequence"]):
        latest[r["transaction_id"]] = r
    return {
        t["id"]: review_state_data(t, legacy.get(t["id"]), latest.get(t["id"]))
        for t in tables["transactions"]
    }


def review_metrics(tables):
    """Rates use distinct transactions with revision events, not legacy imports."""
    revisions = tables.get("confirmation_revisions", [])
    counts = Counter(r["transaction_id"] for r in revisions)
    first = {}
    for r in sorted(revisions, key=lambda r: r["sequence"]):
        first.setdefault(r["transaction_id"], r)
    groups = {}
    routes = Counter()
    for r in first.values():
        group = r["audit"].get("group_confirmation")
        if group:
            groups[group["group_id"]] = group
            routes["grouped" if len(group["transaction_ids"]) > 1 else "quick"] += 1
        else:
            routes["individual"] += 1
    reviewed = len(first)
    states = authoritative_states(tables)
    complete = sum(
        all(
            s.get("authority", {}).get(f) == "HUMAN_CONFIRMED" and s.get(f) is not None
            for f in ("category", "context")
        )
        for s, _ in states.values()
    )
    group_members = sum(len(g["transaction_ids"]) for g in groups.values())
    # Four actions per two-field individual vs two actions per confirmation set.
    saved = 4 * group_members - 2 * len(groups)
    return {
        "historical_transactions": len(states),
        "historical_transactions_reviewed": complete,
        "remaining_unresolved": len(states) - complete,
        "revision_reviewed_transactions": reviewed,
        "revision_events": len(revisions),
        "repeated_review_transactions": sum(n > 1 for n in counts.values()),
        "repeated_review_rate": sum(n > 1 for n in counts.values()) / reviewed if reviewed else 0,
        "quick_confirmation_transactions": routes["quick"],
        "grouped_confirmation_transactions": routes["grouped"],
        "individual_review_transactions": routes["individual"],
        "quick_confirmation_rate": routes["quick"] / reviewed if reviewed else 0,
        "grouped_confirmation_rate": routes["grouped"] / reviewed if reviewed else 0,
        "individual_review_rate": routes["individual"] / reviewed if reviewed else 0,
        "separate_confirmations_avoided": sum(
            len(g["transaction_ids"]) - 1 for g in groups.values()
        ),
        "transactions_avoiding_individual_field_selection": group_members,
        "estimated_manual_actions_saved": saved,
        "rate_denominator": "Distinct transactions with revisions; first recorded route",
        "judgment_rate_limitation": "Individual route is an upper bound on actual judgment; "
        "older events do not distinguish accepting suggestions from new reasoning.",
        "savings_assumption": "Four actions per two-field individual; two per confirmation set. "
        "only recorded group/quick events counted, not unmeasured semantic reuse.",
    }


def exit_decision(
    plan, *, accidental_unknown=0, stale_novelty=0, missed_alias=0, unresolved_reuse_regressions=0
):
    counts = plan["summary"]["reason_counts"]
    evidence_limited = counts.get("INSUFFICIENT_EVIDENCE", 0) + counts.get("PROCESSOR_AMBIGUOUS", 0)
    blockers = {
        "genuinely_novel": plan["summary"]["truly_novel_transactions"],
        "conflicting_history": counts.get("CONFLICTING_HISTORY", 0),
        "high_value_judgments": max(
            0, plan["summary"]["individual_reviews_remaining"] - evidence_limited
        ),
        "accidental_unknown": accidental_unknown,
        "stale_novelty": stale_novelty,
        "missed_alias": missed_alias,
        "unresolved_reuse_regressions": unresolved_reuse_regressions,
        "excluded_pending": plan["summary"].get("ineligible_pending", 0),
    }
    return {
        "status": "HISTORICAL_REVIEW_MODE"
        if any(blockers.values())
        else "READY_FOR_ONGOING_REVIEW_MODE",
        "blockers": blockers,
        "evidence_limited": evidence_limited,
        "quick_confirmations_remaining": plan["summary"]["known_single_confirmations"],
    }
