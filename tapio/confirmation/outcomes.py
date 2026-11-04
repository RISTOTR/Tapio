"""Field outcomes describe explicit selections, never inferred human decisions."""

from collections import Counter

FIELDS = ("category", "context")


def field_outcomes(suggestion, selected, current):
    result = {}
    for field in FIELDS:
        if field in selected:
            proposed = suggestion.get(field)
            result[field] = (
                "MANUALLY_COMPLETED"
                if proposed is None
                else "SUGGESTION_ACCEPTED"
                if selected[field] == proposed
                else "SUGGESTION_CHANGED"
            )
        else:
            result[field] = (
                "NOT_APPLICABLE"
                if current.get("authority", {}).get(field) == "HUMAN_CONFIRMED"
                else "LEFT_UNRESOLVED"
            )
    return result


def outcome_metrics(cards, revisions, skips):
    latest = {r["audit"]["card_id"]: r for r in sorted(revisions, key=lambda r: r["sequence"])}
    counts = Counter()
    for cid, card in cards.items():
        row = latest.get(cid)
        if row:
            counts.update(row["audit"]["field_outcomes"].values())
        elif cid in skips:
            counts.update(field_outcomes(card["suggestion"], {}, card["current_state"]).values())
    receipts = [c for c in cards.values() if c.get("receipt_evidence")]
    return {
        "field_outcomes": dict(counts),
        "suggested_fields_accepted": counts["SUGGESTION_ACCEPTED"],
        "suggested_fields_changed": counts["SUGGESTION_CHANGED"],
        "unsuggested_fields_manually_completed": counts["MANUALLY_COMPLETED"],
        "fields_left_unresolved": counts["LEFT_UNRESOLVED"],
        "processor_transactions_reviewed": sum(
            c["card_id"] in latest or c["card_id"] in skips for c in receipts
        ),
        "receipt_search_attempted": sum(
            c["receipt_evidence"]["search_attempted"] for c in receipts
        ),
        "receipt_statuses": dict(Counter(c["receipt_evidence"]["status"] for c in receipts)),
        "suggestions_improved_by_receipt_evidence": sum(
            c.get("receipt_category_added", False) for c in cards.values()
        ),
        "manually_completed_despite_receipt_absence": sum(
            c["card_id"] in latest
            and c["receipt_evidence"]["status"] == "NO_RECEIPT_FOUND"
            and "MANUALLY_COMPLETED" in latest[c["card_id"]]["audit"]["field_outcomes"].values()
            for c in receipts
        ),
    }
