"""Prepare one frozen 25–50 card batch; never submit review decisions."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.api.app.domain.models import Document, Transaction
from integrations.gmail.cache import private_write
from integrations.gmail.receipts import receipt_events
from tapio.confirmation.batch import freeze_batch, prepare_candidates
from tapio.confirmation.receipt_support import integrate_receipt
from tapio.confirmation.service import review_state
from tapio.knowledge.models import KnowledgeEvent, digest
from tapio.knowledge.store import load_bundle, save_bundle
from tapio.pilot.config import load_config, readonly_engine, source_fingerprints

ROOT = Path("data/interim/bounded_confirmation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=30)
    args = parser.parse_args()
    if not 25 <= args.size <= 50:
        parser.error("batch size must be 25–50")
    if (ROOT / "preview.json").exists():
        raise ValueError("FROZEN_BATCH_EXISTS_DO_NOT_REGENERATE")
    os.environ["TAPIO_PILOT_MODE"] = "true"
    config, _ = load_config()
    engine = readonly_engine()
    before = source_fingerprints(engine, config)
    with sessionmaker(engine)() as db:
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
    inventory = json.loads((ROOT / "inventory.json").read_text())
    assert tables == inventory["tables"] and json.loads(json.dumps(states)) == inventory["states"]
    prior = Path("data/interim/general_confirmation")
    prior_report = json.loads((prior / "final_results.json").read_text())
    h = prior_report["knowledge_diff"]["events_hash"]
    snapshot = load_bundle(prior / "knowledge" / ("snapshot-" + h + ".json"))
    assert len(snapshot.items) == 2685
    events = [
        KnowledgeEvent.model_validate(e)
        for e in json.loads((prior / "knowledge" / ("events-" + h + ".json")).read_text())
    ]
    now = datetime.now(UTC)
    candidates = prepare_candidates(tables, snapshot, now, states, bounded=True)
    for index, card in enumerate(candidates):
        if card.get("paytrail_purpose"):
            receipt = json.loads(
                (ROOT / "receipts" / (card["transaction"]["id"] + ".json")).read_text()
            )
            candidates[index] = integrate_receipt(card, receipt)
    batch = freeze_batch(
        candidates,
        snapshot.events_hash,
        before,
        {r["id"]: digest(r) for r in tables["confirmation_revisions"]},
        size=args.size,
        bounded=True,
        created_at=now,
    )
    receipt_claims = []
    for card in batch["cards"]:
        if card.get("receipt_evidence"):
            receipt_claims.extend(
                receipt_events(card["transaction"]["id"], card["receipt_evidence"])
            )
    combined = save_bundle(ROOT / "knowledge", events + receipt_claims)
    assert {i.id: i for i in combined.items if i.id in {v.id for v in snapshot.items}} == {
        i.id: i for i in snapshot.items
    }
    batch["knowledge_hash"] = combined.events_hash
    batch.pop("batch_id")
    batch["batch_id"] = "BOUNDED-" + digest(batch)[:16]
    assert source_fingerprints(engine, config) == before
    assert before == json.loads((ROOT / "baseline.json").read_text())
    files = {
        "preview.json": batch,
        "knowledge_diff.json": {
            "new_events_hash": combined.events_hash,
            "before": len(snapshot.items),
            "after": len(combined.items),
            "receipt_source_events": len(receipt_claims),
            "human_events_added": 0,
        },
        "selection_report.json": {
            "batch_id": batch["batch_id"],
            "size": len(batch["cards"]),
            "available": batch["available_composition"],
            "selected": batch["composition"],
            "previous_revisions": len(tables["confirmation_revisions"]),
            "fully_confirmed_excluded": True,
        },
    }
    for name, value in files.items():
        if (ROOT / name).exists():
            raise ValueError("PREPARATION_OUTPUT_EXISTS")
        private_write(ROOT / name, json.dumps(value, ensure_ascii=False, indent=2).encode())
    print(json.dumps(files["selection_report.json"]))
    engine.dispose()


if __name__ == "__main__":
    main()
