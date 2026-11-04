"""Scoped category hypotheses, independent of human-confirmed semantic facts."""

from tapio.knowledge.models import digest


def derive_mappings(candidates):
    """Record observed label evidence; concept approval does not approve this mapping."""
    records = []
    for candidate in candidates:
        support = candidate["support"]
        categories = sorted({s["category"] for s in support})
        conflicts = categories if len(categories) != 1 else []
        blocked = []
        if candidate.get("mapping_review_required"):
            blocked.append("EXPLICIT_MAPPING_REVIEW_REQUIRED")
        if candidate["concept"] == "GOVERNMENT_AGENCY":
            blocked.append("GOVERNMENT_IDENTITY_IS_NOT_TAX_PURPOSE")
        if "UNKNOWN" in categories:
            blocked.append("UNKNOWN_IS_NOT_CATEGORY_MAPPING")
        if conflicts:
            blocked.append("CONFLICTING_MAPPING_EVIDENCE")
        if len({s["transaction_id"] for s in support}) < 2:
            blocked.append("INSUFFICIENT_MAPPING_SUPPORT")
        if candidate["concept"] == "HARDWARE_RETAILER":
            blocked.append("HARDWARE_MAPPING_REQUIRES_SEPARATE_VALIDATION")
        record = {
            "kind": "CATEGORY_MAPPING",
            "candidate_id": candidate["id"],
            "concept": candidate["concept"],
            "category": categories[0] if len(categories) == 1 else None,
            "scope": {
                "term": candidate["term"],
                "match_mode": candidate["match_mode"],
                "candidate_id": candidate["id"],
            },
            "authority": "SUGGESTED",
            "support": support,
            "support_count": len({s["transaction_id"] for s in support}),
            "conflicts": conflicts,
            "blocked": blocked,
            "eligible": not blocked,
            "provenance": {
                "method": "scoped-unanimous-human-category-observations-v1",
                "candidate_hash": digest(candidate),
            },
        }
        records.append({"id": digest(record), **record})
    return records


def current_mappings(candidates, tables, states):
    from tapio.knowledge.concepts import generate_candidates, matches
    from tapio.knowledge.uncertainty import observations

    current = {
        (c["kind"], c["term"], c["match_mode"], c["concept"]): c
        for c in generate_candidates(tables, states)
    }
    reviewed = (
        observations(tables, states)
        if any(c.get("mapping_review_required") for c in candidates)
        else []
    )
    inputs = []
    for c in candidates:
        latest = current.get((c["kind"], c["term"], c["match_mode"], c["concept"]))
        support = latest["support"] if latest else []
        if c.get("mapping_review_required"):
            support = [
                {
                    "transaction_id": r["transaction_id"],
                    "identity": r["identity"],
                    "category": r["value"],
                    "context": states[r["transaction_id"]][0].get("context"),
                    "review_id": r["review_id"],
                    "review_hash": r["review_hash"],
                }
                for r in reviewed
                if r["field"] == "category" and matches(c["term"], c["match_mode"], r["identity"])
            ]
        inputs.append({**c, "support": support})
    return derive_mappings(inputs)


def mapping_events(mappings, observed_at):
    from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance

    return [
        KnowledgeEvent(
            event_type="SOURCE_PARSED",
            claims=(
                Claim(
                    kind="CATEGORY_MAPPING",
                    subject=m["concept"],
                    predicate="suggested_category_mapping",
                    value=m,
                    scope=m["candidate_id"],
                    authority="SUGGESTED",
                    provenance=Provenance(
                        source_type="category_mapping_observations",
                        source_id=m["id"],
                        source_hash=digest(m),
                        originating_field="support",
                        observed_at=observed_at,
                        extraction_method="scoped-human-category-observations-v1",
                    ),
                ),
            ),
        )
        for m in mappings
    ]
