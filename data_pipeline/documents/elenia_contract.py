"""Contract facts and printed tariff metadata, without a tariff calculation engine."""

import re

from .base import DATE, NUM, ParsedDocument, day, dec, flat, require

VERSION = "elenia-contract-1"


def parse(pages):
    head = flat(pages[0])
    text = flat("\n".join(pages))
    production = "Tuote Tuotannon siirto" in head
    effective = day(
        require(r"(?:Voimaantulopäivä|Sopimuksen voimaantulopäivä) (" + DATE + ")", head)[1]
    )
    facts = {
        "role": "production" if production else "consumption",
        "usage_point": require(r"Sähkönkäyttöpaikan numero (\d{18})", head)[1],
        "contract_number": require(r"Sopimusnumero (\d+)", head)[1],
        "effective_date": effective.isoformat(),
        "product": require(r"Tuote (.+)", head)[1],
        "fuse_size": require(r"Pääsulakekoko (\S+)", head)[1],
        "tax_class": require(r"Sähköveroluokka (\d)", head)[1],
        "page": 1,
    }
    dates = re.findall(
        r"(?:Pienasiakkaat \||Suurasiakkaat \||alkaen|Alkaen|Voimassa|voimassa) (" + DATE + ")",
        text,
    )
    facts["price_sheet_effective_dates"] = sorted({day(d).isoformat() for d in dates})
    if production:
        m = require(
            r"nimellisteholtaan alle (\d+) kVA voimalaitokset, "
            r"joista ei peritä tuotannon siirtomaksua",
            text,
        )
        facts["production_fee_rule"] = {
            "exempt_below_kva": m[1],
            "condition": "nameplate_power_less_than_threshold",
            "source_page": next(i for i, p in enumerate(pages, 1) if "nimellisteholtaan alle" in p),
        }
        m = require(r"Siirto jakeluverkko tuotanto < 1 MVA\* (" + NUM + ") (" + NUM + ")", text)
        facts["production_fee_rule"].update(
            net_eur_per_mwh=str(dec(m[1])), gross_eur_per_mwh=str(dec(m[2]))
        )
    else:
        section = text.split("\nVuodenaikasiirto\n", 1)[1]
        winter = require(r"Siirto talviarki \(([^\n]+)", section)[1]
        schedule = require(r"(ma-la klo \d+-\d+)\) (" + NUM + ") (" + NUM + ")", section)
        other = require(r"Siirto muu aika (" + NUM + ") (" + NUM + ")", section)
        base = require(r"3 x 25 A (" + NUM + ") (" + NUM + ")", section)
        tax = require(r"Sähkövero, veroluokka 1 (" + NUM + ") (" + NUM + ")", section)
        facts["tariff"] = {
            "winter_period": winter.split(" ")[0],
            "winter_weekday_time_rule": schedule[1],
            "winter_net_snt_per_kwh": str(dec(schedule[2])),
            "winter_gross_snt_per_kwh": str(dec(schedule[3])),
            "other_net_snt_per_kwh": str(dec(other[1])),
            "other_gross_snt_per_kwh": str(dec(other[2])),
            "base_net_eur_per_month": str(dec(base[1])),
            "base_gross_eur_per_month": str(dec(base[2])),
            "tax_net_snt_per_kwh": str(dec(tax[1])),
            "tax_gross_snt_per_kwh": str(dec(tax[2])),
            "source_page": next(i for i, p in enumerate(pages, 1) if "Siirto talviarki" in p),
        }
    return ParsedDocument(
        kind="GRID_CONTRACT",
        vendor="Elenia Verkko Oyj",
        parser_version=VERSION,
        document_date=day(require(r"Vahvistusilmoitus (" + DATE + ")", head)[1]),
        page_count=len(pages),
        contract=facts,
        warnings=[] if dates else ["price_sheet_effective_date_not_extracted"],
    )
