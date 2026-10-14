"""Explicit user scenarios; optional fixed-versus-spot comparison."""

from .cli import output, parser, run
from .engine import calculate
from .scenarios import ElectricityScenario, SupplierScenario, compare
from .sources import load
from .spot import read_spot, weighted_prices
from .types import CostError, D


def main():
    p = parser("Retrospective scenario using unchanged measured consumption.")
    p.add_argument("--scope", choices=["all", "supplier"], default="all")
    p.add_argument("--name", default="user-scenario")
    p.add_argument("--fixed-price-eur-kwh", type=D)
    p.add_argument("--spot-source")
    p.add_argument("--compare", action="store_true")
    p.add_argument("--supplier-monthly-fee", type=D, required=True)
    p.add_argument("--spot-supplier-monthly-fee", type=D)
    p.add_argument("--spot-markup-eur-kwh", type=D, default=D(0))
    p.add_argument("--price-basis", choices=["NET", "GROSS"], required=True)
    p.add_argument("--vat-rate", type=D, required=True)
    p.add_argument("--export-pricing", choices=["omit", "fixed", "spot"], default="omit")
    p.add_argument("--export-price-eur-kwh", type=D)
    p.add_argument("--export-margin-eur-kwh", type=D)
    p.add_argument("--export-price-basis", choices=["NET", "GROSS"])
    p.add_argument("--export-vat-rate", type=D)
    p.add_argument("--export-spot-source")
    args = p.parse_args()

    def action(session):
        readings, tariffs, _ = load(session, args.start, args.end, args.meter_id)
        spot = read_spot(args.spot_source) if args.spot_source else None
        export = read_spot(args.export_spot_source) if args.export_spot_source else None
        for source in (spot, export):
            if source:
                source.require(readings)
        if args.compare and (spot is None or args.fixed_price_eur_kwh is None):
            raise CostError("COMPARISON_REQUIRES_FIXED_PRICE_AND_SPOT")
        if not args.compare and (spot is not None) == (args.fixed_price_eur_kwh is not None):
            raise CostError("SELECT_ONE_IMPORT_PRICING_TYPE")
        common = dict(
            name=args.name,
            supplier_monthly_fee=args.supplier_monthly_fee,
            price_basis=args.price_basis,
            vat_rate=args.vat_rate,
            export_pricing_type=args.export_pricing,
            export_fixed_price=args.export_price_eur_kwh,
            export_margin=args.export_margin_eur_kwh,
            export_price_basis=args.export_price_basis,
            export_vat_rate=args.export_vat_rate,
        )
        fixed = (
            SupplierScenario(
                ElectricityScenario(
                    **common,
                    import_pricing_type="fixed",
                    fixed_import_price=args.fixed_price_eur_kwh,
                ),
                export_spot=export,
            )
            if args.fixed_price_eur_kwh is not None
            else None
        )
        variable = (
            SupplierScenario(
                ElectricityScenario(
                    **{
                        **common,
                        "supplier_monthly_fee": args.spot_supplier_monthly_fee
                        if args.spot_supplier_monthly_fee is not None
                        else args.supplier_monthly_fee,
                    },
                    import_pricing_type="spot",
                    spot_markup_per_kwh=args.spot_markup_eur_kwh,
                ),
                spot,
                export,
            )
            if spot
            else None
        )
        result = (
            compare(readings, tariffs, args.start, args.end, fixed, variable, scope=args.scope)
            if args.compare
            else calculate(
                readings,
                tariffs,
                args.start,
                args.end,
                scope=args.scope,
                supplier=fixed or variable,
            )
        )
        if spot:
            result["spot_averages"] = weighted_prices(readings, spot)
        if export:
            result["export_spot_averages"] = weighted_prices(readings, export)
        output(result, args.output)

    run(action)


if __name__ == "__main__":
    main()
