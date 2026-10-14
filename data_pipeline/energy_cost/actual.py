"""python -m data_pipeline.energy_cost.actual --help"""

from datetime import date

from .cli import output, parser, run
from .engine import calculate
from .reconciliation import reconcile_invoice
from .sources import load


def main():
    p = parser("Reconstruct source-supported costs; no database writes.")
    p.add_argument("--scope", choices=["all", "grid", "supplier"], default="all")
    p.add_argument(
        "--reconcile",
        action="store_true",
        help="Compare electricity invoices contained in the requested range.",
    )
    args = p.parse_args()

    def action(session):
        readings, tariffs, documents = load(session, args.start, args.end, args.meter_id)
        if args.reconcile:
            items = []
            for document_id, metadata in documents:
                if metadata.get("kind") not in ("GRID_INVOICE", "ENERGY_INVOICE"):
                    continue
                bill = metadata["bill"]
                periods = {(e["period_start"], e["period_end"]) for e in bill["energy"]}
                if len(periods) != 1:
                    continue
                a, b = map(date.fromisoformat, next(iter(periods)))
                if not args.start <= a <= b <= args.end:
                    continue
                # Source provider/meters must match the selected metering point.
                from sqlalchemy import select

                from apps.api.app.domain.models import EnergyReading, MeteringPoint

                ids = list(session.scalars(select(EnergyReading.metering_point_id).distinct()))
                meter = session.get(MeteringPoint, args.meter_id or ids[0])
                if not any(e["usage_point"] == meter.external_code for e in bill["energy"]):
                    continue
                rows, _, _ = load(session, a, b, args.meter_id)
                item = reconcile_invoice(rows, tariffs, metadata, a, b)
                item["source_document_id"] = str(document_id)
                items.append(item)
            result = {"mode": "ACTUAL_RECONSTRUCTION", "invoices": items}
        else:
            result = calculate(readings, tariffs, args.start, args.end, args.scope)
        output(result, args.output)

    run(action)


if __name__ == "__main__":
    main()
