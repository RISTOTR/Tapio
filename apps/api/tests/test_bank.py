"""Synthetic source fixtures only; no household rows, references or account numbers."""

import csv
import io
from datetime import date
from decimal import Decimal

import pandera as pa
import polars as pl
import pytest

from data_pipeline.ingest.bank_csv import HEADERS, BankInputError, parse_bank_csv
from data_pipeline.normalize.bank import canonical_bank, counterparty_fields, normalize_name
from data_pipeline.normalize.bank_analysis import (
    classification_features,
    duplicate_payment_candidates,
    recurring_candidates,
    reversal_candidates,
)
from data_pipeline.validate.bank import bank_enriched_schema


def source_row(**overrides):
    row = dict.fromkeys(HEADERS, "")
    row.update(
        {
            "Kirjauspäivä": "2025-01-15",
            "Arvopäivä": "2025-01-16",
            "Määrä EUROA": "-123,45",
            "Laji": "106",
            "Selitys": "synthetic payment",
            "Saaja/Maksaja": "Vattenfall Oy",
            "Viite": "000123",
            "Arkistointitunnus": "SYNTHETIC-1",
        }
    )
    row.update(overrides)
    return row


def source_bytes(rows=None):
    out = io.StringIO()
    writer = csv.DictWriter(out, HEADERS, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows if rows is not None else [source_row()])
    return out.getvalue().encode("utf-8-sig")


def test_parse_preserves_raw_strings_and_quotes():
    raw = source_bytes([source_row(Viesti='synthetic; "quoted" message')])
    parsed = parse_bank_csv(raw)
    assert parsed.schema == dict.fromkeys(HEADERS, pl.String)
    assert parsed["Viite"][0] == "000123"
    assert parsed["Viesti"][0] == 'synthetic; "quoted" message'
    assert parsed["Määrä EUROA"][0] == "-123,45"


def test_canonical_exact_dates_money_and_nulls():
    frame = canonical_bank(source_bytes(), "synthetic.csv")
    row = frame.row(0, named=True)
    assert frame.schema["amount"] == pl.Decimal(20, 6)
    assert row["amount"] == Decimal("-123.45")
    assert row["booking_date"] == date(2025, 1, 15)
    assert row["value_date"] == date(2025, 1, 16)
    assert row["message"] is None
    assert row["direction"] == "outgoing" and row["currency"] == "EUR"
    assert row["transaction_type_code"] == "106"
    bank_enriched_schema.validate(frame)


@pytest.mark.parametrize(
    "amount,direction", [("+12,34", "incoming"), ("12,34", "incoming"), ("-12,34", "outgoing")]
)
def test_sign_direction(amount, direction):
    frame = canonical_bank(source_bytes([source_row(**{"Määrä EUROA": amount})]), "synthetic.csv")
    assert frame["direction"][0] == direction


@pytest.mark.parametrize(
    "value", ["NaN", "1.23", "1,234", "1 000,00", "--1,00", "", "0,00", "100000000000000,00"]
)
def test_invalid_amount_rejected(value):
    with pytest.raises(BankInputError):
        canonical_bank(source_bytes([source_row(**{"Määrä EUROA": value})]), "synthetic.csv")


@pytest.mark.parametrize("value", ["2025-02-30", "15.01.2025", "2025-1-01", ""])
def test_invalid_date_rejected(value):
    with pytest.raises(BankInputError):
        canonical_bank(source_bytes([source_row(**{"Kirjauspäivä": value})]), "synthetic.csv")


@pytest.mark.parametrize("raw", [b"wrong;header\n1;2", b"\xffinvalid"])
def test_invalid_source_rejected(raw):
    with pytest.raises(BankInputError):
        parse_bank_csv(raw)


def test_optional_values_and_required_archive_id():
    row = source_row(**{"Arvopäivä": "", "Saaja/Maksaja": "", "Viite": "", "Laji": ""})
    result = canonical_bank(source_bytes([row]), "synthetic.csv").row(0, named=True)
    for name in ["value_date", "raw_counterparty", "reference", "transaction_type_code"]:
        assert result[name] is None
    row["Arkistointitunnus"] = ""
    with pytest.raises(BankInputError, match="archive_id"):
        canonical_bank(source_bytes([row]), "synthetic.csv")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  vATTENfall   Oy. ", "Vattenfall Oy"),
        ("Elenia Verkko Oy", "Elenia Verkko Oyj"),
        ("Metsänhoitoyhdistys Keski-Suomi ry", "Metsänhoitoyhdistys Keski-Suomi"),
        ("STORA ENSO OYJ", "Stora Enso Oyj"),
        ("VEROHALLINTO", "Verohallinto"),
    ],
)
def test_aliases(raw, expected):
    assert normalize_name(raw) == expected


def test_direct_merchant_has_no_invented_recipient():
    assert counterparty_fields("Vattenfall Oy", None) == {
        "normalized_counterparty": "Vattenfall Oy",
        "payment_intermediary": None,
        "ultimate_recipient": None,
    }


def test_paytrail_explicit_recipient_only():
    result = counterparty_fields(
        "Paytrail Oyj Synthetic Store", "Lopullinen saaja: Synthetic Store Oy"
    )
    assert result["payment_intermediary"] == "Paytrail Oyj"
    assert result["normalized_counterparty"] == "Paytrail Oyj"
    assert result["ultimate_recipient"] == "synthetic store oy"


@pytest.mark.parametrize(
    "message",
    [
        None,
        "merchant might be Example",
        "Lopullinen saaja:",
        "Lopullinen saaja: Example; account: 123",
        "Lopullinen saaja: A Lopullinen saaja: B",
        "Lopullinen saaja: 12345",
        "Lopullinen saaja: Example\nextra field",
    ],
)
def test_unreliable_recipient_null(message):
    assert counterparty_fields("PAYTRAIL OYJ", message)["ultimate_recipient"] is None


@pytest.mark.parametrize(
    "merchant,amount,category,context",
    [
        ("Vattenfall Oy", "-1,00", "electricity", "property"),
        ("Elenia Verkko Oy", "-1,00", "grid_distribution", "property"),
        ("Metsänhoitoyhdistys Keski-Suomi ry", "-1,00", "forestry_service", "forestry"),
        ("STORA ENSO OYJ", "1,00", "timber_income", "forestry"),
        ("STORA ENSO OYJ", "-1,00", "unknown", "forestry"),
        ("Verohallinto", "-1,00", "tax", "unknown"),
        ("Synthetic Fuel Store", "-1,00", "unknown", "unknown"),
    ],
)
def test_independent_category_and_context_rules(merchant, amount, category, context):
    frame = canonical_bank(
        source_bytes([source_row(**{"Saaja/Maksaja": merchant, "Määrä EUROA": amount})]),
        "synthetic.csv",
    )
    assert frame["category"][0] == category and frame["business_context"][0] == context
    assert "weak_suggestion" in frame["rule_metadata"][0]


def analytical_frame(dates, amounts=None):
    rows = [
        source_row(
            **{
                "Kirjauspäivä": d,
                "Määrä EUROA": (amounts[i] if amounts else "-20,00"),
                "Arkistointitunnus": f"SYNTHETIC-{i}",
            }
        )
        for i, d in enumerate(dates)
    ]
    return canonical_bank(source_bytes(rows), "synthetic.csv")


def test_monthly_pattern_and_variance():
    frame = analytical_frame(
        ["2025-01-15", "2025-02-17", "2025-03-14"], ["-20,00", "-30,00", "-40,00"]
    )
    result = recurring_candidates(frame)
    assert len(result) == 1 and result[0]["count"] == 3
    assert result[0]["mean_amount"] == Decimal("30") and result[0]["amount_variance"] > 0


@pytest.mark.parametrize(
    "dates",
    [
        ["2025-01-01", "2025-01-04", "2025-01-20"],
        ["2025-01-15", "2025-03-15", "2025-04-15"],
        ["2025-01-15", "2025-02-15"],
    ],
)
def test_repeated_not_monthly(dates):
    assert recurring_candidates(analytical_frame(dates)) == []


def test_refund_candidates_multiple_debits_never_confirmed():
    frame = analytical_frame(
        ["2025-01-15", "2025-01-16", "2025-01-20"], ["-20,00", "-20,00", "20,00"]
    )
    result = reversal_candidates(frame)
    assert len(result) == 2 and all(r["matching_debit_count"] == 2 for r in result)
    assert all(r["status"] == "refund_or_reversal_candidate" for r in result)
    assert len(duplicate_payment_candidates(frame)) == 1
    assert reversal_candidates(frame, max_days=2) == []


def test_refund_different_currency_or_unknown_intermediary_not_paired():
    frame = analytical_frame(["2025-01-15", "2025-01-20"], ["-20,00", "20,00"])
    mixed = frame.with_columns(pl.Series("currency", ["EUR", "USD"]))
    assert reversal_candidates(mixed) == []
    unresolved = frame.with_columns(pl.lit("Paytrail Oyj").alias("payment_intermediary"))
    assert reversal_candidates(unresolved) == []


def test_features_mark_labels_weak():
    frame = classification_features(canonical_bank(source_bytes(), "synthetic.csv"))
    assert frame["month"][0] == 1 and frame["day_of_week"][0] == 2
    assert frame["suggested_category"][0] == "electricity"
    assert frame["label_provenance"][0] == "deterministic_weak_label_not_ground_truth"
    assert "raw_source" not in frame.columns and "source_transaction_id" not in frame.columns


@pytest.mark.parametrize(
    "column,value", [("currency", ""), ("direction", "debit"), ("source_file", "")]
)
def test_contract_rejects_invalid_required_values(column, value):
    frame = canonical_bank(source_bytes(), "synthetic.csv").with_columns(
        pl.lit(value).alias(column)
    )
    with pytest.raises(pa.errors.SchemaError):
        bank_enriched_schema.validate(frame)


def test_role_and_aggregate_groundwork():
    from data_pipeline.verify_bank import aggregate_checks

    rows = [
        source_row(**{"Saaja/Maksaja": "STORA ENSO OYJ", "Määrä EUROA": "500,00"}),
        source_row(
            **{
                "Saaja/Maksaja": "Metsänhoitoyhdistys Keski-Suomi ry",
                "Määrä EUROA": "-80,00",
                "Arkistointitunnus": "SYNTHETIC-2",
            }
        ),
        source_row(**{"Saaja/Maksaja": "Verohallinto", "Arkistointitunnus": "SYNTHETIC-3"}),
        source_row(Arkistointitunnus="SYNTHETIC-4"),
    ]
    frame = canonical_bank(source_bytes(rows), "synthetic.csv")
    roles = classification_features(frame)["suggested_transaction_role"].to_list()
    assert roles == ["income", "expense", "tax", "expense"]
    summary = aggregate_checks(frame)
    assert summary["forestry_suggestions"]["count"] == 2
    assert summary["forestry_suggestions"]["total_credits_eur"] == Decimal("500")
    assert summary["forestry_suggestions"]["total_debits_eur"] == Decimal("80")
    assert summary["unassigned_business_context_count"] == 1
    assert summary["property_energy"][0]["total_debits_eur"] == Decimal("123.45")


def test_reference_wrapper_and_empty_placeholder():
    rows = [
        source_row(Viite="ref="),
        source_row(Viite="ref=000123", Arkistointitunnus="SYNTHETIC-2"),
    ]
    frame = canonical_bank(source_bytes(rows), "synthetic.csv")
    assert frame["reference"].to_list() == [None, "000123"]
    assert "ref=" in frame["raw_source"][0]
    assert duplicate_payment_candidates(frame) == []


def test_recurring_run_can_follow_irregular_payment():
    frame = analytical_frame(["2025-01-01", "2025-01-15", "2025-02-17", "2025-03-14"])
    result = recurring_candidates(frame)
    assert len(result) == 1 and result[0]["count"] == 3
    assert result[0]["first_date"] == date(2025, 1, 15)


def test_delayed_refund_candidate_and_duplicate_within_month():
    frame = analytical_frame(
        ["2025-01-02", "2025-01-15", "2025-07-16"], ["-20,00", "-20,00", "20,00"]
    )
    assert len(reversal_candidates(frame)) == 2
    assert len(duplicate_payment_candidates(frame)) == 1


def test_duplicate_candidate_identity_and_account_scope():
    frame = analytical_frame(["2025-01-15", "2025-01-16"])
    scoped = frame.with_columns(pl.Series("source_namespace", ["synthetic:a", "synthetic:b"]))
    assert duplicate_payment_candidates(scoped) == []
    scoped = frame.with_columns(pl.lit("synthetic:a").alias("source_namespace"))
    assert duplicate_payment_candidates(scoped)[0]["source_namespace"] == "synthetic:a"
    repeated_id = frame.with_columns(pl.lit("SYNTHETIC-1").alias("source_transaction_id"))
    assert duplicate_payment_candidates(repeated_id) == []
