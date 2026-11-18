"""Sampo source fidelity, account isolation and append-only browser imports."""

import csv
import io
import json

import pytest

from apps.api.tests.test_import_workspace import factory as factory
from apps.api.tests.test_import_workspace import queue as queue
from apps.api.tests.test_import_workspace import workflow as workflow
from data_pipeline.ingest.bank_csv import BankInputError
from data_pipeline.normalize.sampo import HEADERS, SOURCE_TYPE, canonical_sampo
from data_pipeline.validate.bank import bank_enriched_schema


def export(*ids, **changes):
    out = io.StringIO()
    writer = csv.DictWriter(out, HEADERS)
    writer.writeheader()
    for identity in ids:
        writer.writerow(
            dict(
                transaction_date="2026-09-15",
                merchant="Example airline",
                description="Flight, sample",
                amount="-29.90",
                currency="EUR",
                sampo_category="Flights",
                source_account="Spanish Visa",
                source_transaction_id=identity,
                source_system="SAMPO",
            )
            | changes
        )
    return out.getvalue().encode()


def inspect(w, raw):
    return w.preview(raw, "sampo.csv", "", "browser", SOURCE_TYPE)


def test_canonical_preserves_evidence_without_confirming():
    frame = canonical_sampo(export("one"), "sampo.csv")
    bank_enriched_schema.validate(frame)
    row = frame.row(0, named=True)
    assert row["category"] == row["business_context"] == "unknown"
    assert json.loads(row["raw_source"])["sampo_category"] == "Flights"
    assert row["direction"] == "outgoing"
    assert canonical_sampo(export("refund", amount="29.90"), "r.csv")["direction"][0] == "incoming"


@pytest.mark.parametrize(
    "changes",
    [
        dict(currency="USD"),
        dict(source_system="OTHER"),
        dict(source_transaction_id=""),
        dict(amount="NaN"),
        dict(transaction_date="2026-02-30"),
    ],
)
def test_invalid_source_rejected(changes):
    with pytest.raises(BankInputError):
        canonical_sampo(export("one", **changes), "s.csv")


def test_append_overlap_conflict_and_account_isolation(workflow):
    before = workflow.read_tables()
    p = inspect(workflow, export("queue-synthetic-0", "two"))
    assert p["new_rows"] == 2 and p["account"] == "Spanish Visa"
    assert p["new_preview"][0]["merchant"] == "Example airline"
    assert workflow.read_tables() == before
    result = workflow.commit(p["token"], "browser")
    assert result["new_rows"] == 2
    after = workflow.read_tables()
    for table, rows in before.items():
        current = {r["id"]: r for r in after[table]}
        assert all(current[r["id"]] == r for r in rows)
    duplicate = inspect(workflow, export("queue-synthetic-0", "two"))
    assert duplicate["duplicates"] == 2 and duplicate["new_rows"] == 0
    workflow.commit(duplicate["token"], "browser")
    assert workflow.read_tables() == after
    overlap = inspect(workflow, export("two", "three"))
    assert overlap["duplicates"] == overlap["new_rows"] == 1
    workflow.commit(overlap["token"], "browser")
    conflict = inspect(workflow, export("two", amount="-30.00"))
    assert conflict["validation"] == "INVALID" and "token" not in conflict
    other = inspect(workflow, export("two", source_account="Other Visa"))
    assert other["new_rows"] == 1


def test_sampo_acceptance_rejects_historical_mutation(workflow):
    from copy import deepcopy

    from data_pipeline.load.bank import import_bank_bytes
    from data_pipeline.normalize.sampo import PARSER_VERSION, sampo_account
    from tapio.confirmation.source_updates import accept_bank_import

    raw = export("new")
    before = workflow.read_tables()
    result = import_bank_bytes(
        raw,
        source_filename="sampo.csv",
        account_key=sampo_account(canonical_sampo(raw, "sampo.csv"))[1],
        session_factory=workflow.queue.factory,
        source_type=SOURCE_TYPE,
        parser_version=PARSER_VERSION,
        normalize=canonical_sampo,
    )
    assert result.status == "imported"
    after = workflow.read_tables()
    changed = deepcopy(after)
    old_id = before["transactions"][0]["id"]
    next(t for t in changed["transactions"] if t["id"] == old_id)["amount"] = "999"
    with pytest.raises(ValueError, match="HISTORICAL_SOURCE_CHANGED"):
        accept_bank_import(workflow.queue, before, changed, result, raw)
    changed = deepcopy(after)
    new = next(
        t for t in changed["transactions"] if t["import_run_id"] == str(result.import_run_id)
    )
    new["raw_source"]["sampo_category"] = "altered"
    with pytest.raises(ValueError, match="BANK_TRANSACTION_SOURCE_MISMATCH"):
        accept_bank_import(workflow.queue, before, changed, result, raw)
    accept_bank_import(workflow.queue, before, after, result, raw)
