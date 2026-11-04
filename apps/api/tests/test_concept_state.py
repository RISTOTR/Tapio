from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.tests.test_semantic_concepts import candidate, card, store
from tapio.confirmation import api
from tapio.confirmation.concept_review import ConceptReview
from tapio.knowledge.category_mappings import derive_mappings
from tapio.knowledge.concepts import apply_concepts


def selection(action="CONFIRM_CONCEPT", **kw):
    return {"candidate_id": "c", "action": action, "concept": "RESTAURANT", **kw}


def test_canonical_persisted_state_and_restart(tmp_path):
    s, _ = store(tmp_path)
    assert s.record("c")["decision"] == "PENDING"
    p = s.preview(selection(expected_state="PENDING"), "b")
    result = s.commit_result(p["token"], "b")
    record = result["record"]
    assert result["status"] == "SAVED"
    assert record["decision"] == "CONFIRMED" and record["active"]
    assert record["authority"] == "HUMAN_CONFIRMED" and record["timestamp"]
    assert ConceptReview(tmp_path).record("c") == record
    assert s.knowledge_events()[0].claims[0].provenance.confirmation_id == record["event_id"]
    assert len(s.events()) == len(s.knowledge_events()) == 1


def test_same_token_and_same_decision_new_token_are_idempotent(tmp_path):
    s, _ = store(tmp_path)
    p = s.preview(selection(), "b")
    s.commit_result(p["token"], "b")
    assert s.commit_result(p["token"], "b")["status"] == "ALREADY_APPLIED"
    p = s.preview(selection(expected_state=s.record("c")["state_version"], revise=True), "b")
    assert s.commit_result(p["token"], "b")["status"] == "ALREADY_APPLIED"
    assert len(s.events()) == len(s.knowledge_events()) == 1


def test_stale_revision_and_deferred_inactive_preserve_audit(tmp_path):
    s, c = store(tmp_path)
    first = s.preview(selection(expected_state="PENDING"), "b")
    stale = s.preview(selection("DEFER", expected_state="PENDING"), "b")
    s.commit(first["token"], "b")
    with pytest.raises(ValueError, match="STALE_CONCEPT_STATE"):
        s.commit(stale["token"], "b")
    with pytest.raises(ValueError, match="STALE_CONCEPT_STATE"):
        s.preview(selection(expected_state="PENDING"), "b")
    p = s.preview(
        selection("DEFER", expected_state=s.record("c")["state_version"], revise=True), "b"
    )
    result = s.commit_result(p["token"], "b")
    assert result["record"]["decision"] == "DEFERRED" and not result["record"]["active"]
    assert len(s.events()) == 2 and len(s.knowledge_events()) == 1
    assert (
        apply_concepts(
            card(), {"id": "new", "normalized_counterparty": "ravintola new"}, [c], s.decisions()
        )["suggestion"]["category"]
        is None
    )


def test_mapping_is_separate_scoped_suggested_and_conflicts_block():
    c = candidate()
    mapping = derive_mappings([c])[0]
    assert mapping["authority"] == "SUGGESTED" and mapping["scope"]["candidate_id"] == c["id"]
    decisions = {"c": {"id": "review", "action": "CONFIRM_CONCEPT", "concept": "RESTAURANT"}}
    tx = {"id": "new", "normalized_counterparty": "ravintola new"}
    assert apply_concepts(card(), tx, [c], decisions, mappings=[])["suggestion"]["category"] is None
    c["support"][0]["category"] = "GROCERIES"
    mapping = derive_mappings([c])[0]
    assert mapping["conflicts"] and not mapping["eligible"]
    assert apply_concepts(card(), tx, [c], decisions)["suggestion"]["category"] is None


def test_edited_fact_does_not_approve_new_mapping():
    c = candidate()
    d = {"c": {"id": "r", "action": "EDIT_CONCEPT", "concept": "GROCERY_RETAILER"}}
    result = apply_concepts(
        card(), {"id": "new", "normalized_counterparty": "ravintola new"}, [c], d
    )
    assert result["suggestion"]["category"] is None
    assert "NO_SUPPORTED_CATEGORY_MAPPING" in result["blocked_generalizations"]


def test_api_returns_authority_and_preserves_session_across_refresh(tmp_path, monkeypatch):
    s, _ = store(tmp_path)
    monkeypatch.setattr(
        api, "persistent_queue", lambda: SimpleNamespace(concepts=s, enabled=lambda: True)
    )
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        path = "/pilot/confirmation/concepts"
        first = client.get(path + "/cards").json()
        headers = {"Origin": "http://testserver", "X-Tapio-CSRF": first["csrf"]}
        assert client.get(path + "/cards").json()["csrf"] == first["csrf"]
        p = client.post(
            path + "/preview", json=selection(expected_state="PENDING"), headers=headers
        )
        assert p.status_code == 200
        body = {"token": p.json()["token"], "explicit_click": "APPLY_CONCEPT_DECISION"}
        result = client.post(path + "/commit", json=body, headers=headers)
        assert result.json()["record"]["decision"] == "CONFIRMED"
        assert (
            client.post(path + "/commit", json=body, headers=headers).json()["status"]
            == "ALREADY_APPLIED"
        )
        assert client.get(path + "/cards").json()["records"][0] == result.json()["record"]
        assert (
            client.post(
                path + "/preview",
                json=selection(expected_state=result.json()["record"]["state_version"]),
                headers=headers,
            ).status_code
            == 409
        )
        stale = client.post(
            path + "/preview", json=selection(expected_state="PENDING"), headers=headers
        )
        assert stale.status_code == 409 and stale.json()["detail"] == "STALE_CONCEPT_STATE"
        assert len(s.events()) == 1


def test_atomic_publication_failure_leaves_no_partial_event(tmp_path, monkeypatch):
    s, _ = store(tmp_path)
    p = s.preview(selection(), "b")

    def fail(*args):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr("tapio.confirmation.concept_review.os.link", fail)
    with pytest.raises(OSError):
        s.commit(p["token"], "b")
    assert not s.events() and s.record("c")["decision"] == "PENDING"
    assert not list((tmp_path / "concept_decisions").iterdir())


def test_browser_script_replaces_authoritative_state_and_reload():
    import subprocess

    subprocess.run(["node", "apps/api/tests/js/concept_ui.cjs"], check=True, capture_output=True)


@pytest.mark.parametrize(
    "term,concept,category,merchant,recipient,action,expected",
    [
        (
            "k-market",
            "GROCERY_RETAILER",
            "GROCERIES",
            "K-Market New Branch",
            None,
            "CONFIRM_CONCEPT",
            "GROCERIES",
        ),
        ("ravintola", "RESTAURANT", "OTHER", "Ravintola New", None, "CONFIRM_CONCEPT", "OTHER"),
        (
            "katsastus",
            "VEHICLE_INSPECTION",
            "MAINTENANCE",
            "Uusi katsastus",
            None,
            "CONFIRM_CONCEPT",
            "MAINTENANCE",
        ),
        (
            "lähitapiola",
            "INSURANCE_COMPANY",
            "INSURANCE",
            "Paytrail Oyj",
            "LähiTapiola New",
            "CONFIRM_CONCEPT",
            "INSURANCE",
        ),
        ("tokmanni", "GENERAL_RETAILER", "OTHER", "Tokmanni New", None, "CONFIRM_CONCEPT", None),
        ("k-rauta", "HARDWARE_RETAILER", "MAINTENANCE", "K-Rauta New", None, "DEFER", None),
    ],
)
def test_requested_semantic_safety_examples(
    term, concept, category, merchant, recipient, action, expected
):
    c = candidate(term, concept, category)
    tx = {"id": "new", "normalized_counterparty": merchant, "ultimate_recipient": recipient}
    decisions = {"c": {"id": "decision", "action": action, "concept": concept}}
    result = apply_concepts(card(merchant), tx, [c], decisions)
    assert result["suggestion"]["category"] == expected
    assert result["suggestion"]["context"] is None
    for fact in result["semantic_concepts"]:
        mapping = fact["category_mapping"]
        assert mapping["authority"] == "SUGGESTED" and mapping["scope"]["candidate_id"] == "c"
