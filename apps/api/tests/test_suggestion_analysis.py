"""Synthetic feedback analysis and non-writing confirmation design contracts."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.api.tests.test_suggestion_cards import card, generator, sample
from tapio.knowledge.models import canonical, digest
from tapio.suggestions.analysis import analyze, content, load_feedback, note_themes, safety_findings
from tapio.suggestions.confirmation_design import ReviewChoice, preview
from tapio.suggestions.models import FeedbackInput, Suggestion
from tapio.suggestions.store import Store


def test_counts_unanswered_latest_and_integrity(tmp_path):
    s = Store(tmp_path)
    cards = sample()
    s.save_batch(cards, {})
    before = (tmp_path / "batch.json").read_bytes()
    s.feedback(cards[0].card_id, FeedbackInput(choice="WRONG"))
    s.feedback(cards[0].card_id, FeedbackInput(choice="CORRECT"))
    s.feedback(cards[1].card_id, FeedbackInput(choice="INSUFFICIENT_EVIDENCE"))
    c, f, audit = load_feedback(s)
    result = analyze(c, f, generator().snapshot)
    assert audit["saved_records"] == 3
    assert result["totals"]["reviewed"] == 2 and result["totals"]["unanswered"] == 14
    assert result["totals"]["WRONG"] == 0 and result["totals"]["CORRECT"] == 1
    assert (tmp_path / "batch.json").read_bytes() == before
    assert result["decision"] == "SUGGESTION_RULES_NEED_REVIEW"


def test_suggestion_abstention_reason_priority_and_safe_notes():
    g = generator()
    yes = card(g)
    no = yes.model_copy(update={"card_id": "abstention", "suggestion": Suggestion()})
    f = {
        yes.card_id: {"choice": "CORRECT", "note": "Private text insurance"},
        no.card_id: {"choice": "INSUFFICIENT_EVIDENCE", "note": ""},
    }
    result = analyze([yes, no], f, g.snapshot)
    assert result["positive_suggestions"]["CORRECT"] == 1
    assert result["abstentions"]["INSUFFICIENT_EVIDENCE"] == 1
    assert result["by_content"]["CONTEXT_ONLY"]["total"] == 0
    assert result["by_reason"]["EXACT_MERCHANT_IDENTITY"]["reviewed"] == 2
    assert result["by_priority"][yes.priority]["reviewed"] == 2
    assert result["note_themes"] == {"MERCHANT_TYPE_INSURANCE": 1}
    assert "Private text" not in canonical(result)
    assert note_themes("") == []
    assert note_themes("unmapped private note") == ["OTHER_NOTE_REQUIRES_MANUAL_READING"]


@pytest.mark.parametrize(
    "category,context,expected",
    [
        ("FUEL", None, "CATEGORY_ONLY"),
        (None, "PROPERTY", "CONTEXT_ONLY"),
        ("FUEL", "PERSONAL", "CATEGORY_AND_CONTEXT"),
        (None, None, "ABSTENTION"),
    ],
)
def test_independent_content_groups(category, context, expected):
    c = card(generator()).model_copy(
        update={"suggestion": Suggestion(category=category, context=context)}
    )
    assert content(c) == expected


def test_tampered_feedback_snapshot_rejected(tmp_path):
    s = Store(tmp_path)
    cards = sample()
    s.save_batch(cards, {})
    s.feedback(cards[0].card_id, FeedbackInput(choice="CORRECT"))
    p = next((tmp_path / "feedback").glob("*.json"))
    data = json.loads(p.read_text())
    data["suggestion_snapshot"]["context"] = "FORESTRY"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="SNAPSHOT_MISMATCH"):
        load_feedback(s)


def test_unsafe_context_and_unsupported_label_block_readiness():
    g = generator()
    c = card(g)
    bad = c.model_copy(
        update={
            "transaction": c.transaction.model_copy(update={"merchant": "K-Rauta"}),
            "suggestion": Suggestion(category="FUEL", context="FORESTRY"),
        }
    )
    codes = {f["code"] for f in safety_findings([bad], g.snapshot)}
    assert "MULTI_CONTEXT_IDENTITY_SUGGESTION" in codes
    assert "UNSUPPORTED_OR_CONFLICTING_LABEL" in codes
    r = analyze([bad], {bad.card_id: {"choice": "CORRECT", "note": ""}}, g.snapshot)
    assert r["decision"] == "SUGGESTION_RULES_NEED_REVIEW"


def choice(c, action="CONFIRM", fields=None, previous=None, reason=None):
    current = {"category": "UNKNOWN", "context": "UNKNOWN"}
    return current, ReviewChoice(
        action=action,
        fields={"category": "OTHER"} if fields is None else fields,
        expected_state_hash=digest(
            {"transaction_id": c.transaction.id, "current": current, "previous_review_id": previous}
        ),
        user_timestamp=datetime(2026, 10, 27, tzinfo=UTC),
        correction_reason=reason,
    )


@pytest.mark.parametrize(
    "action,fields",
    [
        ("CONFIRM", {"category": "OTHER"}),
        ("CONFIRM", {"context": "PERSONAL"}),
        ("CONFIRM", {"category": "OTHER", "context": "PERSONAL"}),
        ("CHANGE", {"category": "FUEL", "context": "PROPERTY"}),
        ("SKIP", {}),
    ],
)
def test_preview_actions_independent_fields_and_no_mutation(action, fields):
    g = generator()
    c = card(g)
    current, request = choice(c, action, fields)
    before = canonical(
        {
            "card": c.model_dump(mode="json"),
            "knowledge": g.snapshot.model_dump(mode="json"),
            "current": current,
        }
    )
    p = preview(c, current, request)
    assert not p["writes_enabled"] and not p["persisted"] and p["mode"] == "DRY_RUN"
    assert set(p["changes"]) == set(fields)
    assert p["audit_preview"]["suggestion_snapshot"]["authority"] == "SUGGESTED"
    if fields:
        assert p["event_preview"]["preview_only"]
        assert p["event_preview"]["event_type"] == "HUMAN_REVIEW_CONFIRMED"
        assert not p["event_preview"]["merchant_rule_created"]
    else:
        assert p["event_preview"] is None
    assert (
        canonical(
            {
                "card": c.model_dump(mode="json"),
                "knowledge": g.snapshot.model_dump(mode="json"),
                "current": current,
            }
        )
        == before
    )


def test_correction_retains_history_and_requires_reason():
    c = card(generator())
    current, request = choice(c, "CHANGE", {"context": "PROPERTY"}, "prior-review")
    with pytest.raises(ValueError, match="CORRECTION_REASON"):
        preview(c, current, request, previous_review_id="prior-review")
    request = request.model_copy(update={"correction_reason": "Explicit human correction"})
    p = preview(c, current, request, previous_review_id="prior-review")
    assert p["audit_preview"]["supersedes_review_id"] == "prior-review"
    assert p["audit_preview"]["old_values"]["context"] == "UNKNOWN"
    assert p["audit_preview"]["new_values"]["context"] == "PROPERTY"


def test_multi_context_and_conflict_cannot_confirm_abstention():
    c = card(generator()).model_copy(update={"suggestion": Suggestion()})
    current, request = choice(c, fields={"context": "FORESTRY"})
    with pytest.raises(ValueError, match="CONFIRM_ONLY"):
        preview(c, current, request)
    p = preview(c, current, request.model_copy(update={"action": "CHANGE"}))
    assert not p["event_preview"]["merchant_rule_created"]


def test_stale_state_and_invalid_values_rejected():
    c = card(generator())
    current, request = choice(c)
    with pytest.raises(ValueError, match="STALE"):
        preview(c, {**current, "context": "PROPERTY"}, request)
    with pytest.raises(ValidationError):
        choice(c, fields={"context": "MIXED"})
    with pytest.raises(ValidationError):
        choice(c, "SKIP", {"category": "OTHER"})


def test_ready_design_gate_and_wrong_requires_review():
    from apps.api.tests.test_suggestion_cards import review

    g = generator(reviews=[review(1), review(3)])
    c = card(g)
    assert (
        analyze([c], {c.card_id: {"choice": "CORRECT", "note": ""}}, g.snapshot)["decision"]
        == "READY_FOR_CONTROLLED_CONFIRMATION_WORKFLOW"
    )
    assert (
        analyze([c], {c.card_id: {"choice": "WRONG", "note": ""}}, g.snapshot)["decision"]
        == "SUGGESTION_RULES_NEED_REVIEW"
    )


@pytest.mark.parametrize("multi", [True, False])
def test_real_policy_and_conflicting_history_design_fixtures(multi):
    from apps.api.tests.test_suggestion_cards import review, tx

    merchant = "Tokmanni" if multi else "Synthetic merchant"
    rows = [tx(i, merchant) for i in (1, 2, 3)]
    reviews = [review(1, context="PERSONAL")]
    if not multi:
        reviews.append(review(3, context="PROPERTY"))
    c = card(generator(rows, reviews))
    assert c.suggestion.context is None
    current, request = choice(c, fields={"context": "PROPERTY"})
    with pytest.raises(ValueError, match="CONFIRM_ONLY"):
        preview(c, current, request)
    changed = preview(c, current, request.model_copy(update={"action": "CHANGE"}))
    assert changed["changes"]["context"]["new"] == "PROPERTY"
    assert not changed["event_preview"]["merchant_rule_created"]
    assert not changed["persisted"]
