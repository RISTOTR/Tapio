"""Validate an immutable historical subset without mistaking appends for mutation."""

from data_pipeline.labels.snapshot import fingerprint


def indexed(rows):
    result = {}
    for row in rows:
        key = str(row["id"])
        if key in result:
            raise ValueError("DUPLICATE_SOURCE_IDENTITY")
        result[key] = row
    return result


def verify_historical_sources(current, historical, expected):
    """Authenticate archived rows before using their IDs; compare ALL live fields.

    ``expected`` is the existing accepted snapshot's count + SHA-256 per table.
    No live row is ever used to establish or update that historical baseline.
    Appended rows remain subject to the normal importer/database constraints.
    """
    if set(current) != set(expected):
        raise ValueError("SOURCE_TABLE_SCOPE_CHANGED")
    for name, protected_hash in expected.items():
        old_rows = historical[name]
        if fingerprint(old_rows) != protected_hash:
            raise ValueError("HISTORICAL_ARCHIVE_NOT_AUTHENTICATED")
        old = indexed(old_rows)
        live = indexed(current[name])
        if not old.keys() <= live.keys():
            raise ValueError("HISTORICAL_SOURCE_DELETED")
        if fingerprint([live[key] for key in old]) != protected_hash:
            raise ValueError("HISTORICAL_SOURCE_CHANGED")
        if name == "transactions":
            # Also reject an appended identity collision, even before DB constraints.
            identities = set()
            for row in live.values():
                identity = (row.get("source_namespace"), row.get("source_transaction_id"))
                if None in identity:
                    continue  # Legacy rows predate source-identity normalization.
                if identity in identities:
                    raise ValueError("DUPLICATE_BANK_SOURCE_IDENTITY")
                identities.add(identity)
