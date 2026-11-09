"""Field-level human uncertainty and exact-identity observations, never merchant rules."""

from collections import Counter, defaultdict
from copy import deepcopy
from enum import StrEnum

from integrations.gmail.receipts import norm
from tapio.knowledge.concepts import identity
from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance, digest


class FieldState(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    UNRESOLVED = "UNRESOLVED"
    HUMAN_CONFIRMED_VALUE = "HUMAN_CONFIRMED_VALUE"
    HUMAN_CONFIRMED_UNKNOWN = "HUMAN_CONFIRMED_UNKNOWN"


def field_state(state, field):
    value = state.get(field)
    if state.get("authority", {}).get(field) == "HUMAN_CONFIRMED" and value is not None:
        return (
            FieldState.HUMAN_CONFIRMED_UNKNOWN
            if value == "UNKNOWN"
            else FieldState.HUMAN_CONFIRMED_VALUE
        )
    return (
        FieldState.UNRESOLVED
        if any(v == "HUMAN_CONFIRMED" for v in state.get("authority", {}).values())
        else FieldState.UNREVIEWED
    )


def observations(tables, states):
    """Only latest field decisions count; corrections supersede, not erase, old audit."""
    revisions = defaultdict(list)
    for r in tables.get("confirmation_revisions", []):
        revisions[str(r["transaction_id"])].append(r)
    legacy = {str(r["transaction_id"]): r for r in tables.get("transaction_label_reviews", [])}
    output = []
    for tx in tables["transactions"]:
        state = states[tx["id"]][0]
        for field in ("category", "context"):
            status = field_state(state, field)
            if not status.startswith("HUMAN_CONFIRMED"):
                continue
            source = next(
                (
                    r
                    for r in sorted(revisions[tx["id"]], key=lambda r: r["sequence"], reverse=True)
                    if field in r["fields"]
                ),
                None,
            ) or legacy.get(tx["id"])
            if not source:
                raise ValueError("HUMAN_FIELD_WITHOUT_PROVENANCE")
            output.append(
                {
                    "transaction_id": tx["id"],
                    "identity": identity(tx),
                    "identity_key": norm(identity(tx)),
                    "field": field,
                    "value": state[field],
                    "field_state": status.value,
                    "authority": "HUMAN_CONFIRMED",
                    "review_id": source["id"],
                    "review_hash": digest(source),
                    "timestamp": source.get("created_at") or source.get("reviewed_at"),
                    "source_type": "confirmation_revisions"
                    if "sequence" in source
                    else "transaction_label_reviews",
                    "note": source.get("audit", {}).get("correction_reason", ""),
                }
            )
    return output


def unknown_events(rows):
    return [
        KnowledgeEvent(
            event_type="HUMAN_REVIEW_CONFIRMED",
            claims=(
                Claim(
                    kind="UNCERTAINTY_OBSERVATION",
                    subject=r["transaction_id"],
                    predicate="human_confirmed_unknown",
                    value=r,
                    scope=r["field"],
                    authority="HUMAN_CONFIRMED",
                    provenance=Provenance(
                        source_type=r["source_type"],
                        source_id=r["review_id"],
                        source_hash=r["review_hash"],
                        originating_field=r["field"],
                        observed_at=r["timestamp"],
                        extraction_method="latest-explicit-unknown-v1",
                        confirmation_id=r["review_id"],
                    ),
                ),
            ),
        )
        for r in rows
        if r["field_state"] == "HUMAN_CONFIRMED_UNKNOWN"
    ]


def repeated_unknown(rows):
    groups = defaultdict(list)
    for r in rows:
        if r["identity_key"] and r["field_state"] == "HUMAN_CONFIRMED_UNKNOWN":
            groups[r["identity_key"]].append(r)
    return [
        {
            "code": "REPEATED_UNKNOWN_MERCHANT",
            "identity": key,
            "transactions": len({r["transaction_id"] for r in values}),
            "observations": values,
            "is_rule": False,
        }
        for key, values in sorted(groups.items())
        if len({r["transaction_id"] for r in values}) >= 2
    ]


def apply_uncertainty(card, tx, rows, semantic_known=False, *, identity_key=None):
    result = deepcopy(card)
    state = result["current_state"]
    result["field_states"] = {f: field_state(state, f).value for f in ("category", "context")}
    history = [
        r
        for r in rows
        if r["identity_key"]
        and r["identity_key"] == (identity_key if identity_key is not None else norm(identity(tx)))
        and r["transaction_id"] != tx["id"]
        and r["field_state"] == "HUMAN_CONFIRMED_UNKNOWN"
    ]
    result["uncertainty_history"] = history
    signals = []
    if any(v == "HUMAN_CONFIRMED_UNKNOWN" for v in result["field_states"].values()):
        signals.append("HUMAN_CONFIRMED_UNKNOWN")
    for f in ("category", "context"):
        if result["field_states"][f].startswith("HUMAN_CONFIRMED"):
            result["suggestion"][f] = None
        elif any(r["field"] == f for r in history):
            # This is a conservative review warning, not an UNKNOWN assignment.
            # Explicit scoped rules or transaction-specific documents remain visible.
            explicit = bool(result.get("user_rules")) or (
                f == "category" and result.get("receipt_category_added")
            )
            if not explicit:
                result["suggestion"][f] = None
    if history:
        signals.append("HUMAN_CONFIRMED_UNKNOWN_HISTORY")
        if len({r["transaction_id"] for r in history}) >= 2:
            signals.append("REPEATED_UNKNOWN_MERCHANT")
        result["reasons"].append(
            {
                "code": "HUMAN_CONFIRMED_UNKNOWN_HISTORY",
                "explanation": (
                    "Previously reviewed but purpose remained unknown. Exact-identity "
                    "observations are not merchant-wide classifications."
                ),
                "evidence_refs": sorted({r["review_id"] for r in history}),
            }
        )
    if not identity(tx):
        signals.append("UNKNOWN_IDENTITY")
    elif semantic_known or result.get("semantic_concepts"):
        signals.append("KNOWN_BUSINESS_TYPE_UNKNOWN_TRANSACTION_PURPOSE")
    else:
        signals.append("KNOWN_IDENTITY_UNKNOWN_PURPOSE")
    result["review_signals"] = signals
    result["abstention_reasons"] = {}
    for f in ("category", "context"):
        if result["suggestion"].get(f) is not None or result["field_states"][f].startswith(
            "HUMAN_CONFIRMED"
        ):
            continue
        blocked = result.get("blocked_generalizations", [])
        reason = (
            "HUMAN_CONFIRMED_UNKNOWN_HISTORY"
            if any(r["field"] == f for r in history)
            else "PROCESSOR_OPAQUE"
            if result.get("paytrail_purpose") == "STILL_OPAQUE"
            else "MULTI_CONTEXT_BLOCK"
            if f == "context" and result.get("multi_context")
            else "CONFLICTING_HISTORY"
            if result.get("conflicting_knowledge") or result.get("user_rule_conflicts")
            else "NO_ENTITY_KNOWLEDGE"
            if not identity(tx)
            else "NO_CATEGORY_MAPPING"
            if f == "category" and (semantic_known or any("MAPPING" in x for x in blocked))
            else "NO_SEMANTIC_CONCEPT"
            if f == "category" and not result.get("semantic_concepts")
            else "INSUFFICIENT_TRANSACTION_EVIDENCE"
        )
        result["abstention_reasons"][f] = reason
    tags = [
        t
        for t in result.get("pilot_tags", [])
        if t not in {"BOTH", "CATEGORY_ONLY", "CONTEXT_ONLY", "ABSTENTION"}
    ]
    c, x = (result["suggestion"].get(f) for f in ("category", "context"))
    tags.append(
        "BOTH" if c and x else "CATEGORY_ONLY" if c else "CONTEXT_ONLY" if x else "ABSTENTION"
    )
    if history:
        tags.append("HUMAN_CONFIRMED_UNKNOWN_HISTORY")
    result["pilot_tags"] = tags
    result["card_id"] = digest(result)[:32]
    return result


def consolidate(cards, revisions, states):
    """New derived report; never rewrite original field_outcomes or audit records."""
    by_tx = {c["transaction"]["id"]: c for c in cards}
    records = []
    for txid, card in by_tx.items():
        for field in ("category", "context"):
            rows = sorted(
                (r for r in revisions if r["transaction_id"] == txid and field in r["fields"]),
                key=lambda r: r["sequence"],
            )
            if not rows:
                continue
            row = rows[-1]
            value = states[txid][0][field]
            proposed = row["audit"].get("suggestion_snapshot", card["suggestion"]).get(field)
            outcome = (
                "HUMAN_CONFIRMED_UNKNOWN"
                if value == "UNKNOWN"
                else "ACCEPTED_EXISTING_SUGGESTION"
                if proposed is not None and proposed == value
                else "HUMAN_COMPLETED_KNOWN_VALUE"
            )
            records.append(
                {
                    "transaction_id": txid,
                    "field": field,
                    "review_id": row["id"],
                    "review_hash": digest(row),
                    "prior_suggestion": proposed,
                    "original_card_suggestion": card["suggestion"].get(field),
                    "final_value": value,
                    "authority": "HUMAN_CONFIRMED",
                    "outcome": outcome,
                    "note": row["audit"].get("correction_reason", ""),
                    "revision_history": [r["id"] for r in rows],
                }
            )
    return {
        "records": records,
        "outcomes": dict(Counter(r["outcome"] for r in records)),
        "reviewed_transactions": len({r["transaction_id"] for r in records}),
    }


def classification_friction(consolidated, prior_observations, transactions):
    """Repeated manual completion against knowledge available before window creation."""
    txs = {t["id"]: t for t in transactions}
    repeated = []
    for row in consolidated["records"]:
        if row["outcome"] != "HUMAN_COMPLETED_KNOWN_VALUE":
            continue
        key = norm(identity(txs[row["transaction_id"]]))
        prior = [
            r
            for r in prior_observations
            if key
            and r["identity_key"] == key
            and r["transaction_id"] != row["transaction_id"]
            and r["field"] == row["field"]
        ]
        if prior and {r["value"] for r in prior} == {row["final_value"]}:
            repeated.append(
                {
                    "code": "REPEATED_CLASSIFICATION",
                    "transaction_id": row["transaction_id"],
                    "field": row["field"],
                    "value": row["final_value"],
                    "prior_review_ids": sorted({r["review_id"] for r in prior}),
                    "review_id": row["review_id"],
                }
            )
    return {"repeated_manual_fields": len(repeated), "records": repeated}


def replay_unknown(events, rows):
    """Project current uncertainty without erasing any source review events."""
    projected = []
    for event in events:
        claims = tuple(c for c in event.claims if c.kind != "UNCERTAINTY_OBSERVATION")
        if claims:
            projected.append(event.model_copy(update={"claims": claims}))
    return projected + unknown_events(rows)
