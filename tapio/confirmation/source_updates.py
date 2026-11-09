"""Accept a proven append-only bank import without rewriting historical pilot snapshots."""

import hashlib
import hmac
import json
from decimal import Decimal

from data_pipeline.ingest.bank_csv import SOURCE_TYPE
from data_pipeline.labels.snapshot import fingerprint
from data_pipeline.normalize.bank import canonical_bank
from integrations.gmail.cache import private_write
from tapio.knowledge.models import digest


def accepted_fingerprints(queue, original):
    path = queue.root / "ongoing_sources.json"
    if not path.exists():
        return original
    envelope = json.loads(path.read_text())
    data = envelope["data"]
    signature = hmac.new(
        (queue.root / "queue.key").read_bytes(), digest(data).encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, envelope["signature"]):
        raise ValueError("ONGOING_SOURCE_INTEGRITY")
    if (
        data["version"] != "VERIFIED_BANK_APPEND_V1"
        or data["source_fingerprints"] != queue.manifest()["source_fingerprints"]
    ):
        raise ValueError("ONGOING_SOURCE_MANIFEST_MISMATCH")
    return data["source_fingerprints"]


def accept_bank_import(queue, before, after, result, raw):
    """Called only after an authorized production import; creates no labels or windows."""
    manifest = queue.manifest()
    source_names = manifest["source_fingerprints"]
    if {n: fingerprint(before[n]) for n in source_names} != source_names:
        raise ValueError("UNVERIFIED_IMPORT_BASELINE")
    if result.status != "imported" or hashlib.sha256(raw).hexdigest() != result.sha256:
        raise ValueError("BANK_IMPORT_NOT_VERIFIED")
    if set(before) != set(after):
        raise ValueError("SOURCE_TABLE_SET_CHANGED")
    added = {}
    for name in before:
        old = {r["id"]: r for r in before[name]}
        current = {r["id"]: r for r in after[name]}
        if any(current.get(i) != row for i, row in old.items()):
            raise ValueError("HISTORICAL_SOURCE_CHANGED")
        added[name] = [row for i, row in current.items() if i not in old]
        if added[name] and name not in {"transactions", "import_runs"}:
            raise ValueError("UNEXPECTED_IMPORT_MUTATION")
    runs = added["import_runs"]
    if len(runs) != 1 or runs[0]["id"] != str(result.import_run_id):
        raise ValueError("UNEXPECTED_IMPORT_RUN")
    run = runs[0]
    if (
        run["source_type"] != SOURCE_TYPE
        or run["status"] != "completed"
        or run["sha256"] != result.sha256
        or run["source_filename"] != result.source_file
        or run["source_metadata"].get("outcome") != "imported"
        or run["row_count"] != result.rows_loaded
    ):
        raise ValueError("BANK_IMPORT_PROVENANCE_MISMATCH")
    frame = canonical_bank(raw, result.source_file)
    rows = {r["source_transaction_id"]: r for r in frame.iter_rows(named=True)}
    new = added["transactions"]
    if len(new) != result.rows_loaded or frame.height != result.rows_parsed:
        raise ValueError("BANK_IMPORT_COUNT_MISMATCH")
    namespace = run["source_metadata"]["source_namespace"]
    for tx in new:
        expected = rows.get(tx["source_transaction_id"])
        if not expected or tx["import_run_id"] != run["id"] or tx["source_namespace"] != namespace:
            raise ValueError("BANK_TRANSACTION_PROVENANCE_MISMATCH")
        for field, value in expected.items():
            actual = tx[field]
            if field in {"raw_source", "rule_metadata"}:
                equal = actual == json.loads(value)
            elif isinstance(value, Decimal):
                equal = Decimal(str(actual)) == value
            else:
                equal = str(actual) == str(value)
            if not equal:
                raise ValueError("BANK_TRANSACTION_SOURCE_MISMATCH")
    actual_ids = {r["source_transaction_id"] for r in new}
    existing = {
        r["source_transaction_id"]: r
        for r in before["transactions"]
        if r["source_namespace"] == namespace
    }
    for source_id, row in rows.items():
        if source_id not in actual_ids and (
            source_id not in existing
            or existing[source_id]["raw_source"] != json.loads(row["raw_source"])
        ):
            raise ValueError("UNVERIFIED_SKIPPED_OVERLAP")
    if frame.height - len(new) != result.rows_skipped_duplicates:
        raise ValueError("BANK_IMPORT_COUNT_MISMATCH")
    fingerprints = {n: fingerprint(after[n]) for n in source_names}
    data = {
        "version": "VERIFIED_BANK_APPEND_V1",
        "source_fingerprints": fingerprints,
        "previous_fingerprints": source_names,
        "import_run_id": run["id"],
        "source_sha256": result.sha256,
        "source_filename": result.source_file,
        "new_transaction_ids": sorted(r["id"] for r in new),
        "historical_rows_unchanged": True,
    }
    signature = hmac.new(
        (queue.root / "queue.key").read_bytes(), digest(data).encode(), hashlib.sha256
    ).hexdigest()
    artifact = json.dumps({"data": data, "signature": signature}, indent=2).encode()
    private_write(queue.root / "source_acceptances" / (run["id"] + ".json"), artifact)
    # Any interruption between these writes fails closed on manifest mismatch.
    private_write(queue.root / "ongoing_sources.json", artifact)
    queue.save_manifest(
        {
            **manifest,
            "source_fingerprints": fingerprints,
            "transaction_ids": list(
                dict.fromkeys(manifest["transaction_ids"] + data["new_transaction_ids"])
            ),
        }
    )
    return data
