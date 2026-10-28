"""Central source-field registry. Discovery records unknown fields but cannot activate them."""

from data_pipeline.ingest.bank_fields import BANK_FIELDS

SOURCE_FIELDS = {
    "raw_description": ("message", "Imported bank message"),
    "raw_merchant": ("raw_counterparty", "Imported counterparty text"),
    "normalized_merchant": ("normalized_counterparty", "Canonicalized merchant text"),
    "recipient": ("ultimate_recipient", "Imported recipient"),
    "processor": ("payment_intermediary", "Imported processor"),
}
SOURCE_FIELDS.update(
    {
        "raw_source." + name: ("raw_source." + name, spec.meaning)
        for name, spec in BANK_FIELDS.items()
        if spec.searchable
    }
)
IDENTITY_PATHS = ("normalized_counterparty", "ultimate_recipient", "payment_intermediary")


def source_text_fields(tx):
    result = {}
    for name, (path, _) in SOURCE_FIELDS.items():
        if path.startswith("raw_source."):
            raw = tx.get("raw_source") if isinstance(tx, dict) else tx.raw_source
            value = raw.get(path.split(".", 1)[1]) if isinstance(raw, dict) else None
        else:
            value = tx.get(path) if isinstance(tx, dict) else getattr(tx, path, None)
        result[name] = value if isinstance(value, str) else None
    return result


def field_provenance(name):
    path = SOURCE_FIELDS.get(name, (name, ""))[0]
    original = {
        "message": "raw_source.Viesti",
        "raw_counterparty": "raw_source.Saaja/Maksaja",
        "normalized_counterparty": "raw_source.Saaja/Maksaja",
    }.get(path, path)
    return {
        "matched_field": path,
        "source_field": original,
        "value_representation": "NORMALIZED" if path == "normalized_counterparty" else "RAW",
        "matching_normalization": "NFKD_CASEFOLD_ALNUM_TOKEN_PHRASE_V1",
    }
