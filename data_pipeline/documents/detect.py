"""Explicit layout signatures, with no guessed or generic extraction fallback."""

from . import elenia, elenia_contract, forestry_sale_summary, metsahoitoyhdistys_invoice, vattenfall
from .base import DocumentError, flat


def parser_for(pages):
    text = flat("\n".join(pages))
    if "Puukaupan yhteenveto" in text and "Metsänhoitoyhdistys Keski-Suomi" in text:
        return forestry_sale_summary
    if (
        "Metsänhoitoyhdistys Keski-Suomi" in text
        and "Laskunumero:" in text
        and "Tuotekoodi" in text
    ):
        return metsahoitoyhdistys_invoice
    if "Vattenfall Oy" in text and "Laskun erittely" in text:
        return vattenfall
    if "Elenia Verkko Oyj" in text and "KULUTUSLASKU" in text:
        return elenia
    if "Elenia Verkko Oyj" in text and "verkkopalvelusopimuksen vahvistusilmoitus" in text.lower():
        return elenia_contract
    raise DocumentError("unsupported_document_layout")
