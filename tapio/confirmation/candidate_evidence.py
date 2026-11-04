"""Versioned, non-authoritative evidence refresh without rewriting candidate/audit history."""

import json


def refreshed(root, candidates, decided_ids):
    overlays = {}
    for path in sorted((root / "evidence_refresh").glob("*.json")):
        overlays.update(json.loads(path.read_text()))
    allowed = {
        "support",
        "observed_labels",
        "impact",
        "source_evidence",
        "conflicts",
        "support_count",
        "entity_support_level",
        "purchase_support_requirement",
    }
    result = []
    for candidate in candidates:
        patch = overlays.get(candidate["id"], {}) if candidate["id"] not in decided_ids else {}
        if set(patch) - allowed:
            raise ValueError("INVALID_CANDIDATE_EVIDENCE_REFRESH")
        result.append({**candidate, **patch})
    return result
