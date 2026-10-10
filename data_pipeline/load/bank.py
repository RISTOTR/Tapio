"""Atomic bank import with archive-ID overlap protection and immutable prior facts."""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import UUID

import pandera as pa
import polars as pl
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.domain.enums import BusinessContext, ImportStatus, TransactionDirection
from apps.api.app.domain.models import ImportRun, Transaction
from data_pipeline.ingest.bank_csv import PARSER_VERSION, SOURCE_TYPE, BankInputError
from data_pipeline.normalize.bank import canonical_bank
from data_pipeline.validate.bank import bank_enriched_schema


class BankImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["imported", "already_imported", "failed"]
    source_file: str
    rows_parsed: int
    rows_loaded: int
    rows_skipped_duplicates: int
    parser_version: str
    sha256: str
    import_run_id: UUID
    error_code: str | None = None


def _insert_transactions(session: Session, frame: pl.DataFrame, namespace: str, run_id: UUID):
    loaded = skipped = 0
    for row in frame.iter_rows(named=True):
        source = json.loads(row.pop("raw_source"))
        rules = json.loads(row.pop("rule_metadata"))
        if not isinstance(source, dict) or not isinstance(rules, dict):
            raise BankInputError("invalid_audit_metadata")
        existing = session.scalar(
            select(Transaction).where(
                Transaction.source_namespace == namespace,
                Transaction.source_transaction_id == row["source_transaction_id"],
            )
        )
        if existing is not None:
            if existing.raw_source != source:
                raise BankInputError("archive_id_content_conflict")
            skipped += 1
            continue  # Never update facts, weak labels or human reviews on an overlap.
        if (row["amount"] > 0) != (row["direction"] == "incoming"):
            raise BankInputError("direction_amount_mismatch")
        session.add(
            Transaction(
                **{k: v for k, v in row.items() if k not in ["business_context", "direction"]},
                direction=TransactionDirection(row["direction"]),
                business_context=BusinessContext(row["business_context"]),
                source_namespace=namespace,
                raw_source=source,
                rule_metadata=rules,
                import_run_id=run_id,
            )
        )
        session.flush()  # Detect repeated IDs in this file, too; everything shares a savepoint.
        loaded += 1
    return loaded, skipped


def import_bank_bytes(
    raw: bytes,
    *,
    source_filename: str,
    account_key: str,
    session_factory: sessionmaker[Session],
    parser_version: str = PARSER_VERSION,
    normalize: Callable[[bytes, str], pl.DataFrame] = canonical_bank,
) -> BankImportResult:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", account_key):
        raise BankInputError("invalid_account_key")
    filename = Path(source_filename).name
    if not filename.strip():
        raise BankInputError("missing_source_filename")
    digest = sha256(raw).hexdigest()
    namespace = f"{SOURCE_TYPE}:{account_key}"
    lock_key = int.from_bytes(sha256(namespace.encode()).digest()[:8], signed=True)
    file_key = int.from_bytes(
        sha256(f"{SOURCE_TYPE}:{parser_version}:{digest}".encode()).digest()[:8], signed=True
    )
    parsed = loaded = skipped = 0
    outcome = "failed"
    error_code = None
    with session_factory.begin() as session:
        # Lock file identity first, so concurrent misassigned account aliases cannot
        # both accept the same file. Account locking also serializes different overlaps.
        session.execute(select(func.pg_advisory_xact_lock(file_key)))
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))
        run = ImportRun(
            source_type=SOURCE_TYPE,
            source_filename=filename,
            sha256=digest,
            parser_version=parser_version,
            status=ImportStatus.RUNNING,
            source_metadata={"source_namespace": namespace},
        )
        session.add(run)
        session.flush()
        try:
            with session.begin_nested():
                previous = session.scalar(
                    select(ImportRun)
                    .where(
                        ImportRun.sha256 == digest,
                        ImportRun.source_type == SOURCE_TYPE,
                        ImportRun.parser_version == parser_version,
                        ImportRun.status == ImportStatus.COMPLETED,
                        ImportRun.source_metadata["outcome"].astext == "imported",
                    )
                    .order_by(ImportRun.started_at)
                    .limit(1)
                )
                if previous:
                    if previous.source_metadata.get("source_namespace") != namespace:
                        raise BankInputError("fingerprint_account_mismatch")
                    outcome = "already_imported"
                    parsed = previous.source_metadata["rows_parsed"]
                    skipped = parsed
                    run.source_metadata = {
                        **run.source_metadata,
                        "original_import_run_id": str(previous.id),
                    }
                else:
                    frame = normalize(raw, filename)
                    parsed = frame.height
                    if not parsed:
                        raise BankInputError("empty_source")
                    bank_enriched_schema.validate(frame)
                    if frame["source_file"].unique().to_list() != [filename]:
                        raise BankInputError("source_filename_mismatch")
                    loaded, skipped = _insert_transactions(session, frame, namespace, run.id)
                    outcome = "imported"
        except BankInputError as exc:
            error_code = str(exc)
        except (pa.errors.SchemaError, pa.errors.SchemaErrors):
            error_code = "canonical_validation_failed"
        except IntegrityError:
            error_code = "database_constraint_conflict"
        except Exception:
            error_code = "import_processing_failed"
        if error_code:
            outcome, loaded, skipped = "failed", 0, 0
        run.status = ImportStatus.FAILED if error_code else ImportStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.row_count = loaded
        run.source_metadata = {
            **run.source_metadata,
            "outcome": outcome,
            "rows_parsed": parsed,
            "rows_skipped_duplicates": skipped,
            "error_code": error_code,
        }
        result = BankImportResult(
            status=outcome,
            source_file=filename,
            rows_parsed=parsed,
            rows_loaded=loaded,
            rows_skipped_duplicates=skipped,
            parser_version=parser_version,
            sha256=digest,
            import_run_id=run.id,
            error_code=error_code,
        )
    return result
