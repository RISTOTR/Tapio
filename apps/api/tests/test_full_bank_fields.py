"""Full source-schema contract and independent message provenance, synthetic only."""

import pytest

from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_suggestion_cards import NOW, generator, review, tx
from data_pipeline.ingest.bank_csv import HEADERS, BankInputError, parse_bank_csv
from data_pipeline.ingest.bank_fields import BANK_FIELDS, audit_columns
from data_pipeline.normalize.bank import canonical_bank
from tapio.knowledge.backfill import accrue
from tapio.knowledge.bank_evidence import document_candidates, purpose_evidence
from tapio.knowledge.fields import field_provenance, source_text_fields
from tapio.knowledge.store import rebuild
from tapio.pilot.transaction_search import matching_terms
from tapio.suggestions.full_fields import FullFieldGenerator

EXPECTED = [
    "Kirjauspäivä",
    "Arvopäivä",
    "Määrä EUROA",
    "Laji",
    "Selitys",
    "Saaja/Maksaja",
    "Saajan tilinumero",
    "Saajan pankin BIC",
    "Viite",
    "Viesti",
    "Arkistointitunnus",
]


def test_full_schema_lossless_and_classified():
    assert HEADERS == EXPECTED == list(BANK_FIELDS)
    row = source_row(Viesti="Synthetic pharmacy invoice", Selitys="Card debit")
    parsed = parse_bank_csv(source_bytes([row])).to_dicts()[0]
    assert parsed == row
    assert all(s.classification and s.meaning and s.stored for s in BANK_FIELDS.values())
    canonical = canonical_bank(source_bytes([row]), "synthetic.csv").to_dicts()[0]
    assert canonical["message"] == "Synthetic pharmacy invoice"
    import json

    assert json.loads(canonical["raw_source"])["Viesti"] == row["Viesti"]
    assert json.loads(canonical["raw_source"])["Selitys"] == row["Selitys"]


def test_new_unknown_column_never_silently_dropped():
    assert audit_columns([*EXPECTED, "New field"])["unknown"] == ["New field"]
    raw = source_bytes([source_row()]).decode("utf-8-sig")
    lines = raw.splitlines()
    changed = (lines[0] + ";New field\n" + lines[1] + ";extra\n").encode()
    with pytest.raises(BankInputError, match="unsupported_bank_headers"):
        parse_bank_csv(changed)


def test_viesti_selitys_search_provenance_and_no_account_index():
    t = tx(1)
    t["raw_source"] = {
        "Viesti": "Farmacia invoice",
        "Selitys": "Card purchase",
        "Saajan tilinumero": "PRIVATE_ACCOUNT",
        "Viite": "ref=123456",
    }
    fields = source_text_fields(t)
    assert matching_terms(fields, ["farmacia"])[0]["fields"] == ["raw_source.Viesti"]
    assert matching_terms(fields, ["purchase"])[0]["fields"] == ["raw_source.Selitys"]
    assert not matching_terms(fields, ["PRIVATE_ACCOUNT"])
    assert field_provenance("raw_description")["source_field"] == "raw_source.Viesti"
    s = rebuild(accrue({"transactions": [t]}, observed_at=NOW))
    assert any(
        i.claim.predicate == "observed_source_text"
        and i.claim.value["field"] == "raw_source.Viesti"
        for i in s.items
    )
    assert all(i.claim.authority != "HUMAN_CONFIRMED" for i in s.items)


def test_recipient_scoped_paytrail_category_not_processor_rule():
    rows = [
        tx(1, "Paytrail Oyj"),
        tx(2, "Paytrail Oyj"),
        tx(3, "Paytrail Oyj"),
        tx(4, "Paytrail Oyj"),
    ]
    for t, recipient in zip(rows, ["Shop A", "Shop A", "Shop B", "Unknown shop"], strict=True):
        t["raw_counterparty"] = "Paytrail Oyj"
        t["raw_source"] = {"Viesti": "Lopullinen saaja: " + recipient}
    reviews = [review(1, "FUEL", "PERSONAL"), review(3, "OTHER", "PROPERTY")]
    g = generator(rows, reviews)
    v2 = FullFieldGenerator(g.snapshot, rows, reviews, NOW)
    c = v2.card(rows[1], v2.signals(rows[1]))
    assert c.suggestion.category == "FUEL" and c.suggestion.context is None
    assert c.suggestion.authority == "SUGGESTED" and c.rule_version == "FULL_CSV_CARDS_V2"
    assert "SOURCE_MESSAGE_MATCH" in {r.code for r in c.reasons}
    opaque = v2.card(rows[3], v2.signals(rows[3]))
    assert opaque.suggestion.category is None and opaque.suggestion.context is None


def test_recipient_is_not_purchase_purpose_and_candidate_is_not_confirmation():
    t = tx(1, "Paytrail Oyj")
    t["raw_source"] = {"Viesti": "Lopullinen saaja: Example Oy"}
    assert purpose_evidence(t)["classification"] == "STILL_OPAQUE"
    t["raw_source"]["Viesti"] = "Lopullinen saaja: Example / Prepaid"
    assert purpose_evidence(t)["classification"] == "PURPOSE_VISIBLE_IN_BANK_SOURCE"
    invoices = [
        {
            "id": str(i),
            "vendor": "Example",
            "invoice_date": "2025-01-01",
            "total_eur": "588.07",
            "invoice_number": "ABC123",
        }
        for i in (1, 2)
    ]
    t["raw_source"]["Viesti"] = "Example invoice ABC123"
    links = document_candidates(t, invoices)
    assert {link["status"] for link in links} == {"AMBIGUOUS"}
    assert not document_candidates(tx(5, "Unrelated"), invoices)
