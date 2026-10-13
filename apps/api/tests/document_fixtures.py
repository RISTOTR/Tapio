"""Invented text and generated PDFs only; no copied private document contents."""

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf(pages):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=1200, height=1800)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        commands = ["BT /F1 8 Tf 10 TL 20 1760 Td"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj T*")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("cp1252"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def mhy(number="9001", variant=1):
    header = f"""LASKU
Synthetic Customer      Päiväys: 1.2.2026
Laskunumero: {number}
Viitenumero: 99001
Eräpäivä: 15.2.2026
Tilausnumero: SYNTHETIC-ORDER
Tuote Tuotekoodi Määrä Yksikkö Yks.hinta Veroton arvo Alv-%
"""
    if variant == 1:
        body = """Synthetic service M100 10,00 m3 2,00 20,00 25,5
Synthetic continuation
Veroton arvo yhteensä: 20,00 €
Alv 25,5 %: 5,10 €
Summa yhteensä: 25,10 €"""
    else:
        body = """Synthetic soil work M200 2,00 ha 10,00 20,00 25,5
Alv-% Veroton arvo ALV Verollinen arvo
Yhteensä 20,00 € 5,10 € 25,10 €"""
    return [header + body + "\nMetsänhoitoyhdistys Keski-Suomi ry"]


def vattenfall():
    head = """Koontilasku
Laskunumero: 80001
Synthetic Customer       Puh. 020 722 9000
Vattenfall Oy
Laskun päivämäärä 1.2.2026
Veron peruste 11,00 eur
Arvonlisävero 25.50 % 2,81 eur
Laskun loppusumma 13,81 eur"""

    def component(usage, product):
        return f"""Kulutuslasku
Käyttöpaikan tunnus: {usage}
Sähkösopimus {product}
Laskun eräpäivä 15.2.2026
Laskun viitenumero 9 80001"""

    consume = """Laskun erittely
Perusmaksu 01.01.2026-31.01.2026 2,51 eur/kk 2,51 eur
Energia 01.01.2026-31.01.2026 12,55 snt/kWh 100,00 kWh 12,55 eur
Veron peruste 12,00 eur
Arvonlisävero 25,50 % 3,06 eur
Laskun loppusumma 15,06 eur"""
    export = """Laskun erittely
Marginaali 01.01.2026-31.01.2026 0,50 snt/kWh 10,00 kWh 0,05 eur
Spot-energia 01.01.2026-31.01.2026 -13,00 snt/kWh 10,00 kWh -1,30 eur
Veron peruste -1,00 eur
Arvonlisävero 25,50 % -0,25 eur
Laskun loppusumma -1,25 eur"""
    return [
        head,
        component("111111111111111111", "Synthetic product"),
        consume,
        component("222222222222222222", "Omatuotanto"),
        export,
    ]


def elenia():
    return [
        """Elenia Verkko Oyj
Laskun numero Laskun päivämäärä
70001 1.2.2026
Asiakkaan nimi Asiakasnumero
Synthetic Customer 100
Viitenro 9 70001
Eräpäivä 15.2.2026 Euro 17,57""".replace("70001", "70000001"),
        """Käyttöpaikka 111111111111111111, Synthetic address
KULUTUSLASKU
Verkkopalvelu Elenia Verkko Oyj, Vuodenaikasiirto 3x25 A
1.1.2026 - 31.1.2026
Perusmaksu 1,00 kk 12,55 ¤/kk 10,00 2,55 12,55 ¤
Talviarkipäiväsiirto 100,00 kWh 1,255 snt/kWh 1,00 0,26 1,26 ¤
Muun ajan siirto 100,00 kWh 1,255 snt/kWh 1,00 0,25 1,25 ¤
Sähkövero (veroluokka 1) 200,00 kWh 1,255 snt/kWh 2,00 0,51 2,51 ¤
YHTEENSÄ 14,00 3,57 17,57 ¤
Käyttöpaikka 222222222222222222, Synthetic address
KULUTUSLASKU
Verkkopalvelu Elenia Verkko Oyj, Tuotannon siirto
1.1.2026 - 31.1.2026
Perusmaksu 1,00 kk 0,00 ¤/kk 0,00 0,00 0,00 ¤
Tuotannon siirto 12,00 kWh 0,00 snt/kWh 0,00 0,00 0,00 ¤
YHTEENSÄ 0,00 0,00 0,00 ¤""",
        """Arvonlisäveroton summa 14,00 ¤
Lasku sisältää 25,5 % arvonlisäveroa 3,57 ¤""",
    ]


def sale():
    return [
        """Puukaupan yhteenveto
Sopimus-/työmaanumero
TM-SYNTHETIC-001 1.2.2026
Ostaja Päiväys/Vastuualue
Synthetic Buyer 1.6.2025/000
Yhteensä 2,0 30,0
Kauppakirja Toteutuneet
Uudistushakkuu
PINE 10,00 20,00 200,00 12,00 20,00 240,00
BIRCH 2,00 5,00 10,00
Uudistushakkuu yhteensä 10,00 200,00 14,00 250,00
Puukauppa yhteensä 10,00 200,00 14,00 250,00
Metsänhoitoyhdistys Keski-Suomi"""
    ]


def contract(production=False):
    head = f"""Elenia Verkko Oyj
Vahvistusilmoitus 1.2.2026
Verkkopalvelusopimuksen vahvistusilmoitus
Sopimusnumero 900000
Sähkönkäyttöpaikan numero 111111111111111111
Pääsulakekoko 3x25A
Voimaantulopäivä 1.1.2026
Tuote {"Tuotannon siirto" if production else "Vuodenaikasiirto 3x25 A"}
Sähköveroluokka {"0" if production else "1"}"""
    tariff = """Verkkopalveluhinnasto
Pienasiakkaat | 1.1.2026
Vuodenaikasiirto
Siirto talviarki (1.11.-31.3. 3 x 25 A 10,00 12,55
ma-la klo 07-22) 2,00 2,51
Siirto muu aika 1,00 1,255
Sähkövero, veroluokka 1 2,00 2,51
nimellisteholtaan alle 50 kVA voimalaitokset, joista ei peritä tuotannon siirtomaksua
Siirto jakeluverkko tuotanto < 1 MVA* 0,70 0,88"""
    return [head, tariff]
