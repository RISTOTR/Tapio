"""Complete inspected CSV field contract; no implicit activation of unknown columns."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BankField:
    classification: str
    stored: str
    meaning: str
    searchable: bool = False
    vocabulary: bool = False
    reconciliation: str = "Not a matching key"
    exclusion: str = ""


BANK_FIELDS = {
    "Kirjauspäivä": BankField(
        "AMOUNT_DATE_FIELD",
        "booking_date",
        "Bank booking date",
        reconciliation="Date-window candidate evidence",
    ),
    "Arvopäivä": BankField(
        "AMOUNT_DATE_FIELD",
        "value_date",
        "Bank value date",
        reconciliation="Available as supplemental date evidence",
    ),
    "Määrä EUROA": BankField(
        "AMOUNT_DATE_FIELD",
        "amount/currency/direction",
        "Signed euro amount",
        reconciliation="Exact Decimal amount",
    ),
    "Laji": BankField(
        "CORE_STRUCTURED_FIELD",
        "transaction_type_code",
        "Bank transaction type code; no undocumented purpose mapping",
        exclusion="No generic text search: opaque code",
    ),
    "Selitys": BankField(
        "SEARCHABLE_SOURCE_TEXT",
        "raw_source.Selitys",
        "Bank transaction description",
        True,
        True,
        "Supplemental candidate text, never automatic confirmation",
    ),
    "Saaja/Maksaja": BankField(
        "IDENTITY_FIELD",
        "raw_counterparty/normalized_counterparty",
        "Payee or payer identity",
        True,
        True,
        "Exact known vendor identity",
    ),
    "Saajan tilinumero": BankField(
        "IDENTITY_FIELD",
        "raw_source.Saajan tilinumero",
        "Recipient bank account",
        exclusion="Sensitive account identifier: retained, not generic search/vocabulary",
    ),
    "Saajan pankin BIC": BankField(
        "IDENTITY_FIELD",
        "raw_source.Saajan pankin BIC",
        "Recipient bank identifier",
        exclusion="Bank identity does not establish purchase purpose; no generic search",
    ),
    "Viite": BankField(
        "REFERENCE_FIELD",
        "reference",
        "Payment reference; raw ref= prefix preserved",
        True,
        False,
        "Exact normalized reference; candidate evidence",
    ),
    "Viesti": BankField(
        "SEARCHABLE_SOURCE_TEXT",
        "message",
        "Transaction message / supplemental payment information",
        True,
        True,
        "Explicit message/reference tokens; candidate evidence only",
    ),
    "Arkistointitunnus": BankField(
        "METADATA_ONLY",
        "source_transaction_id",
        "Stable archive identity / import deduplication",
        exclusion="Private stable identifier: no generic search/vocabulary",
    ),
}


def audit_columns(columns):
    return {
        "known": [c for c in columns if c in BANK_FIELDS],
        "unknown": [c for c in columns if c not in BANK_FIELDS],
        "missing": [c for c in BANK_FIELDS if c not in columns],
        "exact_order": list(columns) == list(BANK_FIELDS),
    }
