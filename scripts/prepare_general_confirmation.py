"""Freeze one diverse, private 20-card pilot batch without creating human decisions."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.api.app.domain.models import Document, Transaction
from tapio.confirmation.batch import freeze_batch, prepare_candidates
from tapio.confirmation.service import review_state
from tapio.knowledge.models import KnowledgeEvent, digest
from tapio.knowledge.store import load_bundle, save_bundle
from tapio.pilot.config import load_config, readonly_engine, source_fingerprints


def main():
    os.environ["TAPIO_PILOT_MODE"] = "true"
    root = Path("data/interim/general_confirmation")
    if (root / "preview.json").exists():
        raise ValueError("FROZEN_BATCH_ALREADY_EXISTS_DO_NOT_REGENERATE")
    config, _ = load_config()
    engine = readonly_engine()
    factory = sessionmaker(engine)
    before = source_fingerprints(engine, config)
    with factory() as db:
        tables = {
            name: json.loads(
                json.dumps(
                    [
                        dict(r)
                        for r in db.execute(select(Document.metadata.tables[name])).mappings()
                    ],
                    default=str,
                )
            )
            for name in (
                "transactions",
                "transaction_label_reviews",
                "confirmation_revisions",
                "invoices",
                "transaction_invoice_allocations",
                "transaction_reversal_candidates",
            )
        }
        states = {str(t.id): review_state(db, t)[:2] for t in db.scalars(select(Transaction))}
    prior = Path("data/interim/controlled_confirmation")
    result = json.loads((prior / "results.json").read_text())
    path = prior / "knowledge" / ("snapshot-" + result["knowledge_diff"]["events_hash"] + ".json")
    snapshot = load_bundle(path)
    candidates = prepare_candidates(tables, snapshot, datetime.now(UTC), states)
    batch = freeze_batch(
        candidates,
        snapshot.events_hash,
        before,
        {r["id"]: digest(r) for r in tables["confirmation_revisions"]},
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    events = [
        KnowledgeEvent.model_validate(e)
        for e in json.loads(path.with_name("events-" + snapshot.events_hash + ".json").read_text())
    ]
    assert save_bundle(root / "knowledge", events) == snapshot
    assert source_fingerprints(engine, config) == before
    files = {
        "preview.json": batch,
        "knowledge_diff.json": {"new_events_hash": snapshot.events_hash},
        "baseline.json": before,
        "selection_report.json": {
            "batch_id": batch["batch_id"],
            "size": len(batch["cards"]),
            "available": batch["available_composition"],
            "selected": batch["composition"],
            "knowledge_items": len(snapshot.items),
            "previous_revisions": len(tables["confirmation_revisions"]),
            "excluded": (
                "Already human-reviewed, unstable identity, reversal candidates, "
                "ambiguous links, absolute EUR 588.07."
            ),
        },
    }
    for name, value in files.items():
        with (root / name).open("x") as out:
            (root / name).chmod(0o600)
            json.dump(value, out, ensure_ascii=False, indent=2)
    print(json.dumps(files["selection_report.json"]))
    engine.dispose()


if __name__ == "__main__":
    main()
