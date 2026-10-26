"""Read-only search presentation metadata; no classification or suggestion actions."""

from copy import deepcopy
from decimal import Decimal

AUTHORITY = {
    "raw_description": "SOURCE_TEXT",
    "raw_source.Selitys": "SOURCE_TEXT",
    "raw_merchant": "SOURCE_TEXT",
    "recipient": "SOURCE_TEXT",
    "processor": "SOURCE_TEXT",
    "normalized_merchant": "CANONICAL_MERCHANT",
    "confirmed_category": "HUMAN_LABEL",
    "confirmed_context": "HUMAN_LABEL",
}

TEXT = {
    "en": {
        "found": "Found {n} matching imported transactions.",
        "none": (
            "No matching imported transactions were found for the searched terms. This "
            "does not establish zero spending. "
        ),
        "terms": "Search terms: ",
        "outflow": "Total matched outflow: ",
        "labels": (
            "{n} matches include human-confirmed labels; {only} rely entirely on those "
            "labels, not merchant/source text. "
        ),
        "coverage": (
            "Imported transactions do not establish complete statement coverage. "
            "Translation and text matches do not establish purpose or tax deductibility. "
        ),
        "unresolved": "UNRESOLVED",
        "matched": "Matched: ",
        "availability": (
            "{n} rows have unresolved or UNKNOWN category/context. Existing human-"
            "confirmed labels remain authoritative. "
        ),
    },
    "es": {
        "found": "Se encontraron {n} transacciones importadas coincidentes.",
        "none": (
            "No se encontraron transacciones importadas para los términos buscados. Esto "
            "no demuestra que el gasto sea cero. "
        ),
        "terms": "Términos buscados: ",
        "outflow": "Total de salidas coincidentes: ",
        "labels": (
            "{n} coincidencias incluyen etiquetas confirmadas por una persona; {only} "
            "dependen exclusivamente de ellas, no del texto del comercio o fuente. "
        ),
        "coverage": (
            "Las transacciones importadas no demuestran cobertura completa del extracto. "
            "La traducción y las coincidencias no establecen finalidad ni deducibilidad "
            "fiscal. "
        ),
        "unresolved": "SIN RESOLVER",
        "matched": "Coincidencia: ",
        "availability": (
            "{n} filas tienen categoría o contexto sin resolver o UNKNOWN. Las etiquetas "
            "humanas confirmadas siguen siendo autoritativas. "
        ),
    },
    "fi": {
        "found": "Löytyi {n} hakua vastaavaa tuotua tapahtumaa.",
        "none": (
            "Hakutermeillä ei löytynyt tuotuja tapahtumia. Tämä ei osoita, että menoja "
            "olisi nolla. "
        ),
        "terms": "Hakutermit: ",
        "outflow": "Vastaavien tapahtumien menot yhteensä: ",
        "labels": (
            "{n} osumaa sisältää ihmisen vahvistamia luokituksia; {only} perustuu "
            "yksinomaan niihin eikä kauppias- tai lähdetekstiin. "
        ),
        "coverage": (
            "Tuodut tapahtumat eivät osoita tiliotteiden täydellistä kattavuutta. "
            "Käännös tai tekstiosuma ei vahvista käyttötarkoitusta eikä "
            "verovähennyskelpoisuutta. "
        ),
        "unresolved": "SELVITTÄMÄTÖN",
        "matched": "Osuma: ",
        "availability": (
            "{n} rivin luokka tai konteksti on selvittämätön tai UNKNOWN. Ihmisen "
            "vahvistamat luokitukset ovat edelleen ensisijaisia. "
        ),
    },
}


def prepare(evidence):
    from tapio.pilot.transaction_search import normalize_text

    evidence = deepcopy(evidence)
    for row in evidence["items"]:
        matches = []
        for match in row["matched_terms"]:
            fields = [f for f in match["fields"] if f in AUTHORITY]
            if fields:
                matches.append(
                    {
                        **match,
                        "fields": fields,
                        "normalized_term": normalize_text(match["term"]),
                        "matching": "NORMALIZED_TOKEN_PHRASE_V1",
                        "provenance": [{"field": f, "authority": AUTHORITY[f]} for f in fields],
                    }
                )
        row["matched_terms"] = matches
    evidence["items"] = [r for r in evidence["items"] if r["matched_terms"]]
    evidence["searched_fields"] = [f for f in evidence["searched_fields"] if f in AUTHORITY]
    return evidence


def summary(rows, language):
    t = TEXT.get(language, TEXT["en"])
    label_rows = only = 0
    totals = {}
    for row in rows:
        authorities = {p["authority"] for m in row["matched_terms"] for p in m["provenance"]}
        label_rows += "HUMAN_LABEL" in authorities
        only += authorities == {"HUMAN_LABEL"}
        value = Decimal(row["amount"])
        if value < 0:
            totals[row["currency"]] = totals.get(row["currency"], Decimal(0)) - value
    notes = [t["labels"].format(n=label_rows, only=only)] if label_rows else []
    if totals:
        notes.append(t["outflow"] + "; ".join(f"{v:.2f} {c}" for c, v in sorted(totals.items())))
    return t, notes
