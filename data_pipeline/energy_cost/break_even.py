"""Import-only threshold where common grid/export terms cancel."""

from .cli import output, parser, run
from .scenarios import ElectricityScenario, SupplierScenario, supplier_break_even
from .sources import load
from .spot import read_spot, weighted_prices
from .types import D


def main():
    p = parser("Break-even supplier price for complete months, with common grid/export unchanged.")
    p.add_argument("--spot-source", required=True)
    p.add_argument("--spot-markup-eur-kwh", type=D, required=True)
    p.add_argument("--supplier-monthly-fee", type=D, required=True)
    p.add_argument("--fixed-monthly-fee-gross", type=D, required=True)
    p.add_argument("--price-basis", choices=["NET", "GROSS"], required=True)
    p.add_argument("--vat-rate", type=D, required=True)
    args = p.parse_args()

    def action(session):
        rows, _, _ = load(session, args.start, args.end, args.meter_id)
        spot = read_spot(args.spot_source)
        supplier = SupplierScenario(
            ElectricityScenario(
                name="User-supplied spot terms",
                import_pricing_type="spot",
                supplier_monthly_fee=args.supplier_monthly_fee,
                spot_markup_per_kwh=args.spot_markup_eur_kwh,
                price_basis=args.price_basis,
                vat_rate=args.vat_rate,
            ),
            spot,
        )
        result = supplier_break_even(
            rows, args.start, args.end, supplier, args.fixed_monthly_fee_gross
        )
        result["spot_statistics"] = weighted_prices(rows, spot)
        output(result, args.output)

    run(action)


if __name__ == "__main__":
    main()
