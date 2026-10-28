"""Explicit offline generation of a small immutable batch; never writes source tables."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from apps.api.app.domain.models import Document
from tapio.confirmation.projection import project_review_rows
from tapio.knowledge.store import load_bundle
from tapio.pilot.config import load_config, readonly_engine, readonly_session, source_fingerprints
from tapio.suggestions.generate import Generator
from tapio.suggestions.store import Store


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--observed-at", required=True)
    p.add_argument("--output", type=Path, default=Path("data/interim/suggestion_pilot"))
    p.add_argument("--size", type=int, default=16)
    args = p.parse_args()
    if not args.output.resolve().is_relative_to(Path("data/interim").resolve()):
        p.error("Output must be private derived data under data/interim")
    os.environ["TAPIO_PILOT_MODE"] = "true"
    config, _ = load_config()
    engine = readonly_engine()
    before = source_fingerprints(engine, config)
    snapshot = load_bundle(args.snapshot)
    rows = {}
    with readonly_session(engine) as db:
        for name in ("transactions", "transaction_label_reviews", "confirmation_revisions"):
            values = (
                db.execute(select(Document.metadata.tables[name]).limit(100001)).mappings().all()
            )
            if len(values) > 100000:
                raise ValueError("SOURCE_LIMIT")
            rows[name] = json.loads(json.dumps([dict(v) for v in values], default=str))
    cards = Generator(
        snapshot,
        rows["transactions"],
        project_review_rows(rows["transaction_label_reviews"], rows["confirmation_revisions"]),
        datetime.fromisoformat(args.observed_at),
    ).sample(args.size)
    assert before == source_fingerprints(engine, config)
    Store(args.output).save_batch(
        cards,
        {
            "knowledge_events_hash": snapshot.events_hash,
            "source_fingerprints": before,
            "observed_at": args.observed_at,
        },
    )
    report = {
        "cards": len(cards),
        "category": sum(c.suggestion.category is not None for c in cards),
        "context": sum(c.suggestion.context is not None for c in cards),
        "both": sum(bool(c.suggestion.category and c.suggestion.context) for c in cards),
        "neither": sum(
            c.suggestion.category is None and c.suggestion.context is None for c in cards
        ),
        "multi_context": sum(
            any(r.code == "MULTI_CONTEXT_MERCHANT" for r in c.reasons) for c in cards
        ),
        "conflicting": sum(c.conflicting_knowledge for c in cards),
        "ambiguous_links": sum("RECONCILIATION_LINK" in {r.code for r in c.reasons} for c in cards),
        "source_tables_unchanged": len(before),
        "model_calls": 0,
    }
    lines = ["# Read-only suggestion batch", "", json.dumps(report, indent=2), ""]
    for n, c in enumerate(cards, 1):
        lines += [
            f"## Card {n}: {c.transaction.merchant}",
            "",
            "```json",
            c.model_dump_json(indent=2),
            "```",
            "",
        ]
    path = args.output / "report.md"
    path.write_text("\n".join(lines))
    path.chmod(0o600)
    path = args.output / "summary.json"
    path.write_text(json.dumps(report, indent=2))
    path.chmod(0o600)
    print(json.dumps(report, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
