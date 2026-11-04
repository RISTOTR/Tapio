import json
from copy import deepcopy

import pytest

from apps.api.tests.test_semantic_concepts import card
from tapio.confirmation.rule_review import RuleReview
from tapio.knowledge.user_rules import (
    UserRule,
    apply_user_rules,
    explanations,
    explicit_user_context,
    friction_metrics,
    rule_match,
)


def rule(
    subject="DNA Oyj",
    scope=None,
    category="OTHER",
    context="PERSONAL",
    kind="MERCHANT_CLASSIFICATION_RULE",
):
    return UserRule(
        subject=subject,
        category=category,
        context=context,
        kind=kind,
        scope=scope or {"type": "ENTITY_FAMILY", "entity": subject},
    ).model_dump(mode="json")


def active(r=None, event_id="decision"):
    return {"candidate_id": "candidate-" + event_id, "event_id": event_id, "rule": r or rule()}


def tx(name="DNA Oyj", recipient=None, day="2026-06-09"):
    return {
        "id": "new",
        "normalized_counterparty": name,
        "ultimate_recipient": recipient,
        "booking_date": day,
    }


def trip():
    return rule(
        "2026 planting trip",
        {
            "type": "TRIP",
            "start": "2026-05-25",
            "end": "2026-06-10",
            "purpose": "TREE_PLANTING",
            "modes": ["BUS", "TRAIN", "FLIGHT"],
            "transport_entities": {"Onnibuscom Oy": "BUS", "VR": "TRAIN", "Finnair Oyj": "FLIGHT"},
        },
        "TRAVEL",
        "FORESTRY",
        "TRIP_SCOPED_RULE",
    )


@pytest.mark.parametrize(
    "merchant,recipient",
    [("DNA Oyj", None), ("dna oy", None), ("DNA", None), ("Paytrail Oyj", "DNA Oyj")],
)
def test_dna_exact_resolver_direct_and_processor_recipient(merchant, recipient):
    c = card(merchant)
    c.update(
        multi_context=True,
        paytrail_purpose="STILL_OPAQUE",
        receipt_evidence={"status": "NO_RECEIPT_FOUND_IN_AVAILABLE_MAIL"},
    )
    result = apply_user_rules(c, tx(merchant, recipient), [active()])
    assert (
        result["suggestion"]["category"] == "OTHER"
        and result["suggestion"]["context"] == "PERSONAL"
    )
    assert explicit_user_context(result)
    assert result["user_rules"][0]["rule"]["scope"]["owner"] == "THIS_USER"
    assert result["current_state"] == c["current_state"]


@pytest.mark.parametrize(
    "merchant,recipient",
    [("Paytrail Oyj", None), ("Paytrail Oyj", "DNA reseller scam"), ("DNA tools", None)],
)
def test_processor_and_lookalike_do_not_inherit_rule(merchant, recipient):
    result = apply_user_rules(card(merchant), tx(merchant, recipient), [active()])
    assert not result["user_rules"] and result["suggestion"]["context"] is None


@pytest.mark.parametrize(
    "term,concept,name",
    [
        ("ravintola", "RESTAURANT", "Ravintola New"),
        ("café", "CAFE", "Café New"),
        ("bar", "BAR", "New Bar"),
    ],
)
def test_explicit_taxonomy_rule(term, concept, name):
    r = rule(
        concept,
        {"type": "USER_GLOBAL_TAXONOMY", "concept": concept, "terms": [term]},
        kind="VOCABULARY_CLASSIFICATION_RULE",
    )
    out = apply_user_rules(card(name), tx(name), [active(r)])
    assert out["suggestion"]["category"] == "OTHER" and out["suggestion"]["context"] == "PERSONAL"
    assert not apply_user_rules(card("Barcelona"), tx("Barcelona"), [active(r)])["user_rules"]


def test_exact_private_road_not_generic_road():
    r = rule(
        "Lepolan yksityistie",
        {"type": "ENTITY_EXACT", "entity": "Lepolan yksityistie"},
        "MAINTENANCE",
        "FORESTRY",
        "ENTITY_CLASSIFICATION_RULE",
    )
    assert rule_match(UserRule.model_validate(r), tx("Lepolan yksityistie"))
    assert not rule_match(UserRule.model_validate(r), tx("Other yksityistie"))
    assert not rule_match(UserRule.model_validate(r), tx("Lepolan yksityistie extra"))


@pytest.mark.parametrize(
    "name,day,match",
    [
        ("Onnibuscom Oy", "2026-06-09", True),
        ("Onnibuscom Oy", "2026-06-11", False),
        ("Onnibuscom Oy", "2025-06-09", False),
        ("Ravintola New", "2026-06-09", False),
        ("VR", "2026-06-09", True),
        ("Finnair Oyj", "2026-06-09", True),
    ],
)
def test_trip_requires_date_and_explicit_transport_identity(name, day, match):
    c = card(name)
    c["suggestion"]["category"] = "TRAVEL" if name != "Ravintola New" else "OTHER"
    out = apply_user_rules(c, tx(name, day=day), [active(trip())])
    assert bool(out["user_rules"]) == match
    assert out["suggestion"]["context"] == ("FORESTRY" if match else None)


def test_human_decision_precedence_and_rule_conflict():
    c = card()
    c["current_state"] = {
        "category": "MAINTENANCE",
        "context": "FORESTRY",
        "authority": {"category": "HUMAN_CONFIRMED", "context": "HUMAN_CONFIRMED"},
    }
    before = deepcopy(c)
    out = apply_user_rules(c, tx(), [active()])
    assert (
        out["suggestion"] == before["suggestion"]
        and out["current_state"] == before["current_state"]
    )
    out = apply_user_rules(card(), tx(), [active(), active(rule(context="FORESTRY"), "other")])
    assert out["suggestion"]["context"] is None and out["user_rule_conflicts"] == ["context"]
    assert any(r["code"] == "USER_RULE_CONFLICT" for r in out["reasons"])


def test_no_implicit_unbounded_or_ambiguous_retail_rule():
    with pytest.raises(ValueError):
        rule("Tokmanni")
    with pytest.raises(ValueError):
        rule("Paytrail Oyj")
    with pytest.raises(ValueError):
        rule("K-Rauta")
    with pytest.raises(ValueError):
        rule(scope={"type": "TRIP"})
    with pytest.raises(ValueError):
        rule(scope={"type": "ENTITY_EXACT", "entity": "DNA Oyj", "terms": ["DNA"]})


def test_repeated_explanation_normalized_and_provenance():
    revisions = [
        {
            "id": "r1",
            "transaction_id": "t1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "fields": {"category": "OTHER"},
            "audit": {"correction_reason": "Ravintola is always other-personal"},
        },
        {
            "id": "r2",
            "transaction_id": "t2",
            "created_at": "2026-02-01T00:00:00+00:00",
            "fields": {"category": "OTHER"},
            "audit": {"correction_reason": "RAVINTOLA, café, bar is always other-personal"},
        },
    ]
    observed = explanations(
        revisions,
        [{"id": "t1", "booking_date": "2026-01-01"}, {"id": "t2", "booking_date": "2026-02-01"}],
    )
    assert len(observed["RESTAURANT"]) == 2 and len(observed["CAFE"]) == 1
    result = friction_metrics(observed, [], {})
    assert result["total_repeats"] == 1 and result["after_activation"] == "NOT_OBSERVED"
    assert observed["RESTAURANT"][0]["review_hash"]


def test_missed_reuse_requires_active_rule_at_card_creation_and_scope():
    obs = {
        "DNA Oyj": [
            {
                "review_id": "review",
                "transaction_id": "new",
                "timestamp": "2026-06-10T00:00:00+00:00",
            }
        ]
    }
    event = {
        "id": "decision",
        "candidate_id": "c",
        "timestamp": "2026-06-01T00:00:00+00:00",
        "action": "CONFIRM_RULE",
        "rule": rule(),
    }
    cards = {
        "new": {**card(), "created_at": "2026-06-09T00:00:00+00:00", "source_transaction": tx()}
    }
    assert len(friction_metrics(obs, [event], cards)["missed_reuse"]) == 1
    revoked = {
        **event,
        "id": "revoked",
        "timestamp": "2026-06-02T00:00:00+00:00",
        "action": "DEFER_RULE",
    }
    assert not friction_metrics(obs, [event, revoked], cards)["missed_reuse"]
    cards["new"]["source_transaction"] = tx("Paytrail Oyj")
    assert not friction_metrics(obs, [event], cards)["missed_reuse"]


def review_store(tmp_path, r=None):
    r = r or rule()
    candidate = {
        "id": "c",
        "rule": r,
        "support": [],
        "semantic_facts": [
            {"kind": "MERCHANT_TYPE", "subject": "DNA Oyj", "concept": "TELECOM_PROVIDER"}
        ],
        "date_envelope": {"start": "2026-05-01", "end": "2026-06-30"},
    }
    (tmp_path / "candidates.json").write_text(json.dumps([candidate]))
    return RuleReview(tmp_path, key=b"test"), candidate


def test_rule_confirmation_audit_fact_separation_idempotency_stale(tmp_path):
    service, c = review_store(tmp_path)
    selection = {
        "candidate_id": "c",
        "action": "CONFIRM_RULE",
        "rule": c["rule"],
        "expected_state": "PENDING",
    }
    p = service.preview(selection, "b")
    stale = service.preview({**selection, "action": "DEFER_RULE"}, "b")
    saved = service.commit_result(p["token"], "b")
    assert saved["record"]["active"]
    assert service.commit_result(p["token"], "b")["status"] == "ALREADY_APPLIED"
    with pytest.raises(ValueError, match="STALE_RULE_STATE"):
        service.commit(stale["token"], "b")
    assert len(service.events()) == 1 and len(service.knowledge_events()[0].claims) == 2
    assert {x.kind for x in service.knowledge_events()[0].claims} == {"USER_RULE", "MERCHANT_TYPE"}
    p = service.preview(
        {
            **selection,
            "action": "DEFER_RULE",
            "expected_state": saved["record"]["state_version"],
            "revise": True,
        },
        "b",
    )
    service.commit(p["token"], "b")
    assert not service.active() and len(service.events()) == 2


def test_trip_requires_explicit_boundary_attestation(tmp_path):
    s, c = review_store(tmp_path, trip())
    selection = {
        "candidate_id": "c",
        "action": "CONFIRM_RULE",
        "rule": c["rule"],
        "expected_state": "PENDING",
    }
    with pytest.raises(ValueError, match="BOUNDARY_CONFIRMATION"):
        s.preview(selection, "b")
    p = s.preview({**selection, "scope_confirmed": True}, "b")
    assert not s.active()
    s.commit(p["token"], "b")
    assert s.active()


def test_rule_api_returns_persisted_state_without_transaction_writes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tapio.confirmation import api

    s, c = review_store(tmp_path)
    monkeypatch.setattr(
        api, "persistent_queue", lambda: SimpleNamespace(rules=s, enabled=lambda: True)
    )
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        p = "/pilot/confirmation/rules"
        before = client.get(p + "/cards").json()
        assert before["records"][0]["decision"] == "PENDING"
        headers = {"Origin": "http://testserver", "X-Tapio-CSRF": before["csrf"]}
        response = client.post(
            p + "/preview",
            json={
                "candidate_id": "c",
                "action": "CONFIRM_RULE",
                "rule": c["rule"],
                "expected_state": "PENDING",
            },
            headers=headers,
        )
        assert response.status_code == 200
        body = {"token": response.json()["token"], "explicit_click": "APPLY_USER_RULE_DECISION"}
        saved = client.post(p + "/commit", json=body, headers=headers).json()
        assert saved["record"]["decision"] == "CONFIRMED"
        assert client.get(p + "/cards").json()["records"][0] == saved["record"]
        assert (
            client.post(p + "/commit", json=body, headers=headers).json()["status"]
            == "ALREADY_APPLIED"
        )
        assert len(s.events()) == 1


def test_rule_edit_cannot_broaden_identity_or_trip_envelope(tmp_path):
    s, c = review_store(tmp_path, trip())
    changed = deepcopy(c["rule"])
    changed["scope"]["end"] = "2026-07-01"
    with pytest.raises(ValueError, match="ENVELOPE"):
        s.preview(
            {
                "candidate_id": "c",
                "action": "EDIT_RULE",
                "rule": changed,
                "expected_state": "PENDING",
                "scope_confirmed": True,
            },
            "b",
        )
    changed = deepcopy(c["rule"])
    changed["scope"]["transport_entities"]["Any restaurant"] = "BUS"
    with pytest.raises(ValueError, match="SCOPE_FROZEN"):
        s.preview(
            {
                "candidate_id": "c",
                "action": "EDIT_RULE",
                "rule": changed,
                "expected_state": "PENDING",
                "scope_confirmed": True,
            },
            "b",
        )


def test_rule_ui_persists_status_without_automatic_reapply():
    import subprocess

    subprocess.run(["node", "apps/api/tests/js/rule_ui.cjs"], check=True, capture_output=True)
