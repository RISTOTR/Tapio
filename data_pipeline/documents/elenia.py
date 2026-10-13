"""Elenia actual billed lines, including zero-cost production transfer."""

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

VERSION = "elenia-invoice-1"
VENDOR = "Elenia Verkko Oyj"


def parse(pages):
    t = flat("\n".join(pages))
    head = flat(pages[0])
    header = require(r"Laskun numero Laskun päivämäärä\n.*?(\d{8,}) (" + DATE + ")", head)
    customer = require(r"Asiakkaan nimi Asiakasnumero\n(.+?) \d+", head)[1]
    due = day(require(r"Eräpäivä (" + DATE + ")", head)[1])
    reference = require(r"Viitenro ([\d ]+)", head)[1].replace(" ", "")
    net = dec(require(r"Arvonlisäveroton summa (" + NUM + ")", t)[1])
    vatmatch = require(r"Lasku sisältää (" + NUM + r") % arvonlisäveroa (" + NUM + ")", t)
    rate, vat = dec(vatmatch[1]), dec(vatmatch[2])
    lines = []
    energies = []
    for page, text in enumerate(pages, 1):
        for block in re.split(r"(?=Käyttöpaikka \d{18},)", flat(text))[1:]:
            if "KULUTUSLASKU" not in block:
                continue
            usage = require(r"Käyttöpaikka (\d{18})", block)[1]
            product = require(r"Verkkopalvelu Elenia Verkko Oyj, (.+)", block)[1]
            dates = require(r"(" + DATE + r") - (" + DATE + ")", block)
            section = []
            pattern = (
                rf"^(Perusmaksu|Talviarkipäiväsiirto|Muun ajan siirto|"
                rf"Sähkövero \(veroluokka \d\)|Tuotannon siirto) "
                rf"({NUM}) (kk|kWh) ({NUM}) (¤/kk|snt/kWh) ({NUM}) ({NUM}) ({NUM}) ¤$"
            )
            for m in re.finditer(pattern, block, re.M):
                price = dec(m[4]) / (100 if m[5] == "snt/kWh" else 1)
                section.append(
                    Line(
                        description=m[1],
                        quantity=dec(m[2]),
                        unit=m[3],
                        unit_price_eur=price,
                        printed_price_quantum=Decimal(1).scaleb(dec(m[4]).as_tuple().exponent)
                        / (100 if "snt" in m[5] else 1),
                        vat_rate=rate,
                        net_amount_eur=dec(m[6]),
                        vat_amount_eur=dec(m[7]),
                        gross_amount_eur=dec(m[8]),
                        usage_point=usage,
                        page=page,
                        price_basis="gross",
                    )
                )
            export = product == "Tuotannon siirto"
            if len(section) != (2 if export else 4):
                raise DocumentError("unsupported_elenia_lines")
            total = require(r"^YHTEENSÄ (" + NUM + ") (" + NUM + ") (" + NUM + ") ¤", block, re.M)
            for field, value in zip(
                ("net_amount_eur", "vat_amount_eur", "gross_amount_eur"),
                total.groups(),
                strict=True,
            ):
                if sum(getattr(line, field) for line in section) != dec(value):
                    raise DocumentError("elenia_component_mismatch")
            quantities = [
                line.quantity
                for line in section
                if line.description in ("Talviarkipäiväsiirto", "Muun ajan siirto")
            ]
            fuse = re.search(r"\d+x\d+ A", product)
            energies.append(
                Energy(
                    usage_point=usage,
                    period_start=day(dates[1]),
                    period_end=day(dates[2]),
                    product=product,
                    fuse_size=fuse[0] if fuse else None,
                    page=page,
                    consumption_kwh=sum(quantities, Decimal(0)) if not export else None,
                    solar_export_kwh=section[1].quantity if export else None,
                    base_fee_eur=section[0].gross_amount_eur,
                )
            )
            lines.extend(section)
    total = dec(require(r"Eräpäivä " + DATE + r" Euro (" + NUM + ")", head)[1])
    bill = Bill(
        vendor=VENDOR,
        invoice_number=header[1],
        invoice_date=day(header[2]),
        due_date=due,
        customer=customer,
        reference=reference,
        subtotal_eur=net,
        vat_eur=vat,
        total_eur=total,
        lines=lines,
        energy=energies,
    )
    return ParsedDocument(
        kind="GRID_INVOICE",
        vendor=VENDOR,
        parser_version=VERSION,
        document_date=bill.invoice_date,
        page_count=len(pages),
        bill=bill,
    )
