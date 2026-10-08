"""Run against a migrated PostgreSQL database with TAPIO_TEST_DATABASE_URL set.

Every test rolls back its outer transaction, including failed-constraint tests.
"""

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.domain.enums import (
    BusinessContext,
    DocumentType,
    TaxReviewStatus,
    TransactionDirection,
)
from apps.api.app.domain.models import (
    Document,
    EnergyReading,
    ImportRun,
    MeteringPoint,
    TaxReview,
    Transaction,
)


@pytest.fixture
def session() -> Iterator[Session]:
    url = os.environ.get("TAPIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TAPIO_TEST_DATABASE_URL to a migrated PostgreSQL test database")
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
    engine.dispose()


def test_energy_precision_provenance_and_duplicate_key(session: Session) -> None:
    run = ImportRun(
        source_type="synthetic",
        source_filename="synthetic.csv",
        sha256="0" * 64,
        parser_version="test",
    )
    meter = MeteringPoint(external_code="synthetic-test-meter")
    session.add_all([run, meter])
    session.flush()
    values = dict(
        metering_point_id=meter.id,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        consumption_kwh=Decimal("1.234567"),
        solar_export_kwh=Decimal("0.000001"),
        source_grain="hourly",
        import_run_id=run.id,
    )
    reading = EnergyReading(**values)
    session.add(reading)
    session.flush()
    session.refresh(reading)
    assert reading.consumption_kwh == Decimal("1.234567")
    assert reading.timestamp.utcoffset().total_seconds() == 0
    session.add(EnergyReading(**values))
    with pytest.raises(IntegrityError):
        session.flush()


def test_document_json_metadata_roundtrip(session: Session) -> None:
    run = ImportRun(
        source_type="synthetic",
        source_filename="synthetic.pdf",
        sha256="1" * 64,
        parser_version="test",
    )
    session.add(run)
    session.flush()
    document = Document(
        document_type=DocumentType.OTHER,
        source_filename="synthetic.pdf",
        sha256="1" * 64,
        import_run_id=run.id,
        document_metadata={"synthetic": True},
    )
    session.add(document)
    session.flush()
    session.refresh(document)
    assert document.document_metadata == {"synthetic": True}


def test_tax_decision_and_suggestion_roundtrip(session: Session) -> None:
    run = ImportRun(
        source_type="synthetic",
        source_filename="synthetic.csv",
        sha256="2" * 64,
        parser_version="test",
    )
    session.add(run)
    session.flush()
    transaction = Transaction(
        booking_date=date(2026, 1, 1),
        amount=Decimal("-20.00"),
        currency="EUR",
        direction=TransactionDirection.OUTGOING,
        source_file="synthetic.csv",
        import_run_id=run.id,
    )
    session.add(transaction)
    session.flush()
    review = TaxReview(
        transaction_id=transaction.id,
        suggested_context=BusinessContext.PERSONAL,
        suggested_treatment="Unconfirmed suggestion",
        confirmed_context=BusinessContext.FORESTRY,
        status=TaxReviewStatus.CONFIRMED_BUSINESS_EXPENSE,
        review_notes="Human decision",
    )
    session.add(review)
    session.flush()
    session.refresh(review)
    assert review.suggested_context == BusinessContext.PERSONAL
    assert review.confirmed_context == BusinessContext.FORESTRY
    assert review.status == TaxReviewStatus.CONFIRMED_BUSINESS_EXPENSE
    assert review.review_notes == "Human decision"
