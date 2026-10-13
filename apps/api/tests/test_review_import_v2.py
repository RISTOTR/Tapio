"""Human v2 import preserves original bytes and decisions without evidence inference."""

import csv
import io
from hashlib import sha256
from uuid import UUID

import pytest

from apps.api.app.domain.models import TransactionLabelReview
from apps.api.tests.test_energy_load import factory as factory
from apps.api.tests.test_transaction_labels import registered as registered
from data_pipeline.labels.contracts import ReviewError
from data_pipeline.labels.review_input import parse_import
from data_pipeline.labels.upgrade_review_queue import V2_COLUMNS, amount_display
from data_pipeline.labels.workflow import ground_truth, import_reviews


def v2_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, V2_COLUMNS, delimiter=";", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(
        [
            {
                **r,
                "amount_display": amount_display(r["amount"]),
                "evidence_status": "UNKNOWN",
                "supporting_document_id": "",
                "supporting_document_note": "Receipt checked elsewhere",
                "review_group": "synthetic-group",
            }
            for r in rows
        ]
    )
    return stream.getvalue().encode("utf-8-sig")


def test_v2_authoritative_labels_notes_hash_and_retry(factory, registered):
    account, rows, _ = registered
    rows[0].update(
        review_status="REVIEWED",
        reviewed_category="OTHER",
        reviewed_business_context="PERSONAL",
        review_notes="  Human broad label\nkept exactly  ",
    )
    rows[1].update(review_status="SKIPPED_AMBIGUOUS", review_notes="Known mixed allocation")
    raw = v2_bytes(rows)
    result = import_reviews(raw, reviewer="synthetic", factory=factory)
    assert result["reviewed_rows_inserted"] == result["ambiguous_skipped"] == 1
    assert result["unreviewed"] == 2
    with factory() as session:
        review = (
            session.query(TransactionLabelReview)
            .filter_by(transaction_id=UUID(rows[0]["transaction_id"]))
            .one()
        )
        assert review.review_notes == rows[0]["review_notes"]
        assert review.confirmed_category == "OTHER"
        assert review.confirmed_business_context == "PERSONAL"
        assert review.review_file_sha256 == sha256(raw).hexdigest()
        assert review.label_source == "human_csv_v2"
        assert review.taxonomy_version == "2"
        timestamp = review.reviewed_at
        assert ground_truth(session, account).height == 1
    assert import_reviews(raw, reviewer="synthetic", factory=factory)["unchanged"] == 2
    with factory() as session:
        assert (
            session.query(TransactionLabelReview)
            .filter_by(transaction_id=UUID(rows[0]["transaction_id"]))
            .one()
            .reviewed_at
            == timestamp
        )


def test_invalid_v2_does_not_bypass_label_validation(registered):
    _, rows, _ = registered
    rows[0].update(
        review_status="REVIEWED",
        reviewed_category="NOT_A_CATEGORY",
        reviewed_business_context="PERSONAL",
    )
    with pytest.raises(ReviewError, match="invalid_category"):
        parse_import(v2_bytes(rows))


def test_cli_archives_exact_evidence_bytes(monkeypatch, tmp_path, registered):
    from data_pipeline.labels import import_transaction_reviews as cli

    _, rows, _ = registered
    raw = v2_bytes(rows)
    path = tmp_path / "input.csv"
    path.write_bytes(raw)
    monkeypatch.setattr(cli, "PRIVATE_ROOT", tmp_path)
    monkeypatch.setattr(
        cli,
        "import_reviews",
        lambda received, **kwargs: (
            {"unchanged": 0} if received == raw else pytest.fail("changed bytes")
        ),
    )
    assert cli.main(["--file", str(path), "--reviewer", "synthetic"]) == 0
    assert (tmp_path / "review_imports" / f"{sha256(raw).hexdigest()}.csv").read_bytes() == raw
    assert path.read_bytes() == raw
