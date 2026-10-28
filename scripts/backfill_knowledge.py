"""Explicit offline read-only source scan; writes only private derived knowledge artifacts."""

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from apps.api.app.domain.models import Document
from tapio.confirmation.replay import replay_confirmations
from tapio.knowledge.backfill import (
    accepted_contract_events,
    accrue,
    reviewed_email_events,
    reviewed_export_decision_events,
)
from tapio.knowledge.models import canonical
from tapio.knowledge.queries import KnowledgeQueries
from tapio.knowledge.store import rebuild, save_bundle
from tapio.pilot.config import load_config, readonly_engine, readonly_session, source_fingerprints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observed-at", required=True, help="Explicit ISO timestamp for replayability"
    )
    parser.add_argument("--output", type=Path, default=Path("data/interim/knowledge"))
    args = parser.parse_args()
    when = datetime.fromisoformat(args.observed_at)
    if when.tzinfo is None:
        parser.error("observed-at must include timezone")
    if args.output.resolve().is_relative_to(Path("data/interim").resolve()) is False:
        parser.error("derived output must be under data/interim")
    os.environ["TAPIO_PILOT_MODE"] = "true"
    config, _ = load_config()
    engine = readonly_engine()
    before = source_fingerprints(engine, config)
    tables = {}
    wanted = (
        "transactions",
        "transaction_label_reviews",
        "documents",
        "invoices",
        "transaction_invoice_allocations",
        "transaction_reversal_candidates",
        "confirmation_revisions",
    )
    with readonly_session(engine) as db:
        for name in wanted:
            table = Document.metadata.tables[name]
            rows = db.execute(select(table).limit(100001)).mappings().all()
            if len(rows) > 100000:
                raise ValueError("KNOWLEDGE_BACKFILL_LIMIT")
            tables[name] = json.loads(json.dumps([dict(r) for r in rows], default=str))
    events = accrue(tables, observed_at=when)
    events += accepted_contract_events(
        Path("data/interim/energy_cost/accepted_supplier_contracts.json"),
        Path("data/interim/energy_cost/supplier_acceptance.json"),
        observed_at=when,
    )
    for path in sorted(Path("data/interim/gmail/evidence").glob("*.json")):
        events += reviewed_email_events(path)
    events += reviewed_export_decision_events(
        Path("data/interim/gmail/export_research/invoice_settlement_review.json"),
        observed_at=when,
    )
    if tables["confirmation_revisions"]:
        from tapio.pilot.subject_identity import resolve_subject

        names = {
            t["normalized_counterparty"]
            for t in tables["transactions"]
            if t.get("normalized_counterparty")
        }
        merchants = {
            t["id"]: resolve_subject(t.get("normalized_counterparty") or "", names)[
                "canonical_subject"
            ]
            or t.get("normalized_counterparty")
            for t in tables["transactions"]
        }
        _, events = replay_confirmations(events, tables["confirmation_revisions"], merchants)
    snapshot = save_bundle(args.output, events)
    assert rebuild(list(reversed(events))) == snapshot
    assert rebuild(events + events) == snapshot
    assert before == source_fingerprints(engine, config)
    queries = KnowledgeQueries(snapshot)
    examples = {
        name: {
            "aliases": [i.model_dump(mode="json") for i in queries.get_known_aliases(name)],
            "observations": queries.get_merchant_observations(name),
        }
        for name in ("Vattenfall Oy", "Elenia Verkko Oyj", "Oikea Konekauppa", "K-Rauta")
    }
    examples["talletuskorko"] = [
        i.model_dump(mode="json") for i in queries.get_known_vocabulary("talletuskorko")
    ]
    examples["contract_facts"] = [
        i.model_dump(mode="json") for i in snapshot.items if i.claim.kind == "CONTRACT_FACT"
    ]
    examples["reversal_ambiguity"] = [
        i.model_dump(mode="json")
        for i in snapshot.items
        if i.claim.predicate == "possible_reversal"
    ]
    uses = {
        q: queries.prepare_search(q).model_dump(mode="json")
        for q in ("Vattenfall", "Elenia", "Oikea Konekauppa", "farmacia", "talletuskorko")
    }
    report = {
        "source_tables_unchanged": len(before),
        "source_row_counts": {k: len(v) for k, v in tables.items()},
        "event_count": len(events),
        "item_count": len(snapshot.items),
        "by_type": dict(sorted(Counter(i.claim.kind.value for i in snapshot.items).items())),
        "by_authority": dict(
            sorted(Counter(i.claim.authority.value for i in snapshot.items).items())
        ),
        "contradictions": len(snapshot.contradictions),
        "replay_verified": True,
        "events_hash": snapshot.events_hash,
        "examples": examples,
        "search_reuse": uses,
        "live_model_calls": 0,
        "gmail_calls": 0,
    }
    report_path = args.output / ("inventory-" + snapshot.events_hash + ".json")
    report_path.write_text(canonical(report))
    report_path.chmod(0o600)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("examples", "search_reuse")}, indent=2
        )
    )
    engine.dispose()


if __name__ == "__main__":
    main()
