"""Offline lexical expansion and pre-retrieval label ablation regressions."""

import pytest
from test_pilot_transaction_search import bank, factory, plan  # noqa: F401

from tapio.experiments.multilingual import CONCEPTS, concept_plan
from tapio.pilot.transaction_search import matching_terms, retrieve_search


@pytest.mark.parametrize("terms", CONCEPTS.values())
def test_languages_have_identical_visible_expansion(terms):
    for term in terms:
        assert concept_plan(term).terms == list(terms)
    assert len(terms) <= 10


def test_unknown_concept_is_not_guessed():
    with pytest.raises(ValueError, match="UNSUPPORTED_EXPLICIT_CONCEPT"):
        concept_plan("medical anything")


def test_normalization_preserves_provenance():
    assert matching_terms({"raw_merchant": "HAMMASLÄÄKÄRI"}, concept_plan("dentista").terms) == [
        {"term": "hammaslääkäri", "fields": ["raw_merchant"]}
    ]
    assert not matching_terms({"raw_merchant": "Superapteekki"}, ["apteekki"])


def test_hidden_labels_before_matching(bank):  # noqa: F811
    session_factory = bank
    visible = retrieve_search(plan(["dental"]), session_factory)
    hidden = retrieve_search(plan(["dental"]), session_factory, hide_labels=True)
    assert [(r["id"], r["amount"]) for r in visible["items"]] == [
        (r["id"], r["amount"]) for r in hidden["items"]
    ]
    assert all(r["category"] is None and r["business_context"] is None for r in hidden["items"])
    assert all(r["review_status"] == "UNREVIEWED" for r in hidden["items"])
    assert not retrieve_search(
        plan(["PROPERTY", "FORESTRY", "TAX"]), session_factory, hide_labels=True
    )["items"]
    assert retrieve_search(plan(["PROPERTY"]), session_factory)["items"]
    assert retrieve_search(plan(["dental"]), session_factory) == visible


def test_hidden_presentation_cannot_restore_labels(bank):  # noqa: F811
    from tapio.pilot.contracts import Session
    from tapio.pilot.transaction_search import search_response

    evidence = retrieve_search(plan(["dental"]), bank, hide_labels=True)
    session = Session(
        id="offline",
        timestamp="offline",
        model_calls=0,
        rounds=0,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        latency_seconds=0,
        estimated_cost_usd="0",
    )
    response = search_response(evidence, session)
    assert "Offline label ablation" in response.coverage_note
    assert "MAINTENANCE" not in response.model_dump_json()
    assert "PROPERTY" not in response.model_dump_json()
    assert "HUMAN_REVIEW_REQUIRED" in response.evidence_states
    assert all(r["category"] is None for r in response.optional_details["transactions"])
