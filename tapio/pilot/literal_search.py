"""Explicit literal extraction, with no semantic synonyms or classification."""

import re

from tapio.pilot.transaction_search import (
    SearchPlan,
    normalize_text,
    requested_dates,
    search_intent,
)


def literal_plan(question):
    q = normalize_text(question)
    q = re.sub(r"\btranactions\b", "transactions", q)
    try:
        dates = requested_dates(question)
    except ValueError:
        return None
    # Strip only an explicit supported date suffix, never arbitrary qualifiers.
    if dates:
        import calendar

        month = calendar.month_name[dates.date_from.month].casefold()
        q = re.sub(r"(?: in| during| vuonna)? (?:" + month + r" )?20\d{2}$", "", q)

    patterns = (
        r"(?:kuinka paljon olen maksanut|mita maksuja olen tehnyt) (.+)",
        r"(.+?) maksut",
        r"maksut (.+)",
        r"(?:find|show|list)(?: me)? (?:all )?transactions "
        r"(?:containing|mentioning|matching|with) (.+)",
        r"(?:(?:find|show|list)(?: me)? )?(.+?) (?:transactions|payments|purchases)",
        r"(?:show|find)(?: me)? anything (?:mentioning|containing) (.+)",
        r"do i have anything (?:mentioning|containing) (.+)",
        r"search (?:the )?bank data for (.+)",
    )
    term = None
    for pattern in patterns:
        m = re.fullmatch(pattern, q)
        if m:
            term = m[1]
            break
    if (
        term is None
        and search_intent(question)
        and not re.search(r"\b(show|find|list|search|look)\b", q)
    ):
        term = q
    if term is None:
        return None
    term = re.sub(r" (?:lle|lla)$", "", term)
    # Do not accidentally turn a date/context qualifier into a literal or drop it.
    if re.search(r"\b(in|from|before|after|since|between|during|related|deduct\w*|tax)\b", term):
        return None
    if re.search(r"\b20\d{2}\b", term):
        return None
    try:
        return SearchPlan(intent="TRANSACTION_SEARCH", terms=[term], date_range=dates)
    except ValueError:
        return None
