"""Synthetic imports in an Alembic-migrated disposable PostgreSQL schema."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.domain.enums import BusinessContext, ImportStatus, TaxReviewStatus
from apps.api.app.domain.models import ImportRun, TaxReview, Transaction
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_energy_load import factory as factory
from data_pipeline.load.bank import import_bank_bytes


@pytest.fixture
def account():
    return f"synthetic-{uuid4().hex}"


def bank_import(factory, account, rows=None, version="test-1"):
    rows = rows or [source_row()]
    rows = [{**r, "Arkistointitunnus": account + r["Arkistointitunnus"]} for r in rows]
    return import_bank_bytes(
        source_bytes(rows),
        source_filename="synthetic_bank.csv",
        account_key=account,
        session_factory=factory,
        parser_version=version,
    )


def count(factory, account):
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.source_namespace.endswith(":" + account))
        )


def test_file_idempotency_decimal_and_provenance(factory, account):
    first = bank_import(factory, account)
    second = bank_import(factory, account)
    assert (first.status, first.rows_parsed, first.rows_loaded) == ("imported", 1, 1)
    assert (second.status, second.rows_loaded, second.rows_skipped_duplicates) == (
        "already_imported",
        0,
        1,
    )
    assert count(factory, account) == 1
    with factory() as session:
        row = session.scalar(
            select(Transaction).where(Transaction.import_run_id == first.import_run_id)
        )
        assert row.amount == Decimal("-123.450000")
        assert row.reference == "000123" and row.transaction_type_code == "106"
        assert row.raw_source["Määrä EUROA"] == "-123,45"
        assert row.rule_metadata["label_kind"] == "weak_suggestion"
        run = session.get(ImportRun, first.import_run_id)
        assert run.sha256 == first.sha256 and run.row_count == 1
        assert run.source_metadata["rows_parsed"] == 1 and run.status == ImportStatus.COMPLETED
        assert session.get(ImportRun, second.import_run_id).source_metadata[
            "original_import_run_id"
        ] == str(run.id)


def test_overlap_skips_but_keeps_distinct_identical_payments(factory, account):
    a = source_row()
    b = source_row(Arkistointitunnus="SYNTHETIC-2")
    assert bank_import(factory, account, [a]).rows_loaded == 1
    result = bank_import(factory, account, [a, b])
    assert (result.rows_loaded, result.rows_skipped_duplicates) == (1, 1)
    assert count(factory, account) == 2


def test_changed_archive_identity_rolls_back_entire_import(factory, account):
    a = source_row()
    assert bank_import(factory, account, [a]).rows_loaded == 1
    b = source_row(Arkistointitunnus="SYNTHETIC-2")
    result = bank_import(factory, account, [b, source_row(Viesti="changed synthetic message")])
    assert result.status == "failed" and result.error_code == "archive_id_content_conflict"
    assert result.rows_loaded == 0 and count(factory, account) == 1
    with factory() as session:
        run = session.get(ImportRun, result.import_run_id)
        assert run.status == ImportStatus.FAILED and run.row_count == 0


def test_repeated_archive_within_file_is_counted(factory, account):
    result = bank_import(factory, account, [source_row(), source_row()])
    assert (result.rows_loaded, result.rows_skipped_duplicates) == (1, 1)


def test_bad_parser_failure_audited_and_retry_allowed(factory, account):
    result = bank_import(factory, account, [source_row(**{"Määrä EUROA": "malformed"})])
    assert result.status == "failed" and result.error_code == "malformed_amount"
    assert count(factory, account) == 0
    assert bank_import(factory, account).rows_loaded == 1


def test_concurrent_overlap_serialized(factory, account):
    a = source_row()
    b = source_row(Arkistointitunnus="SYNTHETIC-2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda rows: bank_import(factory, account, rows), [[a], [a, b]]))
    assert sum(r.rows_loaded for r in results) == 2
    assert count(factory, account) == 2 and all(r.status == "imported" for r in results)


def test_new_parser_and_overlap_never_overwrite_confirmed_review(factory, account):
    first = bank_import(factory, account)
    with factory.begin() as session:
        row = session.scalar(
            select(Transaction).where(Transaction.import_run_id == first.import_run_id)
        )
        row.business_context = BusinessContext.PERSONAL
        row.category = "human_category"
        review = TaxReview(
            transaction_id=row.id,
            confirmed_context=BusinessContext.PERSONAL,
            status=TaxReviewStatus.CONFIRMED_NON_BUSINESS,
            review_notes="Synthetic decision",
        )
        session.add(review)
        session.flush()
        review_id = review.id
    assert bank_import(factory, account, version="test-2").rows_skipped_duplicates == 1
    with factory() as session:
        review = session.get(TaxReview, review_id)
        assert review.status == TaxReviewStatus.CONFIRMED_NON_BUSINESS
        assert review.confirmed_context == BusinessContext.PERSONAL
        assert review.review_notes == "Synthetic decision"
        row = session.get(Transaction, review.transaction_id)
        assert row.category == "human_category" and row.business_context == BusinessContext.PERSONAL


def test_same_file_wrong_namespace_rejected(factory, account):
    raw = source_bytes([source_row(Arkistointitunnus=account)])
    kwargs = {"source_filename": "synthetic.csv", "session_factory": factory}
    assert import_bank_bytes(raw, account_key=account, **kwargs).status == "imported"
    result = import_bank_bytes(raw, account_key=account + "other", **kwargs)
    assert result.error_code == "fingerprint_account_mismatch"


def test_cli_sanitized_summary(factory, account, tmp_path, monkeypatch, capsys):
    import json

    from data_pipeline.ingest import bank

    monkeypatch.setattr(bank, "SessionLocal", factory)
    file = tmp_path / "synthetic_bank.csv"
    file.write_bytes(source_bytes([source_row(Arkistointitunnus=account)]))
    args = ["--file", str(file), "--account-key", account]
    assert bank.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["rows_loaded"] == 1 and "message" not in output and "reference" not in output
    assert bank.main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_imported"


def test_concurrent_same_file_different_alias_cannot_duplicate(factory, account):
    raw = source_bytes([source_row(Arkistointitunnus=account)])

    def load(alias):
        return import_bank_bytes(
            raw, source_filename="synthetic.csv", account_key=alias, session_factory=factory
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(load, [account, account + "other"]))
    assert sorted(r.status for r in results) == ["failed", "imported"]
    assert sum(r.rows_loaded for r in results) == 1
    assert [r.error_code for r in results if r.status == "failed"] == [
        "fingerprint_account_mismatch"
    ]
