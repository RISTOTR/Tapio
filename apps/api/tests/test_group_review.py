"""Effort planning and real atomic writes in an isolated migrated database."""

import pytest
from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Transaction
from apps.api.tests.test_persistent_review import factory as factory
from apps.api.tests.test_persistent_review import queue as queue
from apps.api.tests.test_user_rules import rule
from tapio.confirmation.grouping import analyze
from tapio.confirmation.groups import GroupReview
from tapio.confirmation.service import Commit, row_data


def card(i, entity="synthetic shop"):
    return {
        "card_id": str(i),
        "identity_key": entity,
        "transaction": {"id": str(i), "date": "2026-01-01", "amount": "-10"},
        "current_state": {"category": None, "context": None, "authority": {}},
        "suggestion": {"category": None, "context": None},
    }


def history(contexts=("PERSONAL",) * 3):
    return [
        {
            "identity_key": "synthetic shop",
            "transaction_id": "old" + str(i),
            "field": f,
            "value": value,
        }
        for i, context in enumerate(contexts)
        for f, value in (("category", "OTHER"), ("context", context))
    ]


def test_stable_exact_threshold_and_effort():
    cards = [card(i) for i in range(8)]
    assert not analyze(cards, history()[:4])["groups"]
    p = analyze(cards, history())
    assert len(p["groups"]) == 1
    assert p["groups"][0]["fields"] == {"category": "OTHER", "context": "PERSONAL"}
    assert p["summary"]["manual_actions_before"] == 32
    assert p["summary"]["manual_actions_after"] == 2
    assert p["summary"]["REPEATED_CONFIRMATION_AVOIDED"] == 7
    assert p["individual_ids"] == []


def test_category_conflict_blocks_and_context_conflict_is_field_specific():
    cards = [card(1), card(2)]
    h = history(("PERSONAL", "FORESTRY", "PERSONAL"))
    p = analyze(cards, h)
    assert p["groups"][0]["fields"] == {"category": "OTHER"}
    assert len(p["individual_ids"]) == 2
    h[0]["value"] = "TRAVEL"
    assert not analyze(cards, h)["groups"]


@pytest.mark.parametrize(
    "flag,value",
    [
        ("receipt_conflicts", ["conflict"]),
        ("user_rule_conflicts", ["category"]),
        ("document_evidence", [{"status": "CANDIDATE"}]),
    ],
)
def test_transaction_evidence_splits_out(flag, value):
    cards = [card(1), card(2), card(3)]
    cards[0][flag] = value
    p = analyze(cards, history())
    assert p["groups"][0]["card_ids"] == ["2", "3"]
    assert "1" in p["individual_ids"]


def test_multi_context_and_purpose_boundary():
    cards = [card(1), card(2), card(3)]
    for c in cards:
        c["multi_context"] = True
    cards[0]["suggestion"]["category"] = "TRAVEL"
    p = analyze(cards, history())
    assert p["groups"][0]["fields"] == {"category": "OTHER"}
    assert p["groups"][0]["card_ids"] == ["2", "3"]
    assert len(p["individual_ids"]) == 3


def test_novelty_budget_and_no_unsupported_duplicate_confirmation():
    cards = [card(i, "new" + str(i)) for i in range(15)] + [card(99)]
    p = analyze(cards, history())
    assert len(p["minimal_review_ids"]) == 10
    assert p["individual_ids"][-1] == "99"
    repeated = analyze([card(1), card(2)], [])
    assert repeated["groups"] == []
    assert repeated["cards"][0]["review_analysis"]["reason"] == "REPEATED_IDENTICAL_PATTERN"


@pytest.fixture
def grouped(queue):
    q = queue
    q.rules.root.mkdir()
    import json

    candidate = {
        "id": "rule",
        "rule": rule("Synthetic queue shop"),
        "support": [],
        "semantic_facts": [],
    }
    (q.rules.root / "candidates.json").write_text(json.dumps([candidate]))
    p = q.rules.preview(
        {
            "candidate_id": "rule",
            "action": "CONFIRM_RULE",
            "rule": candidate["rule"],
            "expected_state": "PENDING",
        },
        "test",
    )
    q.rules.commit(p["token"], "test")
    g = GroupReview(q)
    plan = g.build()
    assert len(plan["groups"]) == 1
    return g, plan


def test_group_preview_apply_individual_events_idempotency_and_correction(grouped):
    g, plan = grouped
    group = plan["groups"][0]
    with g.queue.factory() as db:
        before = [row_data(t) for t in db.scalars(select(Transaction).order_by(Transaction.id))]
    p = g.preview(plan["plan_id"], group["id"], "browser")
    assert p["persisted"] is False
    assert len(p["group"]["transaction_ids"]) == 35
    with g.queue.factory() as db:
        assert not list(db.scalars(select(ConfirmationRevision)))
    result = g.commit(plan["plan_id"], p["token"], "browser")
    assert len(result["results"]) == 35
    g.commit(plan["plan_id"], p["token"], "browser")
    with g.queue.factory() as db:
        revisions = list(db.scalars(select(ConfirmationRevision)))
        assert len(revisions) == 35
        assert len({r.knowledge_event["claims"][0]["subject"] for r in revisions}) == 35
        assert all(r.audit["group_confirmation"]["group_id"] == group["id"] for r in revisions)
        assert before == [
            row_data(t) for t in db.scalars(select(Transaction).order_by(Transaction.id))
        ]
    _, s = g.get(plan["plan_id"])
    cid = group["card_ids"][0]
    p = s.preview(
        {
            "card_id": cid,
            "action": "CHANGE",
            "fields": {"context": "PROPERTY"},
            "correction_reason": "Synthetic individual correction",
            "touched_fields": ["context"],
            "review_version": s.current_review(cid)["review_version"],
        },
        "browser",
    )
    g.individual_commit(
        plan["plan_id"],
        Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
        "browser",
    )
    assert s.current_review(cid)["context"]["value"] == "PROPERTY"
    assert s.current_review(group["card_ids"][1])["context"]["value"] == "PERSONAL"


def test_stale_member_rolls_back_whole_group(grouped):
    g, plan = grouped
    group = plan["groups"][0]
    p = g.preview(plan["plan_id"], group["id"], "browser")
    _, s = g.get(plan["plan_id"])
    cid = group["card_ids"][-1]
    one = s.preview({"card_id": cid, "action": "CONFIRM", "fields": group["fields"]}, "browser")
    s.commit(Commit(token=one["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser")
    with pytest.raises(ValueError, match="STALE"):
        g.commit(plan["plan_id"], p["token"], "browser")
    with g.queue.factory() as db:
        assert len(list(db.scalars(select(ConfirmationRevision)))) == 1


def test_disabled_wrong_session_and_changed_evidence_block(grouped, monkeypatch):
    g, plan = grouped
    p = g.preview(plan["plan_id"], plan["groups"][0]["id"], "browser")
    with pytest.raises(ValueError, match="INVALID"):
        g.commit(plan["plan_id"], p["token"], "other")
    _, s = g.get(plan["plan_id"])
    monkeypatch.setattr(s, "enabled", lambda: False)
    with pytest.raises(ValueError, match="DISABLED"):
        g.commit(plan["plan_id"], p["token"], "browser")
    monkeypatch.setattr(g, "versions", lambda: {"changed": True})
    with pytest.raises(ValueError, match="STALE"):
        g.commit(plan["plan_id"], p["token"], "browser")


def test_skips_do_not_write_labels(grouped):
    g, plan = grouped
    g.skip(plan["plan_id"], plan["groups"][0]["id"])
    with g.queue.factory() as db:
        assert not list(db.scalars(select(ConfirmationRevision)))
