"""Suggestion authority and feedback isolation using synthetic sources only."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tapio.knowledge.backfill import accrue
from tapio.knowledge.models import Claim, KnowledgeEvent, Provenance, canonical
from tapio.knowledge.store import rebuild
from tapio.suggestions.generate import Generator
from tapio.suggestions.models import Card, EvidenceInput, FeedbackInput, Suggestion
from tapio.suggestions.store import Store

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def tx(i, merchant="Dental Example"):
    return dict(
        id=str(i),
        normalized_counterparty=merchant,
        raw_counterparty=merchant,
        booking_date="2025-01-01",
        amount="-588.07",
        currency="EUR",
        message="",
    )


def review(i, category="OTHER", context="PERSONAL"):
    return dict(
        id="r" + str(i),
        transaction_id=str(i),
        review_status="REVIEWED",
        confirmed_category=category,
        confirmed_business_context=context,
        review_file_sha256="a" * 64,
    )


def generator(txs=None, reviews=None, extra=()):
    txs = txs or [tx(1), tx(2), tx(3)]
    reviews = [review(1)] if reviews is None else reviews
    events = accrue({"transactions": txs, "transaction_label_reviews": reviews}, observed_at=NOW)
    return Generator(rebuild(events + list(extra)), txs, reviews, NOW)


def card(g, i="2"):
    t = g.txs[i]
    return g.card(t, g.signals(t))


def test_authority_and_provenance():
    g = generator()
    before = canonical(g.snapshot)
    c = card(g)
    assert c.suggestion == Suggestion(category="OTHER", context="PERSONAL")
    assert all(e.provenance for e in c.evidence)
    assert any(e.authority == "HUMAN_CONFIRMED" for e in c.evidence)
    assert canonical(g.snapshot) == before
    assert "Tax treatment remains a separate human decision." in " ".join(c.warnings)
    with pytest.raises(ValidationError):
        Suggestion(authority="HUMAN_CONFIRMED")
    with pytest.raises(ValidationError):
        EvidenceInput(id="x", authority="UNKNOWN", summary="x", provenance=())


@pytest.mark.parametrize("merchant", ["K-Rauta", "Tokmanni", "Oikea Konekauppa"])
def test_multi_context_policy(merchant):
    g = generator([tx(1, merchant), tx(2, merchant)], [review(1, context="FORESTRY")])
    c = card(g)
    assert c.suggestion.context is None
    assert c.suggestion.category == "OTHER"
    assert c.priority == "AMBIGUOUS_REVIEW"
    assert "MULTI_CONTEXT_MERCHANT" in {r.code for r in c.reasons}
    with pytest.raises(ValueError, match="INELIGIBLE"):
        card(g, "1")


def test_independent_category_with_conflicting_context():
    g = generator(reviews=[review(1, "FUEL", "PERSONAL"), review(3, "FUEL", "PROPERTY")])
    c = card(g)
    assert c.suggestion.category == "FUEL" and c.suggestion.context is None
    assert c.conflicting_knowledge and c.priority == "AMBIGUOUS_REVIEW"


def test_independent_context_with_conflicting_category():
    c = card(generator(reviews=[review(1, "FUEL"), review(3, "OTHER")]))
    assert c.suggestion.category is None and c.suggestion.context == "PERSONAL"


def test_partial_human_review_preserved():
    c = card(generator(reviews=[review(1), review(2, "FUEL", "UNKNOWN")]))
    assert c.current_state.category == "FUEL" and c.suggestion.category is None
    assert c.suggestion.context == "PERSONAL"
    d = c.model_dump()
    d["suggestion"]["category"] = "OTHER"
    with pytest.raises(ValidationError, match="AUTHORITATIVE"):
        Card.model_validate(d)


def test_588_ambiguity_never_shortcuts_labels():
    p = Provenance(
        source_type="synthetic",
        source_id="reversal",
        source_hash="b" * 64,
        originating_field="relationship",
        observed_at=NOW,
        extraction_method="test",
    )
    c = Claim(
        kind="RELATIONSHIP",
        subject="2",
        predicate="possible_reversal",
        value="3",
        authority="SUGGESTED",
        relationship_status="AMBIGUOUS",
        provenance=p,
    )
    g = generator(extra=[KnowledgeEvent(event_type="SOURCE_PARSED", claims=(c,))])
    before = canonical(g.snapshot)
    result = card(g)
    assert result.suggestion == Suggestion()
    assert "RECONCILIATION_LINK" in {r.code for r in result.reasons}
    assert canonical(g.snapshot) == before


def sample():
    txs = [tx(1), tx(2), tx(3, "K-Rauta")] + [tx(i, "Unknown " + str(i)) for i in range(4, 23)]
    return generator(txs).sample()


def test_sample_bounded_diverse_deterministic():
    a = sample()
    assert len(a) == 16 and a == sample()
    tags = {t for c in a for t in c.selection_tags}
    assert {
        "MULTI_CONTEXT_MERCHANT",
        "RECURRING_PATTERN",
        "UNKNOWN_PURPOSE",
        "CONSISTENT_REVIEWED_HISTORY",
    } <= tags
    assert len({c.transaction.merchant for c in a}) >= 14
    with pytest.raises(ValueError):
        generator().sample(100)


def test_feedback_is_separate_latest_metrics_and_private(tmp_path):
    cards = sample()
    store = Store(tmp_path)
    store.save_batch(cards, {"source": "unchanged"})
    original = (tmp_path / "batch.json").read_bytes()
    assert store.metrics()["cards_reviewed"] == 0
    store.feedback(cards[0].card_id, FeedbackInput(choice="WRONG", note="Needs receipt"))
    store.feedback(cards[0].card_id, FeedbackInput(choice="PARTIALLY_USEFUL"))
    store.feedback(cards[1].card_id, FeedbackInput(choice="SKIP"))
    assert (tmp_path / "batch.json").read_bytes() == original
    assert len(list((tmp_path / "feedback").glob("*.json"))) == 3
    m = store.metrics()
    assert m["cards_reviewed"] == 2
    assert m["feedback_counts"]["WRONG"] == 0 and m["feedback_counts"]["PARTIALLY_USEFUL"] == 1
    assert all(m["by_dimension"].values())
    public = store.public_batch()
    assert "id" not in public[0]["transaction"] and "knowledge_used" not in public[0]
    assert "provenance" not in json.dumps(public)
    for path in (tmp_path / "feedback").glob("*.json"):
        record = json.loads(path.read_text())
        assert record["suggestion_snapshot"]["authority"] == "SUGGESTED"
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(KeyError):
        store.feedback("missing", FeedbackInput(choice="CORRECT"))


def test_feedback_api_has_no_label_mutation(tmp_path, monkeypatch):
    from tapio.pilot import api

    store = Store(tmp_path)
    cards = sample()
    store.save_batch(cards, {})
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    monkeypatch.setattr(api, "get_suggestion_store", lambda: store)
    client = TestClient(api.app)
    assert client.get("/pilot/suggestions").status_code == 200
    assert len(client.get("/pilot/suggestions/cards").json()) == 16
    url = f"/pilot/suggestions/cards/{cards[0].card_id}/feedback"
    assert client.post(url, json={"choice": "CONFIRM"}).status_code == 422
    assert client.post(url, json={"choice": "CORRECT", "category": "FORESTRY"}).status_code == 422
    assert client.post(url, json={"choice": "CORRECT", "note": "x" * 1001}).status_code == 422
    result = client.post(url, json={"choice": "CORRECT"}).json()
    assert result["saved"] and not result["labels_changed"]
    assert not result["knowledge_authority_changed"] and not result["source_data_changed"]
    assert client.patch(url, json={"category": "FORESTRY"}).status_code == 405
    assert (
        client.post(
            url, json={"choice": "SKIP"}, headers={"origin": "https://evil.invalid"}
        ).status_code
        == 403
    )


def test_consistent_history_priority_and_source_immutability():
    g = generator(reviews=[review(1), review(3)])
    before = canonical(
        {
            "transactions": g.txs,
            "reviews": g.reviews,
            "knowledge": g.snapshot.model_dump(mode="json"),
        }
    )
    c = card(g)
    assert c.priority == "HIGH_REVIEW_VALUE"
    assert c.suggestion == Suggestion(category="OTHER", context="PERSONAL")
    assert (
        canonical(
            {
                "transactions": g.txs,
                "reviews": g.reviews,
                "knowledge": g.snapshot.model_dump(mode="json"),
            }
        )
        == before
    )


def test_missing_reason_provenance_rejected():
    data = card(generator()).model_dump()
    data["reasons"][0]["evidence_refs"] = ("nonexistent",)
    with pytest.raises(ValidationError, match="REASON_WITHOUT_EVIDENCE"):
        Card.model_validate(data)


def test_document_candidate_never_promotes_recommendations():
    p = Provenance(
        source_type="synthetic",
        source_id="invoice",
        source_hash="b" * 64,
        originating_field="allocation",
        observed_at=NOW,
        extraction_method="test",
    )
    c = Claim(
        kind="RELATIONSHIP",
        subject="invoice",
        predicate="bank_allocation",
        value={"transaction_id": "2"},
        authority="SUGGESTED",
        relationship_status="CANDIDATE",
        provenance=p,
    )
    g = generator(extra=[KnowledgeEvent(event_type="SOURCE_PARSED", claims=(c,))])
    result = card(g)
    assert result.suggestion == Suggestion()
    assert result.priority == "AMBIGUOUS_REVIEW"
    assert "RELATED_DOCUMENT_FOUND" in {r.code for r in result.reasons}
