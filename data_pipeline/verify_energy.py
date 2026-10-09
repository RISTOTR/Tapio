"""Read-only monthly verification; not an application analytics endpoint."""

import argparse
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.core.database import SessionLocal
from apps.api.app.domain.models import EnergyReading, MeteringPoint
from data_pipeline.normalize.energy import HELSINKI


def monthly_summary(session: Session, metering_point: str) -> list[dict[str, object]]:
    month = func.date_trunc("month", func.timezone("Europe/Helsinki", EnergyReading.timestamp))
    statement = (
        select(
            month.label("month"),
            func.sum(EnergyReading.consumption_kwh).label("consumption_kwh"),
            func.sum(EnergyReading.solar_export_kwh).label("solar_export_kwh"),
            func.avg(EnergyReading.temperature_c).label("average_temperature_c"),
            func.count().label("readings"),
            (func.count() - func.count(EnergyReading.temperature_c)).label("null_temperatures"),
            (func.count() - func.count(func.distinct(EnergyReading.timestamp))).label("duplicates"),
            func.min(EnergyReading.timestamp).label("min_timestamp"),
            func.max(EnergyReading.timestamp).label("max_timestamp"),
        )
        .join(MeteringPoint)
        .where(
            MeteringPoint.external_code == metering_point, EnergyReading.source_grain == "hourly"
        )
        .group_by(month)
        .order_by(month)
    )
    return [dict(row) for row in session.execute(statement).mappings()]


def reconcile_month(
    session: Session,
    metering_point: str,
    month: date,
    consumption_bill: Decimal,
    export_bill: Decimal,
) -> dict[str, object]:
    start = datetime(month.year, month.month, 1, tzinfo=HELSINKI)
    end = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1, tzinfo=HELSINKI)
    row = session.execute(
        select(
            func.count(),
            func.sum(EnergyReading.consumption_kwh),
            func.sum(EnergyReading.solar_export_kwh),
        )
        .join(MeteringPoint)
        .where(
            MeteringPoint.external_code == metering_point,
            EnergyReading.source_grain == "hourly",
            EnergyReading.timestamp >= start,
            EnergyReading.timestamp < end,
        )
    ).one()
    result: dict[str, object] = {"month": start.date(), "readings": row[0]}
    for name, total, bill in [
        ("consumption_kwh", row[1], consumption_bill),
        ("solar_export_kwh", row[2], export_bill),
    ]:
        difference = abs(total - bill) if total is not None else None
        result[name] = {
            "database_total": total,
            "invoice_total": bill,
            "absolute_difference": difference,
            "percentage_difference": difference * 100 / abs(bill)
            if difference is not None and bill != 0
            else None,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metering-point", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        report = monthly_summary(session, args.metering_point)
    print(json.dumps(report, default=str, indent=2))
    return 0 if report else 1


if __name__ == "__main__":
    raise SystemExit(main())
