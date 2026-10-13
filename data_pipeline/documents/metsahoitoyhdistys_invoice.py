"""Known MHY single-page service invoice layouts."""

import re

from .base import (
    DATE,
    NUM,
    Bill,
    DocumentError,
    Line,
    ParsedDocument,
    cents,
    day,
    dec,
    flat,
    require,
)

VERSION = "mhy-invoice-1"
VENDOR = "Metsänhoitoyhdistys Keski-Suomi"


def parse(pages):
    if len(pages) != 1:
        raise DocumentError("unsupported_mhy_page_count")
    t = flat(pages[0])
    issued = day(require(r"Päiväys: (" + DATE + ")", t)[1])
    number = require(r"Laskunumero: (\d+)", t)[1]
    due = day(require(r"Eräpäivä: (" + DATE + ")", t)[1])
    customer = require(r"^(.+?) Päiväys:", t, re.M)[1]
    table = t.split("Alv-%", 1)[1].split("Metsänhoitoyhdistys", 1)[0]
    lines = []
    pattern = rf"^(.+?) (M\d+) ({NUM}) (m3|ha|kpl) ({NUM}) ({NUM}) ({NUM})$"
    for m in re.finditer(pattern, table, re.M):
        description = m[1]
        tail = table[m.end() :].splitlines()
        for extra in tail:
            extra = extra.strip()
            if not extra:
                continue
            if re.search(r"\d|yhteensä|Alv", extra, re.I):
                break
            description += " / " + extra
        net, rate = dec(m[6]), dec(m[7])
        vat = cents(net * rate / 100)
        lines.append(
            Line(
                description=description,
                product_code=m[2],
                quantity=dec(m[3]),
                unit=m[4],
                unit_price_eur=dec(m[5]),
                net_amount_eur=net,
                vat_rate=rate,
                vat_amount_eur=vat,
                gross_amount_eur=net + vat,
                page=1,
            )
        )
    if "Summa yhteensä:" in t:
        net = dec(require(r"Veroton arvo yhteensä: (" + NUM + ")", t)[1])
        vat = dec(require(r"Alv " + NUM + r" %: (" + NUM + ")", t)[1])
        gross = dec(require(r"Summa yhteensä: (" + NUM + ")", t)[1])
    else:
        m = require(r"Yhteensä (" + NUM + r") € (" + NUM + r") € (" + NUM + r") €", t)
        net, vat, gross = map(dec, m.groups())
    bill = Bill(
        vendor=VENDOR,
        invoice_number=number,
        invoice_date=issued,
        due_date=due,
        customer=customer,
        reference=require(r"Viitenumero: (\d+)", t)[1],
        order_number=require(r"Tilausnumero: ([\w-]+)", t)[1],
        subtotal_eur=net,
        vat_eur=vat,
        total_eur=gross,
        lines=lines,
    )
    return ParsedDocument(
        kind="FORESTRY_INVOICE",
        vendor=VENDOR,
        parser_version=VERSION,
        document_date=issued,
        page_count=1,
        bill=bill,
    )
