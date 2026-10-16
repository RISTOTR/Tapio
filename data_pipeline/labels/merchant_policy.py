"""Prospective review routing only; never a category, context or tax decision."""

import re

AMBIGUOUS_REASON = "AMBIGUOUS_MULTI_CONTEXT_MERCHANT"


def ambiguous_merchant(name):
    return bool(re.search(r"\b(tokmanni|k[\s-]*rauta|oikea\s+konekauppa)\b", name or "", re.I))
