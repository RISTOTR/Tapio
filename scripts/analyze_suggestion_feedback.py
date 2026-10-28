"""Read-only, fixed-batch feedback analysis with source and knowledge replay checks."""

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from apps.api.app.domain.models import Document
from tapio.knowledge.store import load_bundle
from tapio.pilot.config import load_config, readonly_engine, readonly_session, source_fingerprints
from tapio.suggestions.analysis import CHOICES, analyze, content, load_feedback, note_themes
from tapio.suggestions.generate import Generator
from tapio.suggestions.store import Store


def fingerprints(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=Path("data/interim/suggestion_pilot"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/interim/suggestion_feedback_analysis")
    )
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(Path("data/interim").resolve()):
        parser.error("Analysis output must remain private under data/interim")
    if args.output.resolve().is_relative_to(args.store.resolve()):
        parser.error("Keep analysis separate from the original pilot store")
    protected = list(args.store.rglob("*")) + list(args.snapshot.parent.glob("*.json"))
    before = fingerprints(protected)
    store = Store(args.store)
    batch, _ = store.batch()
    cards, feedback, audit = load_feedback(store)
    snapshot = load_bundle(args.snapshot)
    assert snapshot.events_hash == batch["provenance"]["knowledge_events_hash"]
    os.environ["TAPIO_PILOT_MODE"] = "true"
    config, _ = load_config()
    engine = readonly_engine()
    try:
        source_before = source_fingerprints(engine, config)
        assert source_before == batch["provenance"]["source_fingerprints"]
        rows = {}
        with readonly_session(engine) as db:
            for name in ("transactions", "transaction_label_reviews"):
                values = db.execute(select(Document.metadata.tables[name]).limit(100001)).mappings()
                rows[name] = json.loads(json.dumps([dict(v) for v in values], default=str))
                assert len(rows[name]) <= 100000
        g = Generator(
            snapshot,
            rows["transactions"],
            rows["transaction_label_reviews"],
            datetime.fromisoformat(batch["provenance"]["observed_at"]),
        )
        for card in cards:
            tx = g.txs[card.transaction.id]
            assert g.card(tx, g.signals(tx)) == card, "CARD_SOURCE_REPLAY_MISMATCH"
        result = analyze(cards, feedback, snapshot)
        assert source_fingerprints(engine, config) == source_before
    finally:
        engine.dispose()
    result["feedback_audit"] = audit
    result["source_replay"] = {
        "cards_verified": len(cards),
        "source_tables_unchanged": 14,
        "knowledge_bundle_replayed": True,
        "model_calls": 0,
    }
    result["candidate_knowledge"] = [
        {
            "card_id": c.card_id,
            "transaction_reference": c.transaction.id,
            "merchant": c.transaction.merchant,
            "themes": note_themes(feedback[c.card_id]["note"]),
            "candidate_note": feedback[c.card_id]["note"],
            "status": "REQUIRES_EXPLICIT_REVIEW_NOT_KNOWLEDGE",
            "authority_granted": False,
            "scope": "Individual transaction; no merchant-wide rule",
            "feedback_record_hash": hashlib.sha256(
                json.dumps(feedback[c.card_id], sort_keys=True).encode()
            ).hexdigest(),
        }
        for c in cards
        if c.card_id in feedback and feedback[c.card_id]["note"].strip()
    ]
    result["card_audit"] = [
        {
            "card_id": c.card_id,
            "merchant": c.transaction.merchant,
            "content": content(c),
            "suggestion": c.suggestion.model_dump(),
            "priority": c.priority,
            "reason_codes": sorted({r.code for r in c.reasons}),
            "feedback": feedback.get(c.card_id, {}).get("choice"),
            "note_themes": note_themes(feedback.get(c.card_id, {}).get("note", "")),
            "knowledge_used": c.knowledge_used,
            "provenance_check": "REPLAYED_AGAINST_UNCHANGED_SOURCE_AND_KNOWLEDGE",
        }
        for c in cards
    ]
    assert fingerprints(protected) == before, "ANALYSIS_INPUT_MUTATED"
    result["input_file_hashes"] = before
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.chmod(0o700)
    lines = [
        "# Suggestion feedback analysis",
        "",
        result["decision"],
        "",
        "All counts use the latest saved response per card. No labels or knowledge changed.",
        "",
    ]
    for title, groups in [
        ("Suggestion content", result["by_content"]),
        ("Priority", result["by_priority"]),
        ("Reason", result["by_reason"]),
    ]:
        columns = ["total", "reviewed", "unanswered", *CHOICES]
        lines += [
            f"## {title}",
            "",
            "| Group | " + " | ".join(columns) + " |",
            "| --- | " + " | ".join(["---"] * len(columns)) + " |",
        ]
        lines += [
            "| " + key + " | " + " | ".join(str(row[k]) for k in columns) + " |"
            for key, row in groups.items()
        ]
        lines.append("")
    lines += [
        "## Private audit and candidate details",
        "",
        "```json",
        json.dumps(
            {k: v for k, v in result.items() if k != "input_file_hashes"},
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
    ]
    for name, text in [
        ("analysis.json", json.dumps(result, ensure_ascii=False, indent=2)),
        ("report.md", "\n".join(lines)),
    ]:
        path = args.output / name
        path.write_text(text)
        path.chmod(0o600)
    print(
        json.dumps(
            {
                "totals": result["totals"],
                "decision": result["decision"],
                "unsafe_findings": len(result["unsafe_findings"]),
                "source_replay": result["source_replay"],
            }
        )
    )


if __name__ == "__main__":
    main()
