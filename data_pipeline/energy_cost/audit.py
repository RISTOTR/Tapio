"""python -m data_pipeline.energy_cost.audit --help"""

from collections import defaultdict

from .cli import output, parser, run
from .coverage import audit
from .sources import load
from .spot import read_spot, weighted_prices
from .types import HELSINKI, validate_readings


def main():
    p = parser("Audit measured and documented price coverage.")
    p.add_argument("--spot-source")
    args = p.parse_args()

    def action(session):
        readings, tariffs, _ = load(session, args.start, args.end, args.meter_id)
        spot = read_spot(args.spot_source) if args.spot_source else None
        result = audit(readings, tariffs, args.start, args.end, spot)
        if spot and result["spot_prices_hours"] == result["expected_hours"]:
            validate_readings(readings, args.start, args.end)
            groups = defaultdict(list)
            for r in readings:
                local = r.timestamp.astimezone(HELSINKI)
                for key in ("requested_period", local.strftime("%Y"), local.strftime("%Y-%m")):
                    groups[key].append(r)
            result["spot_statistics"] = {
                key: {"hours": len(rows), **weighted_prices(rows, spot)}
                for key, rows in sorted(groups.items())
            }
        output(result, args.output)

    run(action)


if __name__ == "__main__":
    main()
