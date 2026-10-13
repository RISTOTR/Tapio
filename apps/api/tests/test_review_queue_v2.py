"""Synthetic draft queue upgrades: preserve human edits without database writes."""

from decimal import Decimal
from uuid import UUID

import pytest

from apps.api.tests.test_transaction_labels import queue_row
from data_pipeline.labels.contracts import REVIEW_FIELDS, ReviewError, encode_queue, parse_reviews
from data_pipeline.labels.upgrade_review_queue import (
    EVIDENCE_STATUSES,
    V2_COLUMNS,
    amount_display,
    encode_v2,
    parse_v2,
    upgrade_rows,
)


def fixture_rows():
    rows = [
        queue_row(
            transaction_id=str(UUID(int=i + 1)),
            amount="-46.130000",
            booking_date="2026-01-01",
            direction="OUTGOING",
            normalized_counterparty="Synthetic merchant",
            suggested_category="UNKNOWN",
            suggested_business_context="UNKNOWN",
        )
        for i in range(100)
    ]
    for row in rows[:22]:
        row.update(
            reviewed_category="FUEL",
            reviewed_business_context="UNKNOWN",
            review_status="REVIEWED",
            review_notes='  Checked, with "evidence"\nSecond line  ',
        )
    return rows, {r["transaction_id"]: {**r, "currency": "EUR"} for r in rows}


def test_exact_edits_ids_order_and_determinism():
    rows, expected = fixture_rows()
    raw = encode_queue(rows)
    result, report = upgrade_rows(raw, expected)
    assert result == upgrade_rows(raw, dict(reversed(list(expected.items()))))[0]
    upgraded = parse_v2(result)
    assert [r["transaction_id"] for r in upgraded] == [r["transaction_id"] for r in rows]
    for before, after in zip(rows, upgraded, strict=True):
        assert all(before[k] == after[k] for k in before)
        assert all(before[k] == after[k] for k in REVIEW_FIELDS)
        assert after["evidence_status"] == "UNKNOWN"
        assert after["supporting_document_id"] == after["supporting_document_note"] == ""
    assert report["edited_rows_preserved"] == 22
    assert report["edited_cells_preserved"] == 88
    assert result.startswith(b"\xef\xbb\xbf")
    assert not {"raw_source", "reference", "bic", "archive_id", "account_number"} & set(V2_COLUMNS)


@pytest.mark.parametrize(
    ("machine", "display"),
    [
        ("-46.130000", "-46.13 EUR"),
        ("588.070000", "+588.07 EUR"),
        ("37712.500000", "+37,712.50 EUR"),
        ("-0.000001", "-0.000001 EUR"),
        ("1.123400", "+1.1234 EUR"),
        ("0.000000", "+0.00 EUR"),
    ],
)
def test_amount_exact(machine, display):
    assert amount_display(machine) == display
    assert Decimal(display.removesuffix(" EUR").replace(",", "")) == Decimal(machine)


@pytest.mark.parametrize("state", EVIDENCE_STATUSES)
def test_evidence_does_not_create_labels(state):
    rows, expected = fixture_rows()
    raw, _ = upgrade_rows(encode_queue(rows), expected)
    upgraded = parse_v2(raw)
    upgraded[22]["evidence_status"] = state
    parsed = parse_v2(encode_v2(upgraded))
    assert parsed[22]["review_status"] == "UNREVIEWED"
    assert parsed[22]["reviewed_category"] == parsed[22]["reviewed_business_context"] == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reviewed_category", ""),
        ("reviewed_business_context", ""),
        ("evidence_status", "BAD"),
        ("amount_display", "+46.13 EUR"),
        ("supporting_document_id", "not-a-uuid"),
    ],
)
def test_invalid_v2_rejected(field, value):
    rows, expected = fixture_rows()
    raw, _ = upgrade_rows(encode_queue(rows), expected)
    upgraded = parse_v2(raw)
    upgraded[0][field] = value
    with pytest.raises(ReviewError):
        parse_v2(encode_v2(upgraded))


@pytest.mark.parametrize("field", ["amount", "message", "transaction_id", "suggested_category"])
def test_source_mismatch_rejected(field):
    rows, expected = fixture_rows()
    rows[0][field] = str(UUID(int=500)) if field == "transaction_id" else "changed"
    with pytest.raises(ReviewError):
        upgrade_rows(encode_queue(rows), expected)


def test_unsafe_edits_fail_without_silently_rewriting():
    rows, expected = fixture_rows()
    for note in ('=HYPERLINK("bad")', "+SUM(1,2)", "BANKFIHH"):
        rows[0]["review_notes"] = note
        with pytest.raises(ReviewError, match="unsafe_text"):
            upgrade_rows(encode_queue(rows), expected, {"BANKFIHH"})
        assert rows[0]["review_notes"] == note
    rows[0]["review_notes"] = "'=formula escaped by reviewer"
    assert (
        parse_v2(upgrade_rows(encode_queue(rows), expected)[0])[0]["review_notes"]
        == rows[0]["review_notes"]
    )


def test_v2_cannot_be_silently_imported_by_v1():
    rows, expected = fixture_rows()
    with pytest.raises(ReviewError, match="invalid_review_columns"):
        parse_reviews(upgrade_rows(encode_queue(rows), expected)[0])


def test_numbers_semicolon_export_preserves_cells():
    import csv
    import io

    from data_pipeline.labels.contracts import QUEUE_COLUMNS
    from data_pipeline.labels.upgrade_review_queue import normalize_input

    rows, expected = fixture_rows()
    rows[0]["review_notes"] = 'Checked; note with comma, quote " and\nnewline'
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, QUEUE_COLUMNS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    normalized = normalize_input(stream.getvalue().encode("utf-8-sig"), ";")
    upgraded = parse_v2(upgrade_rows(normalized, expected)[0])
    assert upgraded[0]["review_notes"] == rows[0]["review_notes"]


def test_supporting_note_formula_rejected():
    rows, expected = fixture_rows()
    upgraded = parse_v2(upgrade_rows(encode_queue(rows), expected)[0])
    upgraded[0]["supporting_document_note"] = "=1+1"
    with pytest.raises(ReviewError, match="unsafe_text"):
        parse_v2(encode_v2(upgraded))


def test_noncanonical_user_drafts_preserved_but_not_validated_as_final_labels():
    rows, expected = fixture_rows()
    rows[0]["reviewed_category"] = "OTHER/FORESTRY"
    rows[0]["reviewed_business_context"] = "PERSONAL/FORESTRY"
    raw, report = upgrade_rows(encode_queue(rows), expected)
    preserved = parse_v2(raw, strict_labels=False)
    assert preserved[0]["reviewed_category"] == "OTHER/FORESTRY"
    assert preserved[0]["reviewed_business_context"] == "PERSONAL/FORESTRY"
    assert report["label_validation_issue_lines"] == [2]
    with pytest.raises(ReviewError, match="invalid_category"):
        parse_v2(raw)


def test_optional_group_preserves_legacy_and_escapes_formulas():
    import csv
    import io

    rows, expected = fixture_rows()
    upgraded = parse_v2(upgrade_rows(encode_queue(rows), expected)[0])
    assert upgraded[0]["review_group"] == ""
    upgraded[0]["review_group"] = "trip-2026-01"
    upgraded[0]["reviewed_category"] = "TRAVEL"
    assert parse_v2(encode_v2(upgraded))[0]["review_group"] == "trip-2026-01"
    old_columns = [k for k in V2_COLUMNS if k != "review_group"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, old_columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(upgraded)
    assert parse_v2(stream.getvalue().encode())[0]["review_group"] == ""
    upgraded[0]["review_group"] = '=HYPERLINK("bad")'
    with pytest.raises(ReviewError, match="unsafe_text"):
        parse_v2(encode_v2(upgraded))
