"""Human-transcribed export evidence checks; no extraction or tariff capability."""

from datetime import date
from typing import Literal

from pydantic import model_validator

from tapio.tools.schemas import Schema


class ExportFact(Schema):
    value: str | None
    status: Literal["CONFIRMED", "SUPPORTED_BY_ONE_SOURCE", "NOT_STATED", "AMBIGUOUS", "CONFLICT"]
    raw_excerpt: str | None = None
    page: int | None = None

    @model_validator(mode="after")
    def source_required(self):
        if self.status == "NOT_STATED" and (self.value is not None or self.raw_excerpt is not None):
            raise ValueError("unstated_is_not_zero_or_an_inferred_value")
        if self.status in ("CONFIRMED", "SUPPORTED_BY_ONE_SOURCE"):
            if self.value is None or not self.raw_excerpt or not self.page or self.page < 1:
                raise ValueError("accepted_fact_requires_page_and_literal_evidence")
        return self


def validate_excerpts(facts, pages):
    for fact in facts:
        if fact.raw_excerpt is not None:
            if (
                fact.page is None
                or fact.page > len(pages)
                or fact.raw_excerpt not in pages[fact.page - 1]
            ):
                raise ValueError("excerpt_not_in_source_page")
    return facts


def temporal_applicability(start, end, contract_type, year, continuation_confirmed=False):
    """Separate stated duration from evidence that conditional service actually continued."""
    start = date.fromisoformat(start)
    end = date.fromisoformat(end) if end else None
    overlaps = start <= date(year, 12, 31) and (end is None or end >= date(year, 1, 1))
    if not overlaps or (end is None and contract_type != "INDEFINITE"):
        return "NOT_ESTABLISHED"
    return "CONFIRMED_ACTIVE_PERIOD" if continuation_confirmed else "POSSIBLE_ACTIVE_PERIOD"
