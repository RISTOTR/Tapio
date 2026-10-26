"""Centralized explicit multilingual catalog; translation never assigns labels."""

from tapio.pilot.transaction_search import SearchPlan, normalize_text

CATALOG_VERSION = "EXPLICIT_EN_ES_FI_V1"
CONCEPTS = {
    "pharmacy": ("pharmacy", "apteekki", "farmacia"),
    "dentist": ("dentist", "dental", "dentista", "hammaslääkäri", "hammashoito", "odontologia"),
    "car repair": (
        "car repair",
        "autokorjaamo",
        "autohuolto",
        "korjaamo",
        "taller",
        "taller mecanico",
    ),
    "fuel": ("fuel", "polttoaine", "gasolina", "diesel", "bensiini"),
    "insurance": ("insurance", "vakuutus", "seguro", "seguros", "vakuutukset"),
    "hardware/building supplies": (
        "hardware",
        "building supplies",
        "rautakauppa",
        "rakennustarvikkeet",
        "ferreteria",
        "materiales de construccion",
        "hardware/building supplies",
    ),
}


def concept_plan(concept, date_range=None):
    """Exact catalog lookup only. Unknown concepts fail visibly, never guess labels."""
    key = normalize_text(concept)
    for terms in CONCEPTS.values():
        if key in {normalize_text(t) for t in terms}:
            return SearchPlan(intent="TRANSACTION_SEARCH", terms=list(terms), date_range=date_range)
    raise ValueError("UNSUPPORTED_EXPLICIT_CONCEPT")


# Explicit query grammar, separate from evidence search terms.
PREFIXES = {
    "en": ("show", "find", "list", "search", "show me"),
    "es": ("busca", "buscar", "muestra", "mostrar"),
    "fi": ("nayta", "etsi", "hae"),
}
QUERY_WORDS = {
    "transactions",
    "transaction",
    "purchases",
    "payments",
    "me",
    "all",
    "the",
    "related",
    "to",
    "of",
    "in",
    "compras",
    "transacciones",
    "pagos",
    "de",
    "las",
    "los",
    "ostokset",
    "tapahtumat",
    "maksut",
}
SPANISH = {"farmacia", "dentista", "taller", "gasolina", "seguro", "seguros"}
FINNISH = {"apteekki", "hammaslaakari", "autohuolto", "polttoaine", "vakuutus"}


def catalog_query(question):
    """Recognize bounded search requests, never discard unknown qualifiers or intents."""
    import re

    q = normalize_text(question)
    # Only this explicit Finnish compound is an input alias, not an evidence term.
    q = q.replace("apteekkiostokset", "apteekki ostokset")
    language = "en"
    for lang, prefixes in PREFIXES.items():
        if any(q.startswith(p + " ") for p in prefixes):
            language = lang
    if q in SPANISH:
        language = "es"
    elif q in FINNISH:
        language = "fi"
    hits = []
    for concept, terms in CONCEPTS.items():
        remainder = " " + q + " "
        found = False
        for term in sorted(terms, key=len, reverse=True):
            token = " " + normalize_text(term) + " "
            if token in remainder:
                found = True
                remainder = remainder.replace(token, " ")
        if not found:
            continue
        allowed = QUERY_WORDS | {w for ps in PREFIXES.values() for p in ps for w in p.split()}
        words = remainder.split()
        if all(w in allowed or re.fullmatch(r"20\d{2}", w) for w in words):
            hits.append((concept, language))
    return hits[0] if len(hits) == 1 else None
