"""Read-only projections of immutable source evidence, never backfilled prices."""

import re
from datetime import date, time, timedelta

from sqlalchemy import select

from apps.api.app.domain.models import Document, EnergyReading, MeteringPoint

from .reviewed import load_reviewed
from .types import Component, CostError, D, Reading, Season, Tariff, Window, boundaries


class Tariffs:
    def __init__(self, values):
        self.values = tuple(values)
        for i, a in enumerate(self.values):
            for b in self.values[i + 1 :]:
                if a.component == b.component and a.window == b.window:
                    if max(a.effective_from, b.effective_from) < min(
                        a.effective_to or date.max, b.effective_to or date.max
                    ):
                        raise CostError("OVERLAPPING_TARIFF_DEFINITIONS")

    def get(self, component, day, window=Window.ALL):
        matches = [
            t
            for t in self.values
            if t.component == component and t.window == window and t.covers(day)
        ]
        if not matches:
            raise CostError("MISSING_PRICE_COVERAGE")
        if len(matches) != 1:
            raise CostError("AMBIGUOUS_TARIFF_DEFINITIONS")
        return matches[0]

    def grid(self, timestamp):
        # Determine schedule from the active definition, never from an unrelated era.
        from .types import HELSINKI, classify_grid_tariff

        day = timestamp.astimezone(HELSINKI).date()
        other = self.get(Component.GRID_TRANSFER, day, Window.OTHER_TIME)
        winter = self.get(Component.GRID_TRANSFER, day, Window.WINTER_DAY)
        if other.season != winter.season:
            raise CostError("AMBIGUOUS_TARIFF_SCHEDULE")
        window = classify_grid_tariff(timestamp, other.season)
        return (winter if window == Window.WINTER_DAY else other), window


def season_from_metadata(values):
    dates = re.fullmatch(r"(\d+)\.(\d+)\.-(\d+)\.(\d+)\.", values["winter_period"])
    clock = re.fullmatch(r"ma-la klo (\d+)-(\d+)", values["winter_weekday_time_rule"])
    if not dates or not clock:
        raise CostError("UNSUPPORTED_SOURCE_SCHEDULE")
    return Season(
        start_month=int(dates[2]),
        start_day=int(dates[1]),
        end_month=int(dates[4]),
        end_day=int(dates[3]),
        weekdays=tuple(range(6)),
        start_time=time(int(clock[1])),
        end_time=time(int(clock[2])),
    )


def project_tariffs(documents, usage_point):
    values = []
    for document_id, m in documents:
        kind = m.get("kind")
        common = {
            "provider": m.get("vendor"),
            "source_document_id": str(document_id),
            "source_version": m.get("parser_version"),
        }
        if kind == "GRID_CONTRACT":
            c = m["contract"]
            if c["role"] != "consumption" or c["usage_point"] != usage_point:
                continue
            dates = c["price_sheet_effective_dates"]
            if len(dates) != 1:
                raise CostError("AMBIGUOUS_PRICE_SHEET_DATE")
            start = max(date.fromisoformat(c["effective_date"]), date.fromisoformat(dates[0]))
            t = c["tariff"]
            season = season_from_metadata(t)
            # The exact source tax gross/net pair establishes the common VAT factor.
            # Rounded display transfer prices are not a substitute for precise net × VAT.
            net_tax = D(t["tax_net_snt_per_kwh"])
            gross_tax = D(t["tax_gross_snt_per_kwh"])
            if net_tax <= 0:
                raise CostError("UNSUPPORTED_SOURCE_VAT")
            vat = (gross_tax / net_tax - 1) * 100
            for component, window, key, unit in [
                (
                    Component.GRID_TRANSFER,
                    Window.WINTER_DAY,
                    "winter_net_snt_per_kwh",
                    "EUR_PER_KWH",
                ),
                (
                    Component.GRID_TRANSFER,
                    Window.OTHER_TIME,
                    "other_net_snt_per_kwh",
                    "EUR_PER_KWH",
                ),
                (Component.ELECTRICITY_TAX, Window.ALL, "tax_net_snt_per_kwh", "EUR_PER_KWH"),
                (Component.GRID_FIXED_FEE, Window.ALL, "base_net_eur_per_month", "EUR_PER_MONTH"),
            ]:
                values.append(
                    Tariff(
                        **common,
                        product=c["product"],
                        effective_from=start,
                        component=component,
                        window=window,
                        unit=unit,
                        unit_price=D(t[key]) / (100 if unit == "EUR_PER_KWH" else 1),
                        price_basis="NET",
                        vat_rate=vat,
                        source_kind="CONTRACT",
                        season=season if component == Component.GRID_TRANSFER else None,
                    )
                )
        elif kind == "ENERGY_INVOICE":
            bill = m["bill"]
            imports = [
                e
                for e in bill["energy"]
                if e["usage_point"] == usage_point and e["consumption_kwh"] is not None
            ]
            if len(imports) != 1:
                continue
            # Export association is evidenced by the same consolidated document;
            # never select an unrelated meter's readings by address or string similarity.
            for e in bill["energy"]:
                start = date.fromisoformat(e["period_start"])
                end = date.fromisoformat(e["period_end"]) + timedelta(days=1)
                base = {
                    **common,
                    "product": e["product"],
                    "effective_from": start,
                    "effective_to": end,
                    "price_basis": "GROSS",
                    "vat_rate": D(0),
                    "source_kind": "INVOICE_PERIOD",
                }
                if e["consumption_kwh"] is not None:
                    for comp, key, unit in [
                        (Component.ENERGY_IMPORT, "energy_price_eur_per_kwh", "EUR_PER_KWH"),
                        (Component.SUPPLIER_FIXED_FEE, "base_fee_eur", "EUR_PER_MONTH"),
                    ]:
                        if e[key] is not None:
                            if comp == Component.SUPPLIER_FIXED_FEE and (
                                start.day != 1 or end.day != 1
                            ):
                                continue  # A partial-period fee is not a monthly tariff.
                            values.append(
                                Tariff(**base, component=comp, unit=unit, unit_price=D(e[key]))
                            )
                else:
                    # Effective credit rate is negative of the invoice's signed charge.
                    if (
                        e["export_price_eur_per_kwh"] is not None
                        and e["export_margin_eur_per_kwh"] is not None
                    ):
                        values.append(
                            Tariff(
                                **{**base, "source_kind": "BILLED_EXPORT_AVERAGE"},
                                component=Component.SOLAR_EXPORT_CREDIT,
                                unit="EUR_PER_KWH",
                                unit_price=-(
                                    D(e["export_price_eur_per_kwh"])
                                    + D(e["export_margin_eur_per_kwh"])
                                ),
                                export_spot_rate=-D(e["export_price_eur_per_kwh"]),
                                export_margin=D(e["export_margin_eur_per_kwh"]),
                            )
                        )
    return Tariffs(values)


def load(session, start, end, meter_id=None):
    ids = list(session.scalars(select(EnergyReading.metering_point_id).distinct()))
    if meter_id is None:
        if len(ids) != 1:
            raise CostError("EXPLICIT_METER_REQUIRED")
        meter_id = ids[0]
    meter = session.get(MeteringPoint, meter_id)
    if meter is None:
        raise CostError("UNKNOWN_METER")
    a, b = boundaries(start, end)
    rows = list(
        session.scalars(
            select(EnergyReading)
            .where(
                EnergyReading.metering_point_id == meter_id,
                EnergyReading.source_grain == "hourly",
                EnergyReading.timestamp >= a,
                EnergyReading.timestamp < b,
            )
            .order_by(EnergyReading.timestamp)
        )
    )
    readings = [
        Reading(
            timestamp=r.timestamp,
            consumption_kwh=r.consumption_kwh,
            solar_export_kwh=r.solar_export_kwh,
        )
        for r in rows
    ]
    documents = [
        (d.id, d.document_metadata) for d in session.scalars(select(Document).order_by(Document.id))
    ]
    projected = project_tariffs(documents, meter.external_code)
    tariffs = Tariffs([*projected.values, *load_reviewed(meter.external_code)])
    return readings, tariffs, documents
