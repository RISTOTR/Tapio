"""MHY six-column sale summary. Absent planned values stay null."""

import re

from .base import DATE, NUM, ParsedDocument, Sale, SaleLine, day, dec, flat, require

VERSION = "mhy-sale-1"
VENDOR = "Metsänhoitoyhdistys Keski-Suomi"


def parse(pages):
    t = flat("\n".join(pages))
    header = require(r"(TM-[\w-]+) (" + DATE + ")", t)
    buyer = require(r"Ostaja[^\n]*\n(.+?) (" + DATE + r")/", t)
    area = dec(require(r"Yhteensä (" + NUM + ") " + NUM, t)[1])
    totals = require(
        r"Puukauppa yhteensä (" + NUM + ") (" + NUM + ") (" + NUM + ") (" + NUM + ")", t
    )
    lines = []
    for page, text in enumerate(pages, 1):
        section = None
        for row in flat(text).splitlines():
            if row in ("Uudistushakkuu", "Harvennus", "Ensiharvennus"):
                section = row
                continue
            if not section or "yhteensä" in row:
                continue
            m = re.fullmatch(r"([^\d]+?) ((?:" + NUM + r" ?)+)", row)
            if not m:
                continue
            values = re.findall(NUM, m[2])
            if len(values) not in (3, 6):
                continue
            planned = list(map(dec, values[:3])) if len(values) == 6 else [None] * 3
            actual = list(map(dec, values[-3:]))
            lines.append(
                SaleLine(
                    harvest_type=section,
                    timber_product=m[1],
                    estimated_volume_m3=planned[0],
                    estimated_price_eur_per_m3=planned[1],
                    estimated_value_eur=planned[2],
                    actual_volume_m3=actual[0],
                    actual_price_eur_per_m3=actual[1],
                    actual_value_eur=actual[2],
                    page=page,
                )
            )
    sale = Sale(
        buyer=buyer[1],
        association=VENDOR,
        contract_number=header[1],
        sale_date=day(buyer[2]),
        total_area_ha=area,
        estimated_volume_m3=dec(totals[1]),
        estimated_value_eur=dec(totals[2]),
        actual_volume_m3=dec(totals[3]),
        actual_value_eur=dec(totals[4]),
        lines=lines,
    )
    return ParsedDocument(
        kind="FORESTRY_SALE_SUMMARY",
        vendor=VENDOR,
        parser_version=VERSION,
        document_date=day(header[2]),
        page_count=len(pages),
        sale=sale,
        warnings=["sale_totals_differ"] if any(dec(v) for v in sale.differences.values()) else [],
    )
