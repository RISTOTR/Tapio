"""Inspected Finnish semicolon bank export: lossless source strings only."""

from io import StringIO

import polars as pl

SOURCE_TYPE = "finnish_bank_archive_csv"
PARSER_VERSION = "1.0.0"
HEADERS = [
    "Kirjauspäivä",
    "Arvopäivä",
    "Määrä EUROA",
    "Laji",
    "Selitys",
    "Saaja/Maksaja",
    "Saajan tilinumero",
    "Saajan pankin BIC",
    "Viite",
    "Viesti",
    "Arkistointitunnus",
]


class BankInputError(ValueError):
    """Sanitized stable error code; never include source contents."""


def parse_bank_csv(raw: bytes) -> pl.DataFrame:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
        frame = pl.read_csv(
            StringIO(text),
            separator=";",
            infer_schema=False,
            empty_string_is_null=False,
            truncate_ragged_lines=False,
        )
    except (UnicodeError, pl.exceptions.PolarsError):
        raise BankInputError("invalid_utf8_or_csv") from None
    if frame.columns != HEADERS:
        raise BankInputError("unsupported_bank_headers")
    if frame.is_empty():
        raise BankInputError("empty_source")
    if frame.null_count().sum_horizontal()[0]:
        raise BankInputError("incomplete_source_row")
    return frame
