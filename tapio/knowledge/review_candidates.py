"""Bounded interpretation proposals; label history never confirms semantic identity."""

from collections import Counter

from data_pipeline.labels.merchant_policy import ambiguous_merchant
from tapio.knowledge.concepts import identity, matches, words
from tapio.knowledge.models import digest
from tapio.knowledge.user_rules import UserRule, rule_match

# Interpretation seeds are shown as unconfirmed hypotheses with source provenance.
INSPECT = [
    ("farmacia", "PHARMACY", "TOKEN"),
    ("cerveceria", "BAR", "TOKEN"),
    ("ravintola", "RESTAURANT", "TOKEN"),
    ("cafe", "CAFE", "TOKEN"),
    ("bar", "BAR", "TOKEN"),
    ("lidl", "GROCERY_RETAILER", "CHAIN_PREFIX"),
    ("alko", "ALCOHOL_RETAILER", "CHAIN_PREFIX"),
    ("iberia", "AIRLINE", "CHAIN_PREFIX"),
    ("finnair", "AIRLINE", "CHAIN_PREFIX"),
    ("hmshost", "AIRPORT_FOOD_SERVICE", "CHAIN_PREFIX"),
    ("stockmann", "DEPARTMENT_STORE", "CHAIN_PREFIX"),
    ("fiskars", "HOME_GOODS", "CHAIN_PREFIX"),
    ("traficom", "GOVERNMENT_AGENCY", "TOKEN"),
    ("liikenne- ja viestintävirasto", "GOVERNMENT_AGENCY", "CHAIN_PREFIX"),
    ("onnibus", "BUS_OPERATOR", "CHAIN_PREFIX"),
    ("vr", "TRAIN_OPERATOR", "EXACT_IDENTITY"),
]
CATEGORY = {
    "PHARMACY": "OTHER",
    "BAR": "OTHER",
    "CAFE": "OTHER",
    "RESTAURANT": "OTHER",
    "GROCERY_RETAILER": "GROCERIES",
    "ALCOHOL_RETAILER": "OTHER",
    "AIRLINE": "TRAVEL",
    "BUS_OPERATOR": "TRAVEL",
    "TRAIN_OPERATOR": "TRAVEL",
    "AIRPORT_FOOD_SERVICE": "OTHER",
    "DEPARTMENT_STORE": "OTHER",
}
STABLE = ["hmshost", "alko", "elenia", "s-market", "k-market", "dna", "vattenfall", "lähitapiola"]


def propose(tables, rows, pending_cards, concepts, active_rules):
    txs = {t["id"]: t for t in tables["transactions"]}
    semantic, mappings, inspections = [], [], []
    for term, concept, mode in INSPECT:
        existing = any(
            words(c["term"]) == words(term) and c["concept"] == concept for c in concepts
        )
        existing |= any(
            r["rule"]["scope"].get("concept") == concept
            and any(words(t) == words(term) for t in r["rule"]["scope"].get("terms", []))
            for r in active_rules
        )
        found = [t for t in tables["transactions"] if matches(term, mode, identity(t))]
        # Concatenated Lidl location strings require exact observed-identity scope.
        if term == "lidl":
            found += [
                t
                for t in tables["transactions"]
                if words(identity(t)) == "lidlviitasaari viitasaari" and t not in found
            ]
        if existing:
            inspections.append({"term": term, "result": "EXISTING_KNOWLEDGE_REUSED"})
            continue
        if not found or term == "fiskars":
            inspections.append(
                {
                    "term": term,
                    "result": "INSUFFICIENT_SEMANTIC_EVIDENCE",
                    "source_matches": len(found),
                    "reason": (
                        "Merchant string or OTHER label does not prove purchase business type."
                    ),
                }
            )
            continue
        scopes = [(term, mode)]
        if term == "lidl" and any(words(identity(t)) == "lidlviitasaari viitasaari" for t in found):
            scopes = [("lidlviitasaari viitasaari", "EXACT_IDENTITY")]
        for scoped_term, scoped_mode in scopes:
            matches_tx = [t for t in found if matches(scoped_term, scoped_mode, identity(t))]
            ids = {t["id"] for t in matches_tx}
            support = []
            for r in rows:
                if r["transaction_id"] in ids and r["field"] == "category":
                    ctx = next(
                        (
                            x["value"]
                            for x in rows
                            if x["transaction_id"] == r["transaction_id"]
                            and x["field"] == "context"
                        ),
                        None,
                    )
                    support.append(
                        {
                            **r,
                            "category": r["value"],
                            "context": ctx,
                            "transaction_hash": digest(txs[r["transaction_id"]]),
                        }
                    )
            affected = [c for c in pending_cards if c["transaction"]["id"] in ids]
            risk = (
                "Candidate semantic interpretation only; human labels are not proof of "
                "business type. No context inference."
            )
            if term == "iberia":
                risk += (
                    " Onboard purchase was explicitly OTHER; AIRLINE must not turn onboard "
                    "purchases into TRAVEL."
                )
            if concept == "GOVERNMENT_AGENCY":
                risk += " Government identity does not imply TAX."
            c = {
                "kind": "VOCABULARY_CONCEPT" if scoped_mode == "TOKEN" else "MERCHANT_TYPE",
                "term": scoped_term,
                "concept": concept,
                "match_mode": scoped_mode,
                "authority": "SUGGESTED",
                "support": support,
                "source_evidence": [
                    {"transaction_id": t["id"], "identity": identity(t), "hash": digest(t)}
                    for t in matches_tx
                ],
                "observed_labels": {
                    "category": dict(Counter(r["category"] for r in support)),
                    "context": dict(Counter(str(r["context"]) for r in support)),
                },
                "mapping_review_required": True,
                "impact": {
                    "affected_pending": len(affected),
                    "category_abstentions": sum(
                        c["suggestion"].get("category") is None for c in affected
                    ),
                    "context_effect": "NONE",
                },
                "risk": risk,
                "limitations": "Pending explicit semantic review; no mapping or context authority.",
            }
            c["id"] = digest(
                {
                    "term": scoped_term,
                    "mode": scoped_mode,
                    "concept": concept,
                    "phase": "uncertainty-v1",
                }
            )[:24]
            semantic.append(c)
            desired = CATEGORY.get(concept)
            conflicts = sorted({r["category"] for r in support if r["category"] != desired})
            if desired and support and not conflicts:
                m = {
                    "concept_candidate_id": c["id"],
                    "concept": concept,
                    "category": desired,
                    "scope": {"term": scoped_term, "match_mode": scoped_mode},
                    "support": support,
                    "conflicts": conflicts,
                    "authority": "SUGGESTED",
                    "impact": c["impact"],
                    "risk": (
                        "Category only, requires separately confirmed concept and at least"
                        " two current agreeing observations. No context or tax inference."
                    ),
                }
                m["id"] = digest(m)[:24]
                mappings.append(m)
            inspections.append(
                {
                    "term": term,
                    "result": "CANDIDATE",
                    "mapping": "CANDIDATE" if desired and support and not conflicts else "WITHHELD",
                    "conflicting_categories": conflicts,
                }
            )
    stable_inspection = []
    rules = []
    for token in STABLE:
        identities = sorted({r["identity_key"] for r in rows if token in r["identity_key"]})
        for key in identities:
            observations = [r for r in rows if r["identity_key"] == key]
            by_field = {
                f: {r["value"] for r in observations if r["field"] == f}
                for f in ("category", "context")
            }
            count = len({r["transaction_id"] for r in observations})
            affected = [
                c for c in pending_cards if identity(txs[c["transaction"]["id"]]).casefold() == key
            ]
            result = "INSUFFICIENT_HISTORY"
            if ambiguous_merchant(key) or any(len(v) > 1 for v in by_field.values()):
                result = "CONFLICT_OR_MULTI_CONTEXT"
            elif all(
                len({r["transaction_id"] for r in observations if r["field"] == f}) >= 3
                for f in ("category", "context")
            ) and all(len(v) == 1 and "UNKNOWN" not in v for v in by_field.values()):
                uncovered = [
                    c for c in affected if any(c["suggestion"].get(f) is None for f in by_field)
                ]
                covered = any(
                    rule_match(UserRule.model_validate(r["rule"]), txs[o["transaction_id"]])
                    for r in active_rules
                    for o in observations
                )
                result = (
                    "EXISTING_RULE_REUSED"
                    if covered
                    else "ALREADY_COVERED_OR_NO_PENDING_IMPACT"
                    if not uncovered
                    else "CANDIDATE"
                )
                if result == "CANDIDATE":
                    rule = UserRule(
                        subject=key,
                        kind="ENTITY_CLASSIFICATION_RULE",
                        category=next(iter(by_field["category"])),
                        context=next(iter(by_field["context"])),
                        scope={"type": "ENTITY_EXACT", "entity": key},
                    ).model_dump(mode="json")
                    c = {
                        "rule": rule,
                        "support": observations,
                        "semantic_facts": [],
                        "contradictions": [],
                        "would_match": len(affected),
                        "optional_candidate": True,
                        "impact": {
                            "affected_pending": len(affected),
                            "abstentions": len(uncovered),
                        },
                        "risk": "Exact identity only; no universal merchant or tax rule.",
                        "limitations": "Pending explicit structured review.",
                    }
                    c["id"] = digest(rule)[:24]
                    rules.append(c)
            stable_inspection.append(
                {
                    "identity": key,
                    "human_observations": count,
                    "values": {f: sorted(v) for f, v in by_field.items()},
                    "pending": len(affected),
                    "result": result,
                }
            )
    return {
        "semantic": semantic,
        "mappings": mappings,
        "rules": rules,
        "semantic_inspection": inspections,
        "stable_inspection": stable_inspection,
    }
