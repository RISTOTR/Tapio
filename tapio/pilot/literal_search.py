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
    patterns = (
        r"(?:find|show|list)(?: me)? (?:all )?transactions (?:containing|mentioning|matching) (.+)",
        r"(?:find|show|list)(?: me)? (.+?) (?:transactions|payments|purchases)",
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
    # Do not accidentally turn a date/context qualifier into a literal or drop it.
    if re.search(r"\b(in|from|before|after|since|between|during|related|deduct\w*|tax)\b", term):
        return None
    if re.search(r"\b20\d{2}\b", term):
        return None
    try:
        return SearchPlan(
            intent="TRANSACTION_SEARCH", terms=[term], date_range=requested_dates(question)
        )
    except ValueError:
        return None
