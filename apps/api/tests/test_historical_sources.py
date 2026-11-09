"""Append-only startup protection; synthetic evidence only."""

import json
import os
import subprocess
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from apps.api.app.domain.models import Document
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.labels.snapshot import fingerprint
from data_pipeline.load.bank import import_bank_bytes
from tapio.pilot import config
from tapio.pilot.historical_sources import verify_historical_sources


def historical():
    return {
        "transactions": [
            {
                "id": "old",
                "amount": "-12.340000",
                "booking_date": "2025-01-15",
                "merchant": "Synthetic merchant",
                "source_namespace": "bank:test",
                "source_transaction_id": "old-source",
                "import_run_id": "run-1",
                "raw_source": {"message": "Original"},
                "source_file": "original.csv",
            }
        ]
    }


def expected(rows):
    return {name: fingerprint(values) for name, values in rows.items()}


def test_unchanged_zero_or_new_rows():
    old = historical()
    verify_historical_sources(deepcopy(old), old, expected(old))
    current = deepcopy(old)
    current["transactions"].append(
        {**old["transactions"][0], "id": "new", "source_transaction_id": "new-source"}
    )
    verify_historical_sources(current, old, expected(old))


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "-99.000000"),
        ("booking_date", "2025-02-01"),
        ("merchant", "Changed merchant"),
        ("source_file", "replacement.csv"),
        ("source_namespace", "different-bank"),
        ("source_transaction_id", "changed-source"),
        ("import_run_id", "different-run"),
        ("raw_source", {"message": "Changed provenance"}),
    ],
)
def test_historical_field_mutation_rejected(field, value):
    old = historical()
    current = deepcopy(old)
    current["transactions"][0][field] = value
    with pytest.raises(ValueError, match="HISTORICAL_SOURCE_CHANGED"):
        verify_historical_sources(current, old, expected(old))


def test_deletion_even_when_replaced_with_equal_row_count():
    old = historical()
    for rows in [[], [{**old["transactions"][0], "id": "replacement"}]]:
        with pytest.raises(ValueError, match="HISTORICAL_SOURCE_DELETED"):
            verify_historical_sources({"transactions": rows}, old, expected(old))


@pytest.mark.parametrize("new_id", ["old", "collision"])
def test_duplicate_primary_or_bank_identity_rejected(new_id):
    old = historical()
    current = deepcopy(old)
    current["transactions"].append({**old["transactions"][0], "id": new_id})
    with pytest.raises(ValueError, match="DUPLICATE"):
        verify_historical_sources(current, old, expected(old))


def test_archive_cannot_be_regenerated_from_modified_live_rows():
    old = historical()
    replacement = deepcopy(old)
    replacement["transactions"][0]["amount"] = "-999.000000"
    with pytest.raises(ValueError, match="ARCHIVE_NOT_AUTHENTICATED"):
        verify_historical_sources(replacement, replacement, expected(old))


def test_database_types_preserve_original_fingerprint_and_additional_fields_fail():
    old = historical()
    current = deepcopy(old)
    current["transactions"][0].update(amount=Decimal("-12.340000"), booking_date=date(2025, 1, 15))
    verify_historical_sources(current, old, expected(old))
    current["transactions"][0]["unexpected_source_field"] = "added"
    with pytest.raises(ValueError, match="HISTORICAL_SOURCE_CHANGED"):
        verify_historical_sources(current, old, expected(old))


def test_append_review_events_without_replacing_old_records():
    old = {"transaction_label_reviews": [{"id": "review-1", "category": "OTHER"}]}
    current = {
        "transaction_label_reviews": old["transaction_label_reviews"]
        + [{"id": "review-2", "category": "TRAVEL"}]
    }
    verify_historical_sources(current, old, expected(old))


def test_normal_import_repeat_import_restart_and_missing_archive(factory, tmp_path, monkeypatch):
    def read_rows():
        with factory() as db:
            return {
                n: [dict(r) for r in db.execute(select(t)).mappings()]
                for n, t in Document.metadata.tables.items()
            }

    def ingest(identity):
        return import_bank_bytes(
            source_bytes([source_row(Arkistointitunnus=identity)]),
            source_filename="synthetic.csv",
            account_key="historical-guard",
            session_factory=factory,
        )

    assert ingest("protected-original").status == "imported"
    old = read_rows()
    baseline = {"source_fingerprints": expected(old)}
    archive = tmp_path / "historical.json"
    archive.write_text(json.dumps(old, default=str))
    monkeypatch.setattr(config, "HISTORICAL_SOURCE_ROWS", archive)
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    engine = factory.kw["bind"]
    try:
        assert config.source_fingerprints(engine, baseline) == baseline["source_fingerprints"]
        assert ingest("monthly-new").status == "imported"
        actual = config.source_fingerprints(engine, baseline)
        assert (
            actual["transactions"]["count"]
            == baseline["source_fingerprints"]["transactions"]["count"] + 1
        )
        ingest("monthly-new")  # Normal duplicate import path must also be allowed.
        after_repeat = config.source_fingerprints(engine, baseline)
        assert after_repeat["transactions"] == actual["transactions"]
        # Fresh process, no cached identities or in-memory acceptance state.
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(baseline))
        code = """import json,sys
from pathlib import Path
from tapio.pilot import config
config.HISTORICAL_SOURCE_ROWS=Path(sys.argv[2])
from sqlalchemy import create_engine
engine=create_engine(sys.argv[3])
try:
 config.source_fingerprints(engine,json.loads(Path(sys.argv[1]).read_text()))
 print('RESTART_PASS')
finally: engine.dispose()
"""
        result = subprocess.run(
            [".venv/bin/python", "-c", code, str(cfg), str(archive), url],
            env=os.environ,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "RESTART_PASS" in result.stdout
        assert expected(json.loads(archive.read_text())) == baseline["source_fingerprints"]
        archive.unlink()
        with pytest.raises(ValueError, match="SOURCE_SNAPSHOT_CHANGED"):
            config.source_fingerprints(engine, baseline)
    finally:
        engine.dispose()
