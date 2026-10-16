"""Synthetic regressions for importing human choices from the original Phase 07 queue."""

import csv
import io
import json
from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from apps.api.app.domain.models import Transaction, TransactionLabelReview
from apps.api.tests.test_energy_load import factory as factory
from apps.api.tests.test_transaction_labels import registered as registered
from data_pipeline.labels.contracts import FACT_FIELDS, ReviewError
from data_pipeline.labels.merchant_policy import AMBIGUOUS_REASON, ambiguous_merchant
from data_pipeline.labels.phase07_input import COLUMNS
from data_pipeline.labels.review_input import parse_import
from data_pipeline.labels.snapshot import fingerprint, freeze, review_coverage
from data_pipeline.labels.workflow import import_reviews
from data_pipeline.normalize.bank import suggest
from tapio.agent.acceptance.audit import priority


def original(rows):
    return [
        {
            **dict.fromkeys(COLUMNS, ""),
            **{k: r[k] for k in FACT_FIELDS},
            "weak_category": r["suggested_category"].lower(),
            "weak_context": r["suggested_business_context"].lower(),
        }
        for r in rows
    ]


def encode(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, COLUMNS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def test_import_dry_run_idempotency_and_source_integrity(factory, registered):
    _, rows, _ = registered
    manifest = original(rows)
    decisions = deepcopy(manifest)
    decisions[0].update(confirmed_category="OTHER", confirmed_context="PERSONAL")
    raw = encode(decisions)
    with factory.begin() as s:
        s.execute(delete(TransactionLabelReview))
        before = [dict(r) for r in s.execute(select(Transaction.__table__)).mappings()]
    options = dict(reviewer="synthetic", factory=factory, phase07_manifest=manifest)
    assert import_reviews(raw, **options, dry_run=True)["reviewed_rows_inserted"] == 1
    with factory() as s:
        assert list(s.scalars(select(TransactionLabelReview))) == []
    first = import_reviews(raw, **options)
    assert first["reviewed_rows_inserted"] == 1 and first["unreviewed"] == 3
    with factory() as s:
        record = s.scalar(select(TransactionLabelReview))
        assert (
            record.confirmed_category == "OTHER" and record.confirmed_business_context == "PERSONAL"
        )
        assert record.suggested_category_snapshot == "UNKNOWN"
        assert record.taxonomy_version == "2" and record.label_source == "human_phase07_csv_v1"
        timestamp = record.reviewed_at
    assert import_reviews(raw, **options)["unchanged"] == 1
    with factory() as s:
        assert s.scalar(select(TransactionLabelReview)).reviewed_at == timestamp
        assert fingerprint(before) == fingerprint(
            [dict(r) for r in s.execute(select(Transaction.__table__)).mappings()]
        )
        coverage = review_coverage(
            s, year=s.get(Transaction, UUID(rows[0]["transaction_id"])).booking_date.year
        )
        assert coverage["human_reviewed"] == 1 and coverage["unresolved"] == 3
        assert coverage["coverage_status"] == "UNKNOWN_COVERAGE"
    decisions[0]["confirmed_context"] = "FORESTRY"
    with pytest.raises(ReviewError, match="existing_review_conflict"):
        import_reviews(encode(decisions), **options)


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed_category": "INVALID", "confirmed_context": "PERSONAL"},
        {"confirmed_category": "OTHER", "confirmed_context": "INVALID"},
        {"confirmed_category": "OTHER"},
        {"confirmed_context": "PERSONAL"},
        {"transaction_id": ""},
        {"amount": "999"},
    ],
)
def test_invalid_input_rejected(registered, changes):
    manifest = original(registered[1])
    rows = deepcopy(manifest)
    rows[0].update(changes)
    with pytest.raises(ReviewError):
        parse_import(encode(rows), phase07_manifest=manifest)


def test_identity_registration_and_no_label_inference(registered):
    manifest = original(registered[1])
    raw = encode(manifest)
    with pytest.raises(ReviewError, match="original_queue_required"):
        parse_import(raw)
    with pytest.raises(ReviewError, match="duplicate_transaction_id"):
        parse_import(encode(manifest + [manifest[0]]), phase07_manifest=manifest)
    with pytest.raises(ReviewError, match="identity_mismatch"):
        parse_import(encode(manifest[:-1]), phase07_manifest=manifest)
    parsed, _ = parse_import(raw, phase07_manifest=manifest)
    assert all(r["review_status"] == "UNREVIEWED" and not r["reviewed_category"] for r in parsed)


@pytest.mark.parametrize("name", ["Tokmanni Viitasaari", "K-Rauta", "Oikea Konekauppa Oy"])
def test_prospective_ambiguous_merchants_have_no_context_inference(name):
    from decimal import Decimal
    from types import SimpleNamespace

    assert ambiguous_merchant(name)
    assert suggest(name, "outgoing")["business_context"] == "unknown"
    t = SimpleNamespace(
        normalized_counterparty=name, business_context=None, category=None, amount=Decimal(-10)
    )
    assert priority(t, [], []) == ("P2", [AMBIGUOUS_REASON])


def test_snapshot_is_private_and_cannot_overwrite_history(tmp_path):
    path = tmp_path / "snapshot.json"
    freeze(path, {"coverage": "UNKNOWN_COVERAGE", "holdout_hash_source": "recorded_manifest"})
    old = path.read_bytes()
    with pytest.raises(FileExistsError):
        freeze(path, {"replacement": True})
    assert path.read_bytes() == old
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(old)["coverage"] == "UNKNOWN_COVERAGE"
