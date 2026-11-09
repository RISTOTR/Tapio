"""Only verified append-only production bank imports may advance review source guards."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from apps.api.app.domain.models import Document
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_group_review import factory as factory
from apps.api.tests.test_group_review import queue as queue
from data_pipeline.labels.snapshot import fingerprint
from data_pipeline.load.bank import import_bank_bytes
from tapio.confirmation.source_updates import accept_bank_import, accepted_fingerprints


def tables(queue):
    with queue.factory() as db:
        result = {
            n: [dict(r) for r in db.execute(select(t)).mappings()]
            for n, t in Document.metadata.tables.items()
        }
    return json.loads(json.dumps(result, default=str))


@pytest.fixture
def imported(queue):
    before = tables(queue)
    queue.save_manifest(
        {
            **queue.manifest(),
            "source_fingerprints": {n: fingerprint(rows) for n, rows in before.items()},
        }
    )
    raw = source_bytes([source_row(Arkistointitunnus="ongoing-source-append")])
    result = import_bank_bytes(
        raw, source_filename="new.csv", account_key="queue-test", session_factory=queue.factory
    )
    assert result.status == "imported"
    return queue, before, tables(queue), result, raw


def test_verified_bank_append_preserves_windows_and_accepts_new_fingerprint(imported):
    q, before, after, result, raw = imported
    old = q.manifest()
    data = accept_bank_import(q, before, after, result, raw)
    assert accepted_fingerprints(q, old["source_fingerprints"]) == data["source_fingerprints"]
    assert q.manifest()["active"] == old["active"]
    assert q.manifest()["windows"] == old["windows"]
    assert len(q.manifest()["transaction_ids"]) == len(old["transaction_ids"]) + 1
    assert before["confirmation_revisions"] == after["confirmation_revisions"]
    assert before["transaction_label_reviews"] == after["transaction_label_reviews"]


@pytest.mark.parametrize("mutation", ["historical", "new_label", "source_bytes", "unrelated_table"])
def test_import_acceptance_rejects_unproven_changes(imported, mutation):
    q, before, original, result, raw = imported
    after = deepcopy(original)
    if mutation == "historical":
        row = next(r for r in after["transactions"] if r["id"] == before["transactions"][0]["id"])
        row["category"] = "timber_income"
    elif mutation == "new_label":
        row = next(
            r for r in after["transactions"] if r["import_run_id"] == str(result.import_run_id)
        )
        row["category"] = "timber_income"
    elif mutation == "source_bytes":
        raw += b"\n"
    else:
        after["confirmation_revisions"].append({"id": "unapproved-human-decision"})
    with pytest.raises(ValueError):
        accept_bank_import(q, before, after, result, raw)
    assert not (q.root / "ongoing_sources.json").exists()


def test_signed_source_acceptance_tamper_and_manifest_mismatch_rejected(imported):
    q, before, after, result, raw = imported
    accept_bank_import(q, before, after, result, raw)
    path = q.root / "ongoing_sources.json"
    envelope = json.loads(path.read_text())
    envelope["data"]["source_fingerprints"]["transactions"]["count"] += 1
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="INTEGRITY"):
        accepted_fingerprints(q, {})


def test_original_source_guard_remains_when_no_acceptance(queue):
    expected = {"transactions": {"count": 35, "sha256": "synthetic"}}
    assert accepted_fingerprints(queue, expected) == expected
