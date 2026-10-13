"""Vattenfall consolidated consumption/export bills; one payable invoice."""

import re
from decimal import Decimal

from .base import (
    DATE,
    NUM,
    Bill,
    DocumentError,
    Energy,
    Line,
    ParsedDocument,
    day,
    dec,
    flat,
    require,
)

VERSION = "vattenfall-1"
VENDOR = "Vattenfall Oy"


def parse(pages):
    head = flat(pages[0])
    alltext = flat("\n".join(pages))
    number = require(r"Laskunumero: (\d+)", head)[1]
    issued = day(require(r"Laskun päivämäärä (" + DATE + ")", alltext)[1])
    due = day(require(r"Laskun eräpäivä (" + DATE + ")", alltext)[1])
    reference = require(r"Laskun viitenumero ([\d ]+)", alltext)[1].replace(" ", "")
    customer = None
    # Address/header layouts vary; customer is the first left-column name above the usage table.
    for raw in pages[0].splitlines():
        for marker in ("Puh. 020", "Avoinna arkisin"):
            if marker in raw:
                candidate = raw.split(marker)[0].strip()
                if candidate:
                    customer = candidate
                    break
        if customer is not None:
            break
    if customer is None:
        raise DocumentError("unsupported_customer_layout")
    lines = []
    energy = []
    components = []
    for i, p in enumerate(pages):
        t = flat(p)
        if "Käyttöpaikan tunnus:" not in t:
            continue
        usage = require(r"Käyttöpaikan tunnus: (\d{18})", t)[1]
        product = require(r"Sähkösopimus (.+)", t)[1]
        if i + 1 >= len(pages):
            raise DocumentError("missing_vattenfall_detail_page")
        detail = flat(pages[i + 1])
        if "Laskun erittely" not in detail:
            raise DocumentError("missing_vattenfall_detail_page")
        rate = dec(require(r"Arvonlisävero (" + NUM + r") %", detail)[1])
        component = []
        start = end = None
        pattern = (
            rf"^(Perusmaksu|Energia|Marginaali|Spot-energia) "
            rf"({DATE})-({DATE}) ({NUM}) (eur/kk|snt/kWh)(?: ({NUM}) kWh)? ({NUM}) eur$"
        )
        for m in re.finditer(pattern, detail, re.M):
            start, end = day(m[2]), day(m[3])
            price = dec(m[4])
            if m[5] == "snt/kWh":
                price /= 100
            component.append(
                Line(
                    description=m[1],
                    quantity=dec(m[6]) if m[6] else None,
                    unit="kWh" if m[6] else "kk",
                    unit_price_eur=price,
                    printed_price_quantum=Decimal(1).scaleb(dec(m[4]).as_tuple().exponent)
                    / (100 if "snt" in m[5] else 1),
                    vat_rate=rate,
                    gross_amount_eur=dec(m[7]),
                    page=i + 2,
                    usage_point=usage,
                    price_basis="gross",
                )
            )
        if len(component) != 2 or start is None:
            raise DocumentError("unsupported_vattenfall_lines")
        total = dec(require(r"Laskun loppusumma (" + NUM + ") eur", detail)[1])
        net = dec(require(r"Veron peruste (" + NUM + ") eur", detail)[1])
        vat = dec(require(r"Arvonlisävero " + NUM + r" % (" + NUM + ") eur", detail)[1])
        if net + vat != total or sum(line.gross_amount_eur for line in component) != total:
            raise DocumentError("component_total_mismatch")
        components.append((net, vat, total))
        lookup = {line.description: line for line in component}
        export = "Spot-energia" in lookup
        if export and lookup["Spot-energia"].quantity != lookup["Marginaali"].quantity:
            raise DocumentError("export_quantity_mismatch")
        energy.append(
            Energy(
                usage_point=usage,
                period_start=start,
                period_end=end,
                product=product,
                page=i + 2,
                consumption_kwh=None if export else lookup["Energia"].quantity,
                solar_export_kwh=lookup["Spot-energia"].quantity if export else None,
                energy_price_eur_per_kwh=None if export else lookup["Energia"].unit_price_eur,
                base_fee_eur=None if export else lookup["Perusmaksu"].gross_amount_eur,
                export_price_eur_per_kwh=lookup["Spot-energia"].unit_price_eur if export else None,
                export_margin_eur_per_kwh=lookup["Marginaali"].unit_price_eur if export else None,
            )
        )
        lines.extend(component)
    net = dec(require(r"Veron peruste (" + NUM + ") eur", head)[1])
    vat = dec(require(r"Arvonlisävero " + NUM + r" % (" + NUM + ") eur", head)[1])
    total = dec(require(r"Laskun loppusumma (" + NUM + ") eur", head)[1])
    if tuple(sum((c[j] for c in components), Decimal(0)) for j in range(3)) != (net, vat, total):
        raise DocumentError("consolidation_mismatch")
    bill = Bill(
        vendor=VENDOR,
        invoice_number=number,
        invoice_date=issued,
        due_date=due,
        customer=customer,
        reference=reference,
        subtotal_eur=net,
        vat_eur=vat,
        total_eur=total,
        lines=lines,
        energy=energy,
    )
    return ParsedDocument(
        kind="ENERGY_INVOICE",
        vendor=VENDOR,
        parser_version=VERSION,
        document_date=issued,
        page_count=len(pages),
        bill=bill,
    )
