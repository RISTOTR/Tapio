"""Central source-field registry. Discovery records unknown fields but cannot activate them."""

SOURCE_FIELDS = {
    "raw_description": ("message", "Imported bank message"),
    "raw_source.Selitys": ("raw_source.Selitys", "Imported Finnish bank transaction description"),
    "raw_merchant": ("raw_counterparty", "Imported counterparty text"),
    "normalized_merchant": ("normalized_counterparty", "Canonicalized merchant text"),
    "recipient": ("ultimate_recipient", "Imported recipient"),
    "processor": ("payment_intermediary", "Imported processor"),
}


def source_text_fields(tx):
    result = {}
    for name, (path, _) in SOURCE_FIELDS.items():
        if path.startswith("raw_source."):
            raw = tx.raw_source
            value = raw.get(path.split(".", 1)[1]) if isinstance(raw, dict) else None
        else:
            value = getattr(tx, path)
        result[name] = value if isinstance(value, str) else None
    return result
