"""Real transactions in a disposable schema migrated with Alembic, never create_all."""

import os
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import polars as pl
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from apps.api.app.domain.enums import ImportStatus
from apps.api.app.domain.models import EnergyReading, ImportRun, MeteringPoint
from data_pipeline.load.energy import EnergyImportResult, import_energy_bytes
from data_pipeline.normalize.energy import EnergyInputError


@pytest.fixture(scope="module")
def factory() -> Iterator[sessionmaker[Session]]:
    url = os.environ.get("TAPIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TAPIO_TEST_DATABASE_URL for PostgreSQL integration tests")
    admin = create_engine(url)
    schema = f"energy_test_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    test_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(test_url)
    try:
        subprocess.run(
            [".venv/bin/alembic", "upgrade", "head"],
            env={**os.environ, "DATABASE_URL": test_url.render_as_string(hide_password=False)},
            check=True,
            capture_output=True,
        )
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture
def meter() -> str:
    return f"synthetic-{uuid4().hex}"


def frame(*, rows: int = 2, consumption: float = 1.25, start: int = 0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i)
                for i in range(start, start + rows)
            ],
            "consumption_kwh": [consumption] * rows,
            "solar_export_kwh": [0.25] * rows,
            "temperature_c": [None] * rows,
        },
        schema_overrides={"temperature_c": pl.Float64},
    )


def run_import(
    factory: sessionmaker[Session],
    meter: str,
    *,
    raw: bytes | None = None,
    data: pl.DataFrame | None = None,
    version: str = "test-1",
) -> EnergyImportResult:
    return import_energy_bytes(
        raw if raw is not None else meter.encode(),
        source_filename="synthetic_energy.csv",
        metering_point=meter,
        source_type="synthetic_energy_test",
        parser_version=version,
        normalize=lambda _: frame() if data is None else data,
        session_factory=factory,
    )


def count_readings(factory: sessionmaker[Session], meter: str) -> int:
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(EnergyReading)
            .join(MeteringPoint)
            .where(MeteringPoint.external_code == meter)
        )


def test_valid_import_and_repeat_are_audited(factory: sessionmaker[Session], meter: str) -> None:
    first = run_import(factory, meter)
    repeat = run_import(factory, meter)
    assert (first.status, first.rows_parsed, first.rows_loaded) == ("imported", 2, 2)
    assert (repeat.status, repeat.rows_parsed, repeat.rows_loaded) == ("already_imported", 0, 0)
    assert count_readings(factory, meter) == 2
    with factory() as session:
        original = session.get(ImportRun, first.import_run_id)
        skipped = session.get(ImportRun, repeat.import_run_id)
        assert original.status == skipped.status == ImportStatus.COMPLETED
        assert original.row_count == 2 and skipped.row_count == 0
        assert skipped.source_metadata["original_import_run_id"] == str(original.id)
        assert (
            session.scalar(
                select(func.count())
                .select_from(MeteringPoint)
                .where(MeteringPoint.external_code == meter)
            )
            == 1
        )
        assert (
            session.scalar(
                select(EnergyReading.temperature_c).where(
                    EnergyReading.import_run_id == first.import_run_id
                )
            )
            is None
        )


def test_validation_failure_has_audit_but_no_rows(
    factory: sessionmaker[Session], meter: str
) -> None:
    result = run_import(factory, meter, data=frame(consumption=-1.0))
    assert result.status == "failed"
    assert result.error_code == "canonical_validation_failed"
    assert count_readings(factory, meter) == 0
    with factory() as session:
        attempt = session.get(ImportRun, result.import_run_id)
        assert attempt.status == ImportStatus.FAILED
        assert attempt.row_count == 0
        assert attempt.completed_at is not None
    # Failed attempts do not poison the successful-import lookup.
    assert run_import(factory, meter).status == "imported"


def test_overlap_rolls_back_new_rows(factory: sessionmaker[Session], meter: str) -> None:
    assert run_import(factory, meter, data=frame(start=1000, rows=1)).status == "imported"
    # First batch inserts 1000 new rows, second batch conflicts with an existing key.
    result = run_import(factory, meter, raw=f"overlap-{meter}".encode(), data=frame(rows=1001))
    assert result.status == "failed"
    assert result.error_code == "database_constraint_conflict"
    assert result.rows_loaded == 0
    assert count_readings(factory, meter) == 1


def test_new_parser_cannot_replace_existing_data(
    factory: sessionmaker[Session], meter: str
) -> None:
    assert run_import(factory, meter).status == "imported"
    result = run_import(factory, meter, version="test-2")
    assert result.status == "failed"
    assert count_readings(factory, meter) == 2


def test_same_bytes_wrong_meter_rejected(factory: sessionmaker[Session], meter: str) -> None:
    assert run_import(factory, meter).status == "imported"
    result = run_import(factory, meter + "-other", raw=meter.encode())
    assert result.error_code == "fingerprint_meter_mismatch"
    assert count_readings(factory, meter + "-other") == 0


def test_concurrent_repeat_loads_once(factory: sessionmaker[Session], meter: str) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_import(factory, meter), range(2)))
    assert sorted(result.status for result in results) == ["already_imported", "imported"]
    assert count_readings(factory, meter) == 2


def test_parser_failure_has_sanitized_audit(factory: sessionmaker[Session], meter: str) -> None:
    def broken_parser(raw: bytes) -> pl.DataFrame:
        raise EnergyInputError("malformed_timestamp")

    result = import_energy_bytes(
        b"synthetic malformed input",
        source_filename="synthetic.csv",
        metering_point=meter,
        source_type="synthetic",
        parser_version="test-1",
        normalize=broken_parser,
        session_factory=factory,
    )
    assert result.status == "failed"
    assert result.error_code == "malformed_timestamp"
    assert count_readings(factory, meter) == 0


def test_precision_failure_rolls_back_meter(factory: sessionmaker[Session], meter: str) -> None:
    result = run_import(factory, meter, data=frame(consumption=0.0000001))
    assert result.error_code == "unsupported_numeric_precision"
    with factory() as session:
        assert (
            session.scalar(select(MeteringPoint).where(MeteringPoint.external_code == meter))
            is None
        )
    assert count_readings(factory, meter) == 0


def test_monthly_checks_use_helsinki_boundaries(factory: sessionmaker[Session], meter: str) -> None:
    from datetime import date
    from decimal import Decimal

    from data_pipeline.verify_energy import monthly_summary, reconcile_month

    data = frame(rows=3).with_columns(
        pl.Series(
            "timestamp",
            [
                datetime(2026, 7, 31, 20, tzinfo=UTC),  # July 31 23:00 Helsinki
                datetime(2026, 7, 31, 21, tzinfo=UTC),  # August 1 00:00 Helsinki
                datetime(2026, 8, 31, 21, tzinfo=UTC),  # September 1 00:00 Helsinki
            ],
        )
    )
    assert run_import(factory, meter, data=data).status == "imported"
    with factory() as session:
        summaries = monthly_summary(session, meter)
        assert [row["month"].month for row in summaries] == [7, 8, 9]
        assert all(row["readings"] == 1 and row["null_temperatures"] == 1 for row in summaries)
        result = reconcile_month(session, meter, date(2026, 8, 1), Decimal("1"), Decimal("0.25"))
        assert result["readings"] == 1
        assert result["consumption_kwh"]["absolute_difference"] == Decimal("0.25")
        assert result["consumption_kwh"]["percentage_difference"] == Decimal("25")
        assert result["solar_export_kwh"]["absolute_difference"] == 0
        empty = reconcile_month(session, meter, date(2026, 10, 1), Decimal("1"), Decimal("1"))
        assert empty["consumption_kwh"]["database_total"] is None
        assert empty["consumption_kwh"]["absolute_difference"] is None


def test_source_cli_end_to_end(
    factory: sessionmaker[Session], meter: str, monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    import json
    from pathlib import Path

    from data_pipeline.ingest import energy

    monkeypatch.setattr(energy, "SessionLocal", factory)
    source = tmp_path / "synthetic_energy.csv"
    source.write_bytes((Path("data/sample/synthetic_energy_hourly.csv")).read_bytes())
    args = ["--file", str(source), "--metering-point", meter]
    assert energy.main(args) == 0
    assert json.loads(capsys.readouterr().out)["rows_loaded"] == 2
    assert energy.main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_imported"
    source.write_bytes(source.read_bytes().replace(b"1,125", b"-1,125"))
    assert energy.main(args) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "canonical_validation_failed"
    assert count_readings(factory, meter) == 2
