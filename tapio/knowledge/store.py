"""Deterministic replay and private, derived-only persistence."""

from collections import defaultdict
from pathlib import Path

from tapio.knowledge.models import (
    Authority,
    Contradiction,
    KnowledgeEvent,
    KnowledgeItem,
    Snapshot,
    canonical,
    digest,
)

RANK = {
    Authority.UNKNOWN: 0,
    Authority.SUGGESTED: 1,
    Authority.DETERMINISTIC_SOURCE_FACT: 2,
    Authority.HUMAN_CONFIRMED: 3,
}


def rebuild(events: list[KnowledgeEvent]) -> Snapshot:
    unique_events = {digest(e): e for e in events}
    groups = defaultdict(dict)
    claims = {}
    seen = defaultdict(list)
    slots = defaultdict(set)
    for event in unique_events.values():
        for claim in event.claims:
            body = claim.model_dump(mode="json", exclude={"provenance"})
            key = digest(body)
            claims[key] = claim
            seen[key].append(claim.provenance.observed_at)
            p = claim.provenance
            # Repeated runs cannot inflate support from the same source revision/field.
            support_key = (p.source_type, p.source_id, p.source_hash, p.originating_field)
            existing = groups[key].get(support_key)
            if existing is None or (p.observed_at, canonical(p)) < (
                existing.observed_at,
                canonical(existing),
            ):
                groups[key][support_key] = p
            if claim.single_valued:
                slots[(claim.kind, claim.subject, claim.predicate, claim.scope)].add(key)
    conflicts = []
    counts = defaultdict(int)
    for keys in slots.values():
        values = {canonical(claims[k].value) for k in keys}
        if len(values) <= 1:
            continue
        best_rank = max(RANK[claims[k].authority] for k in keys)
        best = sorted(k for k in keys if RANK[claims[k].authority] == best_rank)
        preferred = best if len({canonical(claims[k].value) for k in best}) == 1 else []
        conflicts.append(
            Contradiction(
                claim_ids=tuple(sorted(keys)),
                preferred_claim_ids=tuple(preferred),
                status="HIGHER_AUTHORITY_PREFERRED" if preferred else "UNRESOLVED",
            )
        )
        for key in keys:
            counts[key] += sum(
                canonical(claims[k].value) != canonical(claims[key].value) for k in keys
            )
    items = []
    for key, sources in sorted(groups.items()):
        provenance = tuple(sorted(sources.values(), key=canonical))
        # Canonical representative makes replay independent of input event order.
        claim = claims[key].model_copy(update={"provenance": provenance[0]})
        items.append(
            KnowledgeItem(
                id=key,
                claim=claim,
                provenance=provenance,
                first_seen=min(seen[key]),
                last_seen=max(seen[key]),
                support_count=len(provenance),
                contradiction_count=counts[key],
                human_confirmation_status="CONFIRMED"
                if claim.authority == Authority.HUMAN_CONFIRMED
                else "NOT_CONFIRMED",
            )
        )
    return Snapshot(
        events_hash=digest(sorted(unique_events)),
        items=tuple(items),
        contradictions=tuple(sorted(conflicts, key=canonical)),
    )


def save_bundle(directory: Path, events: list[KnowledgeEvent]) -> Snapshot:
    """Write only a new content-addressed derived bundle; never overwrite history."""
    snapshot = rebuild(events)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    for name, value in (
        (
            "events-" + snapshot.events_hash + ".json",
            [e.model_dump(mode="json") for _, e in sorted({digest(e): e for e in events}.items())],
        ),
        ("snapshot-" + snapshot.events_hash + ".json", snapshot.model_dump(mode="json")),
    ):
        path = directory / name
        content = canonical(value)
        if path.exists():
            if path.read_text() != content:
                raise ValueError("KNOWLEDGE_BUNDLE_CONFLICT")
        else:
            with path.open("x") as f:
                path.chmod(0o600)
                f.write(content)
    return snapshot


def load_bundle(snapshot_path: Path) -> Snapshot:
    """Validate persisted claims against the accompanying replayable events."""
    import json

    snapshot = Snapshot.model_validate_json(snapshot_path.read_text())
    event_path = snapshot_path.with_name("events-" + snapshot.events_hash + ".json")
    events = [KnowledgeEvent.model_validate(e) for e in json.loads(event_path.read_text())]
    if rebuild(events) != snapshot:
        raise ValueError("KNOWLEDGE_REPLAY_MISMATCH")
    return snapshot
