"""Offline CSV utilization, knowledge replay and bounded confirmation-batch preparation."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from data_pipeline.ingest.bank_csv import parse_bank_csv
from data_pipeline.ingest.bank_fields import BANK_FIELDS, audit_columns
from tapio.knowledge.backfill import accrue
from tapio.knowledge.bank_evidence import document_candidates, purpose_evidence
from tapio.knowledge.models import KnowledgeEvent, digest
from tapio.knowledge.store import load_bundle, save_bundle
from tapio.suggestions.full_fields import FullFieldGenerator
from tapio.suggestions.generate import Generator, eligible

ROOT = Path("data/interim/full_csv_confirmation")
OLD = Path(
    "data/interim/knowledge/snapshot-eae685e64e66ff21f4803d843e84b1565dc769e83fe0008869390ed9b395c881.json"
)


def write(name, value):
    p = ROOT / name
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    p.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, required=True)
    args = parser.parse_args()
    ROOT.mkdir(exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    tables = json.loads((ROOT / "source.json").read_text())
    txs = tables["transactions"]
    reviews = {r["transaction_id"]: r for r in tables["transaction_label_reviews"]}
    files = []
    sources = {}
    for name in sorted({t["source_file"] for t in txs}):
        p = args.csv_dir / name
        raw = p.read_bytes()
        parsed = parse_bank_csv(raw)
        with p.open(encoding="utf-8-sig", newline="") as f:
            columns = next(csv.reader(f, delimiter=";"))
        assert audit_columns(columns)["exact_order"]
        assert any(r["sha256"] == hashlib.sha256(raw).hexdigest() for r in tables["import_runs"])
        rows = list(parsed.iter_rows(named=True))
        sources[name] = {r["Arkistointitunnus"]: r for r in rows}
        files.append(
            {
                "file": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "rows": len(rows),
                "columns": columns,
            }
        )
    for tx in txs:
        assert sources[tx["source_file"]][tx["source_transaction_id"]] == tx["raw_source"]
        assert (tx["raw_source"]["Viesti"] or None) == tx["message"]
    inventory = []
    for column, spec in BANK_FIELDS.items():
        inventory.append(
            {
                "column": column,
                **asdict(spec),
                "parsed": True,
                "raw_preserved": True,
                "populated_transactions": sum(bool(t["raw_source"][column]) for t in txs),
                "normalized": column
                in {"Kirjauspäivä", "Arvopäivä", "Määrä EUROA", "Saaja/Maksaja", "Viite"},
                "knowledge": "Schema definition; source observation"
                if spec.vocabulary
                else "Schema definition",
                "suggestions": "Evidence only; never a confirmed label"
                if spec.vocabulary
                else "Structured provenance",
                "previous_generic_search": column in {"Selitys", "Viesti", "Saaja/Maksaja"},
            }
        )
    write(
        "csv_audit.json",
        {
            "files": files,
            "inventory": inventory,
            "preserved_transactions": len(txs),
            "viesti_populated": sum(bool(t["message"]) for t in txs),
            "viesti_differs_from_selitys": sum(
                bool(t["message"]) and t["message"] != t["raw_source"]["Selitys"] for t in txs
            ),
            "backfill_required": False,
        },
    )
    old = load_bundle(OLD)
    events = [
        KnowledgeEvent.model_validate(e)
        for e in json.loads(OLD.with_name("events-" + old.events_hash + ".json").read_text())
    ]
    when = datetime.fromisoformat("2026-10-27T00:00:00+01:00")
    enriched = save_bundle(ROOT / "knowledge", events + accrue(tables, observed_at=when))
    old_by = {i.id: i for i in old.items}
    new_by = {i.id: i for i in enriched.items}
    assert set(old_by) <= set(new_by)
    assert all(new_by[k].claim.authority == v.claim.authority for k, v in old_by.items())
    write(
        "knowledge_diff.json",
        {
            "before": len(old.items),
            "after": len(enriched.items),
            "added": len(set(new_by) - set(old_by)),
            "removed": 0,
            "prior_authorities_changed": 0,
            "new_by_kind": dict(Counter(new_by[k].claim.kind for k in set(new_by) - set(old_by))),
            "new_events_hash": enriched.events_hash,
            "old_events_hash": old.events_hash,
        },
    )
    g0 = Generator(old, txs, list(reviews.values()), when)
    g1 = FullFieldGenerator(enriched, txs, list(reviews.values()), when)
    before = []
    after = []
    for t in sorted(txs, key=lambda t: (t["booking_date"], t["id"])):
        if eligible(t, reviews):
            before.append(g0.card(t, g0.signals(t)))
            after.append(g1.card(t, g1.signals(t)))
    comparison = {
        "unresolved": len(after),
        "additional_category": 0,
        "additional_context": 0,
        "reduced_abstentions": 0,
        "unchanged_abstentions": 0,
        "new_conflicts": 0,
    }
    for a, b in zip(before, after, strict=True):
        comparison["additional_category"] += (
            a.suggestion.category is None and b.suggestion.category is not None
        )
        comparison["additional_context"] += (
            a.suggestion.context is None and b.suggestion.context is not None
        )
        abstain = not a.suggestion.category and not a.suggestion.context
        comparison["reduced_abstentions"] += bool(
            abstain and (b.suggestion.category or b.suggestion.context)
        )
        comparison["unchanged_abstentions"] += bool(
            abstain and not b.suggestion.category and not b.suggestion.context
        )
        comparison["new_conflicts"] += bool(not a.conflicting_knowledge and b.conflicting_knowledge)
    write("suggestion_comparison.json", comparison)
    write(
        "suggestions_v2.json",
        {
            "version": "FULL_CSV_CARDS_V2",
            "knowledge_hash": enriched.events_hash,
            "cards": [c.model_dump(mode="json") for c in after],
        },
    )
    after_by = {c.transaction.id: c for c in after}
    pay = []
    for t in txs:
        if t["normalized_counterparty"] != "Paytrail Oyj":
            continue
        links = document_candidates(
            t, tables["invoices"], tables["transaction_invoice_allocations"]
        )
        r = reviews.get(t["id"])
        c = after_by.get(t["id"])
        related = [
            i.model_dump(mode="json")
            for i in enriched.items
            if i.claim.subject == t["id"] or i.claim.scope == t["id"]
        ]
        pay.append(
            {
                "transaction": t,
                "review": r,
                "document_candidates": links or [{"status": "NO_MATCH"}],
                "purpose": purpose_evidence(t, r, links),
                "suggestion": c.suggestion.model_dump() if c else None,
                "knowledge_evidence": related,
            }
        )
    pay_summary = {
        "total": len(pay),
        "viesti_populated": sum(bool(p["transaction"]["message"]) for p in pay),
        "recipient_visible": sum(p["purpose"]["recipient_visible"] for p in pay),
        "purpose_status": dict(Counter(p["purpose"]["classification"] for p in pay)),
        "human_reviewed": sum(
            p["review"] is not None and p["review"]["review_status"] == "REVIEWED" for p in pay
        ),
        "unresolved_with_category_suggestion": sum(
            bool(p["suggestion"] and p["suggestion"]["category"]) for p in pay
        ),
        "unresolved_with_context_suggestion": sum(
            bool(p["suggestion"] and p["suggestion"]["context"]) for p in pay
        ),
        "new_confirmed_document_links": 0,
        "gmail_calls": 0,
        "pdf_equivalent": (
            "No imported bank-PDF transaction/message schema; accepted documents inspected only."
        ),
    }
    write("paytrail.json", {"summary": pay_summary, "rows": pay})
    selected = []
    for merchant in [
        "Elenia Verkko Oyj",
        "Vattenfall Oy",
        "s-market viitasaari viitasaari",
        "clinica dental agua madrid",
    ]:
        c = next(
            (
                c
                for c in after
                if c.transaction.merchant == merchant
                and c.suggestion.category
                and c.suggestion.context
                and not c.conflicting_knowledge
                and c.priority != "AMBIGUOUS_REVIEW"
            ),
            None,
        )
        if c:
            selected.append(c)
    # No newly exposed message alone is promoted to strong enough for the write allowlist.
    # Prefer a second clear electricity row to an unresolved processor/multi-context row.
    c = next(
        (
            c
            for c in after
            if c.transaction.merchant == "Elenia Verkko Oyj"
            and c not in selected
            and c.suggestion.category
            and c.suggestion.context
            and c.priority != "AMBIGUOUS_REVIEW"
        ),
        None,
    )
    if c:
        selected.append(c)
    assert 1 <= len(selected) <= 5
    cards = []
    by_tx = {t["id"]: t for t in txs}
    for c in selected:
        t = by_tx[c.transaction.id]
        r = reviews.get(t["id"])
        confirmed = r and r["review_status"] == "REVIEWED"
        state = {
            "category": r["confirmed_category"] if confirmed else None,
            "context": r["confirmed_business_context"] if confirmed else None,
            "authority": {
                "category": "HUMAN_CONFIRMED" if confirmed else "UNKNOWN",
                "context": "HUMAN_CONFIRMED" if confirmed else "UNKNOWN",
            },
        }
        row = c.model_dump(mode="json")
        row["source_hash"] = digest(t)
        row["initial_state_hash"] = digest(
            {"transaction": t, "legacy_review": r, "latest_revision": None, "state": state}
        )
        row["source_messages"] = {k: t["raw_source"].get(k) for k in ("Selitys", "Viesti")}
        cards.append(row)
    write(
        "preview.json",
        {
            "version": "CONFIRMATION_PREVIEW_V1",
            "cards": cards,
            "cards_hash": digest(cards),
            "source_fingerprints": json.loads((ROOT / "baseline.json").read_text()),
            "knowledge_hash": enriched.events_hash,
        },
    )
    lines = [
        "# Bank source-field utilization audit",
        "",
        "Generated from the three imported original CSVs; no sensitive values.",
        "All 11 columns are parsed and preserved exactly in raw_source. No backfill is needed.",
        "Viesti was already mapped to message and searchable as raw_description. "
        "This repair adds explicit source provenance and shared usage.",
        "",
        "| Column | Class | Stored projection | Text search | "
        "Knowledge / suggestions | Reconciliation / exclusions |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i in inventory:
        lines.append(
            "| "
            + " | ".join(
                [
                    i["column"],
                    i["classification"],
                    i["stored"],
                    str(i["searchable"]),
                    i["knowledge"] + "; " + i["suggestions"],
                    i["reconciliation"] + "; " + i["exclusion"],
                ]
            )
            + " |"
        )
    lines += [
        "",
        "Dates and amounts use structured filters/arithmetic, not text search. "
        "Account/BIC and archive IDs remain private metadata; "
        "they are not vocabulary or purpose evidence.",
        "Reference matching is candidate evidence. Message text cannot override canonical "
        "payee identity or establish confirmed category/context/tax treatment.",
        "Unknown or reordered source headers fail ingestion and require explicit schema review.",
        "Named-subject matching uses identity fields only; "
        "source messages are attached as supporting evidence.",
        "New derived knowledge retains all prior claims and authorities. "
        "Historical suggestion/feedback artifacts are untouched.",
    ]
    Path("docs/bank_source_field_audit.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "csv_columns": len(inventory),
                "transactions_preserved": len(txs),
                "paytrail": pay_summary,
                "suggestion_comparison": comparison,
                "preview_cards": len(cards),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
