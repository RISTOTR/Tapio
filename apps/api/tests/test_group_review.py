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
from tapio.knowledge.models import digest


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
    assert len(p["minimal_review_ids"]) == 5
    assert "99" not in p["individual_ids"]
    assert p["groups"][0]["card_ids"] == ["99"]
    repeated = analyze([card(1), card(2)], [])
    assert repeated["groups"] == []
    assert repeated["cards"][0]["review_analysis"]["reason"] == "REPEATED_IDENTICAL_PATTERN"


@pytest.fixture
def grouped(queue):
    q = queue
    # Three members suffice for rollback, idempotency and per-transaction provenance.
    with q.factory.begin() as db:
        rows = list(db.scalars(select(Transaction).order_by(Transaction.id)))
        for row in rows[3:]:
            db.delete(row)
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
    assert len(p["group"]["transaction_ids"]) == 3
    with g.queue.factory() as db:
        assert not list(db.scalars(select(ConfirmationRevision)))
    result = g.commit(plan["plan_id"], p["token"], "browser")
    assert len(result["results"]) == 3
    g.commit(plan["plan_id"], p["token"], "browser")
    with g.queue.factory() as db:
        revisions = list(db.scalars(select(ConfirmationRevision)))
        assert len(revisions) == 3
        assert len({r.knowledge_event["claims"][0]["subject"] for r in revisions}) == 3
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


def test_category_only_group_write_preserves_unresolved_context(grouped):
    g, plan = grouped
    group = plan["groups"][0]
    group["fields"] = {"category": "OTHER"}
    p = g.preview(plan["plan_id"], group["id"], "browser")
    g.commit(plan["plan_id"], p["token"], "browser")
    with g.queue.factory() as db:
        rows = list(db.scalars(select(ConfirmationRevision)))
        assert len(rows) == 3
        assert all(r.fields == {"category": "OTHER"} for r in rows)
        assert all(r.state["context"] is None for r in rows)
        assert all(r.state["authority"]["context"] == "UNKNOWN" for r in rows)


def test_persisted_plan_survives_restart_and_detects_tampering(grouped):
    import json

    g, plan = grouped
    restarted = GroupReview(g.queue)
    restored, _ = restarted.get(plan["plan_id"])
    assert digest(restored) == digest(plan)
    p = restarted.preview(plan["plan_id"], plan["groups"][0]["id"], "browser")
    # The same snapshot/key keeps a second read from invalidating an open preview.
    g.build()
    g.commit(plan["plan_id"], p["token"], "browser")
    latest = GroupReview(g.queue)
    _, s = latest.get(plan["plan_id"])
    assert s.current_review(plan["groups"][0]["card_ids"][0])["context"]["value"] == "PERSONAL"
    path = g.queue.root / "minimal_review/plans" / (plan["plan_id"] + ".json")
    data = json.loads(path.read_text())
    data["data"]["plan"]["groups"][0]["fields"]["context"] = "FORESTRY"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="INTEGRITY"):
        GroupReview(g.queue).get(plan["plan_id"])


def test_group_routes_require_same_origin_browser_and_explicit_apply(grouped, monkeypatch):
    from fastapi.testclient import TestClient

    from tapio.confirmation import api
    from tapio.pilot.api import app

    g, plan = grouped
    monkeypatch.setattr(api, "group_review", lambda: g)
    monkeypatch.setattr(api, "persistent_queue", lambda: g.queue)
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    client = TestClient(app)
    result = client.get("/pilot/confirmation/groups/cards?plan_id=" + plan["plan_id"])
    assert result.status_code == 200
    body = {"plan_id": plan["plan_id"], "group_id": plan["groups"][0]["id"]}
    assert client.post("/pilot/confirmation/groups/preview", json=body).status_code == 403
    headers = {"X-Tapio-CSRF": result.json()["csrf"], "Origin": "http://testserver"}
    p = client.post("/pilot/confirmation/groups/preview", json=body, headers=headers)
    assert p.status_code == 200
    commit = {"plan_id": plan["plan_id"], "token": p.json()["token"]}
    assert (
        client.post("/pilot/confirmation/groups/commit", json=commit, headers=headers).status_code
        == 422
    )
    commit["explicit_click"] = "APPLY_DISPLAYED_GROUP"
    assert (
        client.post("/pilot/confirmation/groups/commit", json=commit, headers=headers).status_code
        == 200
    )


def test_semantic_category_group_and_pending_concept_not_used():
    cards = [card(1, "new cafe"), card(2, "other cafe")]
    for c in cards:
        c["semantic_category_used"] = True
        c["semantic_concepts"] = [
            {"confirmation_id": "confirmed", "category_mapping": {"category": "OTHER"}}
        ]
        c["suggestion"]["category"] = "OTHER"
    p = analyze(cards, [])
    assert p["groups"][0]["fields"] == {"category": "OTHER"}
    assert len(p["individual_ids"]) == 2
    for c in cards:
        c["semantic_category_used"] = False
    assert not analyze(cards, [])["groups"]


def test_saved_plan_rebuilds_after_reuse_change(grouped, monkeypatch):
    import hashlib
    import hmac
    import json

    from fastapi.testclient import TestClient

    from tapio.confirmation import api
    from tapio.pilot.api import app

    g, plan = grouped
    monkeypatch.setattr(api, "group_review", lambda: g)
    monkeypatch.setattr(api, "persistent_queue", lambda: g.queue)
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    data = {"entities": [], "vocabulary": [], "version": "new-reviewed-links"}
    signature = hmac.new(
        (g.queue.root / "queue.key").read_bytes(), digest(data).encode(), hashlib.sha256
    ).hexdigest()
    (g.queue.root / "reuse.json").write_text(json.dumps({"data": data, "signature": signature}))
    response = TestClient(app).get("/pilot/confirmation/groups/cards?plan_id=" + plan["plan_id"])
    assert response.status_code == 200
    assert response.json()["plan_id"] != plan["plan_id"]
    with pytest.raises(ValueError, match="STALE"):
        g.preview(plan["plan_id"], plan["groups"][0]["id"], "browser")


def test_supported_single_confirmation_writes_one_audit_event(grouped):
    g, _ = grouped
    with g.queue.factory.begin() as db:
        rows = list(db.scalars(select(Transaction).order_by(Transaction.id)))
        for row in rows[1:]:
            db.delete(row)
    plan = g.build()
    assert plan["individual_ids"] == []
    assert plan["summary"]["known_single_confirmations"] == 1
    preview = g.preview(plan["plan_id"], plan["groups"][0]["id"], "browser")
    result = g.commit(plan["plan_id"], preview["token"], "browser")
    assert len(result["results"]) == 1
    with g.queue.factory() as db:
        revisions = list(db.scalars(select(ConfirmationRevision)))
    assert len(revisions) == 1
    assert revisions[0].audit["group_confirmation"]["REPEATED_CONFIRMATION_AVOIDED"] == 0


def test_real_group_browser_preview_apply_reload(grouped):
    import os
    import subprocess
    from pathlib import Path

    if not Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists():
        pytest.skip("Real Chromium required")
    g, plan = grouped
    result = subprocess.run(
        ["node", "apps/api/tests/js/group_browser.cjs"],
        env={
            **os.environ,
            "BROWSER_TEST_DATABASE_URL": g.queue.factory.kw["bind"].url.render_as_string(
                hide_password=False
            ),
            "GROUP_TEST_ROOT": str(g.queue.root),
            "GROUP_TEST_PLAN": plan["plan_id"],
        },
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GROUP_BROWSER_PASS" in result.stdout


def test_receipt_purpose_cannot_be_overridden_by_group_history():
    cards = [card(1), card(2), card(3)]
    cards[0]["receipt_evidence"] = {
        "status": "RECEIPT_MATCHED",
        "candidates": [{"facts": [{"field": "description", "value": "car repair"}]}],
    }
    plan = analyze(cards, history())
    assert plan["groups"][0]["card_ids"] == ["2", "3"]
    assert "1" in plan["individual_ids"]


def test_live_plan_rebuilds_after_same_batch_decision_and_restart(grouped, monkeypatch):
    g, old = grouped
    _, service = g.get(old["plan_id"])
    cid = old["cards"][0]["card_id"]
    preview = service.preview(
        {
            "card_id": cid,
            "action": "CHANGE",
            "fields": {"category": "OTHER", "context": "PERSONAL"},
            "touched_fields": ["category", "context"],
            "correction_reason": "Synthetic live decision",
            "review_version": service.current_review(cid)["review_version"],
        },
        "browser",
    )
    g.individual_commit(
        old["plan_id"],
        Commit(token=preview["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
        "browser",
    )
    assert not g.is_current(old)
    with pytest.raises(ValueError, match="STALE_GROUP_HISTORY"):
        g.preview(old["plan_id"], old["groups"][0]["id"], "browser")
    restarted = GroupReview(g.queue)
    new = restarted.live(old["plan_id"])
    assert new["plan_id"] != old["plan_id"]
    assert new["summary"]["total_pending"] == 2
    assert cid not in {c["card_id"] for c in new["cards"]}
    assert all(c["review_analysis"]["known_entity"] for c in new["cards"])
    assert g.is_current(new)

    # Multiple tabs can keep the old URL. Once rebuilt, reuse the current plan.
    def unexpected_rebuild(*args, **kwargs):
        pytest.fail("An old URL rebuilt an already current queue")

    monkeypatch.setattr(restarted, "_build", unexpected_rebuild)
    assert restarted.live(old["plan_id"])["plan_id"] == new["plan_id"]
    restored = GroupReview(g.queue)
    monkeypatch.setattr(restored, "_build", unexpected_rebuild)
    assert restored.live(old["plan_id"])["plan_id"] == new["plan_id"]


def test_recent_review_removes_novelty_without_promoting_unsupported_labels(queue):
    g = GroupReview(queue)
    old = g.build()
    _, service = g.get(old["plan_id"])
    cid = old["cards"][0]["card_id"]
    preview = service.preview(
        {
            "card_id": cid,
            "action": "CHANGE",
            "fields": {"category": "OTHER", "context": "PERSONAL"},
            "touched_fields": ["category", "context"],
            "correction_reason": "Synthetic first merchant review",
            "review_version": service.current_review(cid)["review_version"],
        },
        "browser",
    )
    g.individual_commit(
        old["plan_id"],
        Commit(token=preview["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
        "browser",
    )
    new = g.live(old["plan_id"])
    assert new["summary"]["total_pending"] == 34
    assert not new["groups"]
    for c in new["cards"]:
        a = c["review_analysis"]
        assert a["known_entity"]
        assert a["novelty_transition"] == "FALSE_NOVEL_RECENT_REVIEW"
        assert "unseen_entity" not in a["novelty_components"]
        assert a["reason"] == "INSUFFICIENT_EVIDENCE"
        assert "1 prior reviewed" in a["why_review"]


def test_third_consistent_review_creates_group_and_conflict_removes_it(queue):
    g = GroupReview(queue)
    old = g.build()
    _, s = g.get(old["plan_id"])
    ids = [c["card_id"] for c in old["cards"][:3]]
    current = old
    for old_cid in ids:
        txid = next(c["transaction"]["id"] for c in old["cards"] if c["card_id"] == old_cid)
        cid = next(c["card_id"] for c in current["cards"] if c["transaction"]["id"] == txid)
        _, s = g.get(current["plan_id"])
        p = s.preview(
            {
                "card_id": cid,
                "action": "CHANGE",
                "fields": {"category": "OTHER", "context": "PERSONAL"},
                "touched_fields": ["category", "context"],
                "correction_reason": "Synthetic stable merchant",
                "review_version": s.current_review(cid)["review_version"],
            },
            "browser",
        )
        g.individual_commit(
            current["plan_id"],
            Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
            "browser",
        )
        current = g.live(current["plan_id"])
    assert current["summary"]["groupable_transactions"] == 32
    stale = g.preview(current["plan_id"], current["groups"][0]["id"], "browser")
    _, s = g.get(old["plan_id"])
    p = s.preview(
        {
            "card_id": ids[0],
            "action": "CHANGE",
            "fields": {"category": "TRAVEL"},
            "touched_fields": ["category"],
            "correction_reason": "Synthetic conflicting purpose",
            "review_version": s.current_review(ids[0])["review_version"],
        },
        "browser",
    )
    g.individual_commit(
        old["plan_id"],
        Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
        "browser",
    )
    with pytest.raises(ValueError, match="STALE_GROUP_HISTORY"):
        g.commit(current["plan_id"], stale["token"], "browser")
    new = g.live(current["plan_id"])
    assert not new["groups"]
    assert all(c["review_analysis"]["reason"] == "CONFLICTING_HISTORY" for c in new["cards"])
