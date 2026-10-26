"""Real pilot routing with deterministic local evidence fixtures, no provider calls."""

import pytest
from test_pilot import ask
from test_pilot_transaction_search import bank, factory, search_pilot  # noqa: F401

from tapio.pilot.concepts import catalog_query, concept_plan
from tapio.pilot.transaction_search import retrieve_search

QUERIES = [
    "pharmacy",
    "dentist",
    "car repair",
    "fuel",
    "insurance",
    "hardware/building supplies",
    "farmacia",
    "dentista",
    "taller",
    "gasolina",
    "seguro",
    "apteekki",
    "hammaslääkäri",
    "autohuolto",
    "polttoaine",
    "vakuutus",
    "Show pharmacy transactions",
    "Find pharmacy purchases",
    "Busca compras de farmacia",
    "Näytä apteekkiostokset",
]


@pytest.mark.parametrize("question", QUERIES)
def test_catalog_pilot_no_provider(question, tmp_path, bank):  # noqa: F811
    concept, language = catalog_query(question)
    expected = concept_plan(concept)
    pilot = search_pilot(tmp_path, loader=lambda p, _: retrieve_search(p, bank))

    def forbidden(*args):
        raise AssertionError("Catalog must not call a model")

    pilot.model_factory = forbidden
    response = ask(pilot, question)
    assert response.presentation_mode == "TRANSACTION_SEARCH"
    assert response.session.model_calls == 0
    assert response.optional_details["search"]["terms"] == expected.terms
    assert not response.suggestions and not response.human_review
    if not response.optional_details["transactions"]:
        assert response.evidence_states == ["SUPPORTED", "NO_MATCH"]
        assert {"en": "zero spending", "es": "gasto sea cero", "fi": "menoja olisi nolla"}[
            language
        ] in response.direct_answer
    for row in response.optional_details["transactions"]:
        assert row["matched_terms"][0]["provenance"]
        assert not any("suggested" in f for m in row["matched_terms"] for f in m["fields"])


@pytest.mark.parametrize(
    "question",
    [
        "Show pharmacy transactions before 2026",
        "pharmacy and fuel",
        "Are pharmacy purchases deductible?",
        "Show pharmacy transactions in Madrid",
        "Review fuel transactions",
    ],
)
def test_no_silent_qualifier_loss(question):
    assert catalog_query(question) is None


def test_label_only_authority():
    from tapio.pilot.search_display import prepare, summary

    evidence = {
        "searched_fields": ["confirmed_category"],
        "items": [
            {
                "amount": "-12.34",
                "currency": "EUR",
                "matched_terms": [{"term": "fuel", "fields": ["confirmed_category"]}],
            }
        ],
    }
    result = prepare(evidence)
    _, notes = summary(result["items"], "en")
    assert "1 rely entirely" in notes[0]
    assert "not merchant/source text" in notes[0]
    assert result["items"][0]["matched_terms"][0]["provenance"] == [
        {"field": "confirmed_category", "authority": "HUMAN_LABEL"}
    ]
    assert "12.34 EUR" in notes[1]
