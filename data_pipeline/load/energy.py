"""Transactional persistence boundary for a source-specific energy normalizer."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import UUID

import pandera as pa
import polars as pl
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.domain.enums import ImportStatus
from apps.api.app.domain.models import EnergyReading, ImportRun, MeteringPoint
from data_pipeline.normalize.energy import EnergyInputError
from data_pipeline.validate.energy import energy_schema


class EnergyImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["imported", "already_imported", "failed"]
    source_file: str
    rows_parsed: int
    rows_loaded: int
    metering_point: str
    parser_version: str
    sha256: str
    import_run_id: UUID
    error_code: str | None = None


def _database_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    decimal = Decimal(str(value))
    if not decimal.is_finite() or abs(decimal) >= Decimal("100000000000000"):
        raise EnergyInputError("numeric_out_of_range")
    if decimal != decimal.quantize(Decimal("0.000001")):
        raise EnergyInputError("unsupported_numeric_precision")
    return decimal


def _insert_readings(session: Session, frame: pl.DataFrame, meter_id: UUID, run_id: UUID) -> None:
    # Batches limit memory and SQL parameter counts; they share the same transaction.
    for batch in frame.iter_slices(1000):
        rows = [
            {
                "metering_point_id": meter_id,
                "timestamp": row["timestamp"],
                "consumption_kwh": _database_decimal(row["consumption_kwh"]),
                "solar_export_kwh": _database_decimal(row["solar_export_kwh"]),
                "temperature_c": _database_decimal(row["temperature_c"]),
                "source_grain": "hourly",
                "import_run_id": run_id,
            }
            for row in batch.iter_rows(named=True)
        ]
        session.execute(insert(EnergyReading), rows)


def import_energy_bytes(
    raw: bytes,
    *,
    source_filename: str,
    metering_point: str,
    source_type: str,
    parser_version: str,
    normalize: Callable[[bytes], pl.DataFrame],
    session_factory: sessionmaker[Session],
) -> EnergyImportResult:
    """Hash and normalize the same bytes, then commit one atomic import attempt.

    The callable is the source-specific parse/normalize boundary, not a validator.
    This function always validates its result before any reading is inserted.
    Infrastructure errors during transaction setup/commit propagate to the caller.
    """
    if not metering_point or metering_point != metering_point.strip():
        raise EnergyInputError("invalid_metering_point")
    digest = sha256(raw).hexdigest()
    fingerprint = f"{source_type}\0{parser_version}\0{digest}"
    lock_key = int.from_bytes(sha256(fingerprint.encode()).digest()[:8], signed=True)
    parsed = loaded = 0
    outcome: Literal["imported", "already_imported", "failed"] = "failed"
    error_code: str | None = None
    with session_factory.begin() as session:
        # A transaction lock avoids check-then-insert races without altering the schema.
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))
        run = ImportRun(
            source_type=source_type,
            source_filename=Path(source_filename).name,
            sha256=digest,
            parser_version=parser_version,
            status=ImportStatus.RUNNING,
            source_metadata={"metering_point": metering_point, "source_grain": "hourly"},
        )
        session.add(run)
        session.flush()
        try:
            with session.begin_nested():
                previous = session.scalar(
                    select(ImportRun)
                    .where(
                        ImportRun.sha256 == digest,
                        ImportRun.source_type == source_type,
                        ImportRun.parser_version == parser_version,
                        ImportRun.status == ImportStatus.COMPLETED,
                        ImportRun.source_metadata["outcome"].astext == "imported",
                    )
                    .order_by(ImportRun.started_at)
                    .limit(1)
                )
                if previous is not None:
                    if previous.source_metadata.get("metering_point") != metering_point:
                        raise EnergyInputError("fingerprint_meter_mismatch")
                    outcome = "already_imported"
                    run.source_metadata = {
                        **run.source_metadata,
                        "original_import_run_id": str(previous.id),
                    }
                else:
                    frame = normalize(raw)
                    parsed = frame.height
                    if not parsed:
                        raise EnergyInputError("empty_source")
                    energy_schema.validate(frame)
                    session.execute(
                        insert(MeteringPoint)
                        .values(external_code=metering_point)
                        .on_conflict_do_nothing(index_elements=[MeteringPoint.external_code])
                    )
                    meter_id = session.scalars(
                        select(MeteringPoint.id).where(
                            MeteringPoint.external_code == metering_point
                        )
                    ).one()
                    _insert_readings(session, frame, meter_id, run.id)
                    loaded = frame.height
                    outcome = "imported"
        except EnergyInputError as exc:
            error_code = str(exc)
        except (pa.errors.SchemaError, pa.errors.SchemaErrors):
            error_code = "canonical_validation_failed"
        except IntegrityError:
            error_code = "database_constraint_conflict"
        except Exception:
            # Keep raw values/SQL parameters out of both result and audit metadata.
            error_code = "import_processing_failed"
        if error_code is not None:
            outcome = "failed"
            loaded = 0
        run.status = ImportStatus.FAILED if outcome == "failed" else ImportStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.row_count = loaded
        run.source_metadata = {
            **run.source_metadata,
            "outcome": outcome,
            "rows_parsed": parsed,
            "error_code": error_code,
        }
        result = EnergyImportResult(
            status=outcome,
            source_file=run.source_filename,
            rows_parsed=parsed,
            rows_loaded=loaded,
            metering_point=metering_point,
            parser_version=parser_version,
            sha256=digest,
            import_run_id=run.id,
            error_code=error_code,
        )
    return result  # The outer context has committed successfully.
