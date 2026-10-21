"""Synthetic-only human-label contracts, sampling, privacy and persistence tests."""

import os
import subprocess
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import polars as pl
import pytest
from sqlalchemy import select

from apps.api.app.domain.enums import BusinessContext
from apps.api.app.domain.models import Transaction, TransactionLabelReview
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.labels.contracts import (
    CATEGORIES,
    CONTEXTS,
    QUEUE_COLUMNS,
    ReviewError,
    encode_queue,
    parse_reviews,
    safe_text,
)
from data_pipeline.labels.sampling import MERCHANT_CAP, sample_transactions
from data_pipeline.labels.workflow import (
    ground_truth,
    import_reviews,
    prepare_queue,
    quality_report,
)
from data_pipeline.load.bank import import_bank_bytes


def queue_row(**overrides):
    row = dict.fromkeys(QUEUE_COLUMNS, "")
    row.update(transaction_id=str(UUID(int=1)), review_status="UNREVIEWED")
    row.update(overrides)
    return row


@pytest.mark.parametrize("category", CATEGORIES)
def test_allowed_categories(category):
    rows = parse_reviews(
        encode_queue(
            [
                queue_row(
                    review_status="REVIEWED",
                    reviewed_category=category,
                    reviewed_business_context="UNKNOWN",
                )
            ]
        )
    )
    assert rows[0]["reviewed_category"] == category


@pytest.mark.parametrize("context", CONTEXTS)
def test_allowed_contexts(context):
    parse_reviews(
        encode_queue(
            [
                queue_row(
                    review_status="REVIEWED",
                    reviewed_category="FUEL",
                    reviewed_business_context=context,
                )
            ]
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {
            "review_status": "REVIEWED",
            "reviewed_category": "invalid",
            "reviewed_business_context": "PERSONAL",
        },
        {
            "review_status": "REVIEWED",
            "reviewed_category": "FUEL",
            "reviewed_business_context": "MIXED",
        },
        {
            "review_status": "REVIEWED",
            "reviewed_category": "",
            "reviewed_business_context": "PERSONAL",
        },
        {"review_status": "UNREVIEWED", "reviewed_category": "FUEL"},
        {"review_status": "SKIPPED_AMBIGUOUS", "review_notes": ""},
        {"review_status": "AUTO_CONFIRMED"},
        {"transaction_id": "not-a-uuid"},
    ],
)
def test_invalid_review_rejected(changes):
    with pytest.raises(ReviewError):
        parse_reviews(encode_queue([queue_row(**changes)]))


def test_duplicate_review_rows_rejected():
    with pytest.raises(ReviewError, match="duplicate_transaction_id"):
        parse_reviews(encode_queue([queue_row(), queue_row()]))


def test_csv_schema_and_ambiguous_review():
    row = queue_row(review_status="SKIPPED_AMBIGUOUS", review_notes="Purpose unclear, no receipt")
    assert parse_reviews(encode_queue([row])) == [row]
    with pytest.raises(ReviewError, match="invalid_review_columns"):
        parse_reviews(b"transaction_id,raw_source\n123,secret\n")


def synthetic_sample():
    rows = []
    for i in range(200):
        kind = i % 5
        merchant = [
            "Vattenfall Oy",
            "Elenia Verkko Oyj",
            "Example Timber Buyer Oy",
            f"Synthetic shop {i}",
            f"Synthetic fuel {i}",
        ][kind]
        rows.append(
            {
                "transaction_id": str(UUID(int=i + 1)),
                "source_transaction_id": f"SYN-{i}",
                "source_namespace": "synthetic",
                "booking_date": date(2026, 1, 1),
                "amount": Decimal(i + 1) * (1 if i % 7 == 0 else -1),
                "currency": "EUR",
                "normalized_counterparty": merchant,
                "ultimate_recipient": None,
                "payment_intermediary": None,
                "message": None,
                "reference": None,
                "category": "electricity" if kind == 0 else "unknown",
                "business_context": "property"
                if kind < 2
                else ("forestry" if kind == 2 else "unknown"),
            }
        )
    return pl.DataFrame(rows, schema_overrides={"amount": pl.Decimal(20, 6)})


def test_sample_deterministic_balanced_and_mixed():
    frame = synthetic_sample()
    a, report = sample_transactions(frame)
    b, report2 = sample_transactions(frame.reverse())
    assert [r["transaction_id"] for r in a] == [r["transaction_id"] for r in b]
    assert report == report2 and len(a) == 98  # 80 unique shops + 3 capped groups of 6
    assert report["maximum_merchant_count"] <= MERCHANT_CAP
    assert report["strata_selected"]["property_rule"] > 0
    assert report["strata_selected"]["unknown_context"] > 0
    assert report["strata_selected"]["credit"] > 0 and report["strata_selected"]["debit"] > 0


def test_sample_preserves_refund_relationship_rows():
    frame = (
        synthetic_sample()
        .head(3)
        .with_columns(
            pl.lit("Synthetic merchant").alias("normalized_counterparty"),
            pl.Series("booking_date", [date(2026, 1, 1), date(2026, 1, 2), date(2026, 2, 1)]),
            pl.Series(
                "amount", [Decimal("-20"), Decimal("-20"), Decimal("20")], dtype=pl.Decimal(20, 6)
            ),
        )
    )
    rows, report = sample_transactions(frame, target=3)
    assert len(rows) == report["mandatory_relationship_rows"] == 3
    assert all("Unresolved refund candidate" in r["review_hint"] for r in rows)
    assert all("SYN-" not in r["review_hint"] for r in rows)


def test_text_redaction_and_spreadsheet_safety():
    assert safe_text("account FI12 1234 1234 1234 12") == "account [REDACTED IBAN]"
    text = safe_text("code SYNTHETIC-ARCHIVE and BANKFIHH", ["SYNTHETIC-ARCHIVE", "BANKFIHH"])
    assert "ARCHIVE" not in text and "BANKFIHH" not in text
    assert safe_text("=SUM(1,2)").startswith("'")


@pytest.fixture
def registered(factory):
    account = "labels-" + uuid4().hex
    rows = [
        source_row(
            Arkistointitunnus=account + str(i),
            **{
                "Saaja/Maksaja": f"Synthetic merchant {i}",
                "Viesti": "Synthetic human review example",
                "Määrä EUROA": "12,34" if i == 0 else "-12,34",
            },
        )
        for i in range(4)
    ]
    assert (
        import_bank_bytes(
            source_bytes(rows),
            source_filename="synthetic.csv",
            account_key=account,
            session_factory=factory,
        ).rows_loaded
        == 4
    )
    raw, report = prepare_queue(factory, account, target=4)
    parsed = parse_reviews(raw)
    assert report["sample_size"] == 4
    return account, parsed, raw


def mark(row, category="FUEL", context="FORESTRY"):
    return {
        **row,
        "review_status": "REVIEWED",
        "reviewed_category": category,
        "reviewed_business_context": context,
        "review_notes": "Human synthetic decision",
    }


def test_queue_generation_repeats_and_privacy(factory, registered):
    account, rows, raw = registered
    second, _ = prepare_queue(factory, account, target=4)
    assert raw == second
    assert list(rows[0]) == QUEUE_COLUMNS
    assert all(r["reviewed_category"] == r["reviewed_business_context"] == "" for r in rows)
    assert all(r["review_status"] == "UNREVIEWED" for r in rows)
    assert not {"raw_source", "reference", "source_transaction_id", "bank_account", "BIC"} & set(
        rows[0]
    )
    with factory() as session:
        report = quality_report(session, account)
        assert report["total_unreviewed"] == 4 and report["total_reviewed"] == 0
        assert report["category_rule_agreement"]["rate"] is None
        assert ground_truth(session, account).height == 0


def test_human_labels_separate_and_rule_changes_preserve_them(factory, registered):
    account, rows, _ = registered
    labels = [mark(rows[0])]
    assert (
        import_reviews(encode_queue(labels), reviewer="synthetic-reviewer", factory=factory)[
            "reviewed_rows_inserted"
        ]
        == 1
    )
    with factory.begin() as session:
        tx = session.get(Transaction, UUID(rows[0]["transaction_id"]))
        assert tx.category == "unknown" and tx.business_context == BusinessContext.UNKNOWN
        tx.category = "tax"
        tx.business_context = BusinessContext.PROPERTY
    with factory() as session:
        review = session.scalar(
            select(TransactionLabelReview).where(
                TransactionLabelReview.transaction_id == UUID(rows[0]["transaction_id"])
            )
        )
        assert (
            review.confirmed_category == "FUEL" and review.confirmed_business_context == "FORESTRY"
        )
        assert review.suggested_category_snapshot == "UNKNOWN"
        assert review.reviewer == "synthetic-reviewer" and review.reviewed_at is not None
        assert len(review.review_file_sha256) == 64 and review.label_source == "human_csv_v1"
        data = ground_truth(session, account)
        assert data.height == 1 and data["confirmed_category"][0] == "FUEL"
        assert not any("suggest" in c or "snapshot" in c for c in data.columns)
        assert not {"raw_source", "source_transaction_id", "reference", "review_notes"} & set(
            data.columns
        )


def test_review_conflicts_and_atomic_rollback(factory, registered):
    account, rows, _ = registered
    original = mark(rows[0])
    import_reviews(encode_queue([original]), reviewer="human", factory=factory)
    assert (
        import_reviews(encode_queue([original]), reviewer="human", factory=factory)["unchanged"]
        == 1
    )
    with pytest.raises(ReviewError, match="existing_review_conflict"):
        import_reviews(
            encode_queue([mark(rows[1]), mark(rows[0], category="OTHER")]),
            reviewer="human",
            factory=factory,
        )
    with factory() as session:
        assert quality_report(session, account)["total_reviewed"] == 1
        assert ground_truth(session, account)["confirmed_category"][0] == "FUEL"


def test_unknown_transaction_rolls_back(factory, registered):
    account, rows, _ = registered
    missing = {**mark(rows[1]), "transaction_id": str(uuid4())}
    with pytest.raises(ReviewError, match="unknown_transaction_id"):
        import_reviews(encode_queue([mark(rows[0]), missing]), reviewer="human", factory=factory)
    with factory() as session:
        assert quality_report(session, account)["total_reviewed"] == 0


def test_ambiguous_unknown_and_aggregate_agreement(factory, registered):
    account, rows, _ = registered
    labels = [
        mark(rows[0], category="UNKNOWN", context="UNKNOWN"),
        mark(rows[1]),
        {**rows[2], "review_status": "SKIPPED_AMBIGUOUS", "review_notes": "No supporting receipt"},
        rows[3],
    ]
    result = import_reviews(encode_queue(labels), reviewer="human", factory=factory)
    assert result == {
        "reviewed_rows_inserted": 2,
        "ambiguous_skipped": 1,
        "unreviewed": 1,
        "unchanged": 0,
        "validation_failures": 0,
    }
    with factory() as session:
        report = quality_report(session, account)
        assert report["total_reviewed"] == 2 and report["total_ambiguous_skipped"] == 1
        assert report["category_counts"]["FUEL"] == report["category_counts"]["UNKNOWN"] == 1
        assert report["context_counts"]["FORESTRY"] == report["context_counts"]["UNKNOWN"] == 1
        assert report["category_rule_agreement"]["rate"] == 0.5
        assert report["context_rule_agreement"]["rate"] == 0.5
        assert report["unknown_confirmed_count"] == 1
        assert report["credits"] + report["debits"] == 2
        assert ground_truth(session, account).height == 2


@pytest.mark.parametrize(
    "field,value", [("amount", "999"), ("suggested_category", "TAX"), ("message", "changed")]
)
def test_read_only_field_edits_rejected(factory, registered, field, value):
    _, rows, _ = registered
    with pytest.raises(ReviewError):
        import_reviews(
            encode_queue([{**mark(rows[0]), field: value}]), reviewer="human", factory=factory
        )


def test_queue_file_never_overwritten(factory, registered, monkeypatch, tmp_path, capsys):
    from data_pipeline.labels import review_transactions

    account, _, _ = registered
    monkeypatch.setattr(review_transactions, "SessionLocal", factory)
    monkeypatch.setattr(review_transactions, "PRIVATE_ROOT", tmp_path)
    args = ["--account-key", account, "--size", "4"]
    assert review_transactions.main(args) == 0
    path = tmp_path / "review_queue.csv"
    original = path.read_bytes()
    assert review_transactions.main(args) == 1
    assert path.read_bytes() == original


def test_migration_up_down_up_in_disposable_schema(factory):
    # This fixture's URL points to a unique test-only schema, never the real bank tables.
    url = factory.kw["bind"].url
    assert "energy_test_" in url.query["options"]
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    for operation, target in [("downgrade", "0002"), ("upgrade", "head")]:
        subprocess.run(
            [".venv/bin/alembic", operation, target], env=env, check=True, capture_output=True
        )
    subprocess.run([".venv/bin/alembic", "check"], env=env, check=True, capture_output=True)


def test_agreement_counts_use_snapshots_and_coverage(monkeypatch):
    from types import SimpleNamespace

    from data_pipeline.labels import workflow

    pairs = []
    for amount, processor, category, context in [
        (Decimal("1"), "Paytrail Oyj", "TAX", "PROPERTY"),
        (Decimal("-1"), None, "OTHER", "UNKNOWN"),
    ]:
        transaction = SimpleNamespace(amount=amount, payment_intermediary=processor)
        review = SimpleNamespace(
            review_status="REVIEWED",
            confirmed_category=category,
            confirmed_business_context=context,
            suggested_category_snapshot="TAX",
            suggested_context_snapshot="UNKNOWN",
        )
        pairs.append((transaction, review))
    monkeypatch.setattr(workflow, "reviewed_pairs", lambda *_: pairs)
    report = workflow.quality_report(None, "synthetic")
    assert report["category_rule_agreement"]["non_unknown_suggestion_denominator"] == 2
    assert report["category_rule_agreement"]["non_unknown_suggestion_rate"] == 0.5
    assert report["context_rule_agreement"]["rate"] == 0.5
    assert report["context_rule_agreement"]["non_unknown_suggestion_rate"] is None
    assert report["paytrail_reviewed_count"] == 1
    assert report["credits"] == report["debits"] == 1


def test_ground_truth_redacts_embedded_identifiers(monkeypatch):
    from types import SimpleNamespace

    from apps.api.app.domain.enums import TransactionDirection
    from data_pipeline.labels import workflow

    tx = SimpleNamespace(
        id=UUID(int=1),
        booking_date=date(2026, 1, 1),
        amount=Decimal("-1"),
        direction=TransactionDirection.OUTGOING,
        normalized_counterparty="Synthetic merchant",
        ultimate_recipient=None,
        message="Private code SYNTHETIC-ARCHIVE and BANKFIHH and OTHERBIC",
        transaction_type_code="106",
        raw_source={"Arkistointitunnus": "SYNTHETIC-ARCHIVE", "Saajan pankin BIC": "BANKFIHH"},
    )
    review = SimpleNamespace(
        review_status="REVIEWED", confirmed_category="OTHER", confirmed_business_context="UNKNOWN"
    )
    monkeypatch.setattr(workflow, "reviewed_pairs", lambda *_: [(tx, review)])
    monkeypatch.setattr(workflow, "source_identifiers", lambda _: {"OTHERBIC"})
    data = workflow.ground_truth(None, "synthetic")
    assert "SYNTHETIC-ARCHIVE" not in data["message"][0]
    assert "BANKFIHH" not in data["message"][0]
    assert "OTHERBIC" not in data["message"][0]
