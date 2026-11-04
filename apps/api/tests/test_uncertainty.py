import json
from copy import deepcopy

import pytest

from apps.api.tests.test_controlled_confirmation import factory as factory
from apps.api.tests.test_persistent_review import queue as queue
from apps.api.tests.test_semantic_concepts import apply, candidate, card
from apps.api.tests.test_user_rules import active, rule, trip, tx
from tapio.confirmation.mapping_review import MappingReview
from tapio.knowledge.category_mappings import derive_mappings
from tapio.knowledge.concepts import matches
from tapio.knowledge.review_audit import audit_rule_use
from tapio.knowledge.review_candidates import propose
from tapio.knowledge.uncertainty import (
    apply_uncertainty,
    consolidate,
    field_state,
    observations,
    repeated_unknown,
    unknown_events,
)
from tapio.knowledge.user_rules import UserRule, apply_user_rules, rule_match


def state(category=None, context=None):
    return {
        "category": category,
        "context": context,
        "authority": {
            f: "HUMAN_CONFIRMED" if v is not None else "UNKNOWN"
            for f, v in [("category", category), ("context", context)]
        },
    }


def obs(name="Synthetic Shop", tid="old", field="category", value="UNKNOWN"):
    return {
        "transaction_id": tid,
        "identity": name,
        "identity_key": name.casefold(),
        "field": field,
        "value": value,
        "field_state": "HUMAN_CONFIRMED_UNKNOWN" if value == "UNKNOWN" else "HUMAN_CONFIRMED_VALUE",
        "authority": "HUMAN_CONFIRMED",
        "review_id": "r-" + tid,
        "review_hash": "a" * 64,
        "source_type": "confirmation_revisions",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "note": "",
    }


@pytest.mark.parametrize(
    "s,f,expected",
    [
        (state(), "category", "UNREVIEWED"),
        (state(None, "PERSONAL"), "category", "UNRESOLVED"),
        (state("UNKNOWN"), "category", "HUMAN_CONFIRMED_UNKNOWN"),
        (state("OTHER"), "category", "HUMAN_CONFIRMED_VALUE"),
    ],
)
def test_explicit_field_states(s, f, expected):
    assert field_state(s, f) == expected


def test_unknown_never_overwritten_by_rule_or_semantics():
    c = card("DNA Oyj")
    c["current_state"] = state("UNKNOWN", "UNKNOWN")
    c["suggestion"].update(category="OTHER", context="PERSONAL")
    out = apply_uncertainty(apply_user_rules(c, tx(), [active()]), tx(), [])
    assert out["suggestion"]["category"] is None and out["suggestion"]["context"] is None
    assert out["current_state"] == state("UNKNOWN", "UNKNOWN")
    assert "HUMAN_CONFIRMED_UNKNOWN" in out["review_signals"]


def test_prior_unknown_abstains_without_assigning_unknown():
    c = card("Synthetic Shop")
    c["suggestion"]["category"] = "OTHER"
    rows = [obs(), obs(tid="older"), obs(field="context")]
    out = apply_uncertainty(c, tx("Synthetic Shop"), rows)
    assert out["suggestion"]["category"] is None
    assert out["current_state"]["category"] is None
    assert out["abstention_reasons"]["category"] == "HUMAN_CONFIRMED_UNKNOWN_HISTORY"
    assert len(repeated_unknown(rows)) == 1
    assert "Previously reviewed but purpose remained unknown." in out["reasons"][-1]["explanation"]
    assert not apply_uncertainty(c, tx("Different Shop"), rows)["uncertainty_history"]


def test_processor_does_not_share_unknown_history():
    assert not apply_uncertainty(
        card("Paytrail Oyj"), tx("Paytrail Oyj", "DNA Oyj"), [obs("Paytrail Oyj")]
    )["uncertainty_history"]


def test_unknown_events_preserve_field_provenance():
    events = unknown_events([obs(), obs(field="context")])
    assert len(events) == 2
    assert all(e.claims[0].authority == "HUMAN_CONFIRMED" for e in events)
    assert {e.claims[0].scope for e in events} == {"category", "context"}
    assert events[0].claims[0].provenance.confirmation_id == "r-old"


def test_corrected_unknown_is_not_current_observation():
    rows = [
        {
            "id": "first",
            "transaction_id": "new",
            "sequence": 1,
            "fields": {"category": "UNKNOWN"},
            "audit": {},
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "id": "second",
            "transaction_id": "new",
            "sequence": 2,
            "fields": {"category": "OTHER"},
            "audit": {},
            "created_at": "2026-01-02T00:00:00+00:00",
        },
    ]
    tables = {"transactions": [tx("Synthetic Shop")], "confirmation_revisions": rows}
    result = observations(tables, {"new": [state("OTHER"), None]})
    assert result[0]["review_id"] == "second" and not unknown_events(result)
    assert rows[0]["fields"]["category"] == "UNKNOWN"


def test_three_outcomes_and_original_audit_immutable():
    c = card()
    c["suggestion"]["category"] = "OTHER"
    revisions = [
        {
            "id": "r",
            "transaction_id": "new",
            "sequence": 1,
            "fields": {"category": "OTHER", "context": "UNKNOWN"},
            "audit": {
                "correction_reason": "explicit",
                "suggestion_snapshot": {"category": "OTHER", "context": None},
            },
            "created_at": "2026-01-01",
        }
    ]
    before = deepcopy(revisions)
    result = consolidate([c], revisions, {"new": [state("OTHER", "UNKNOWN")]})
    assert result["outcomes"] == {"ACCEPTED_EXISTING_SUGGESTION": 1, "HUMAN_CONFIRMED_UNKNOWN": 1}
    result = consolidate([c], revisions, {"new": [state("OTHER", "PERSONAL")]})
    assert result["outcomes"]["HUMAN_COMPLETED_KNOWN_VALUE"] == 1
    assert revisions == before


@pytest.mark.parametrize(
    "term,text,valid",
    [
        ("bar", "Barcelona", False),
        ("bar", "Foobar", False),
        ("cafe", "Cafeine", False),
        ("ravintola", "Superravintolainen", False),
        ("bar", "VFI* New BAR!", True),
        ("cafe", "Café Madrid", True),
        ("cerveceria", "CERVECERÍA Nueva", True),
        ("farmacia", "Farmácia central", True),
    ],
)
def test_tokens_accents_punctuation_prefixes(term, text, valid):
    assert matches(term, "TOKEN", text) == valid


@pytest.mark.parametrize(
    "term,concept,category,name",
    [
        ("farmacia", "PHARMACY", "OTHER", "Farmacia New"),
        ("lidl", "GROCERY_RETAILER", "GROCERIES", "Lidl New"),
        ("finnair", "AIRLINE", "TRAVEL", "Finnair"),
    ],
)
def test_new_semantic_types_never_supply_context(term, concept, category, name):
    out = apply(candidate(term, concept, category), merchant=name)
    expected = None if concept == "AIRLINE" else category
    assert out["suggestion"]["category"] == expected and out["suggestion"]["context"] is None
    if concept == "AIRLINE":
        assert "PURCHASE_PURPOSE_SUPPORT_REQUIRED" in out["blocked_generalizations"]


def test_government_identity_never_tax_mapping():
    c = candidate("traficom", "GOVERNMENT_AGENCY", "TAX")
    m = derive_mappings([c])[0]
    assert not m["eligible"] and "GOVERNMENT_IDENTITY_IS_NOT_TAX_PURPOSE" in m["blocked"]
    assert apply(c, merchant="Traficom")["suggestion"]["category"] is None


def test_unknown_is_not_mapping_value():
    assert not derive_mappings([candidate(category="UNKNOWN")])[0]["eligible"]


def test_new_mapping_needs_independent_review(tmp_path):
    c = {**candidate("farmacia", "PHARMACY", "OTHER"), "mapping_review_required": True}
    mapping = derive_mappings([c])[0]
    assert not mapping["eligible"]
    record = {
        "id": "mapping",
        "concept_candidate_id": c["id"],
        "concept": "PHARMACY",
        "category": "OTHER",
        "conflicts": [],
    }
    (tmp_path / "candidates.json").write_text(json.dumps([record]))
    review = MappingReview(tmp_path)
    selection = {
        "candidate_id": "mapping",
        "action": "CONFIRM_MAPPING",
        "expected_state": "PENDING",
    }
    p = review.preview(selection, "browser")
    assert not review.apply([mapping])[0]["eligible"]
    result = review.commit_result(p["token"], "browser")
    assert result["record"]["active"]
    assert review.commit_result(p["token"], "browser")["status"] == "ALREADY_APPLIED"
    assert review.apply([mapping])[0]["eligible"]
    with pytest.raises(ValueError, match="STALE"):
        review.preview(selection, "browser")
    assert review.apply([{**mapping, "concept": "AIRLINE"}])[0]["eligible"] is False


def test_rule_audit_detects_missing_and_false_matches():
    event = {
        "candidate_id": "candidate-decision",
        "id": "decision",
        "action": "CONFIRM_RULE",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "rule": rule(),
    }
    c = apply_user_rules(card("DNA Oyj"), tx(), [active()])
    batch = {"created_at": "2026-02-01T00:00:00+00:00", "cards": [c]}
    assert not audit_rule_use(batch, [tx()], [event])["missed_reuse"]
    before = deepcopy(batch)
    batch["cards"][0]["user_rules"] = []
    assert audit_rule_use(batch, [tx()], [event])["missed_reuse"]
    assert audit_rule_use(before, [tx("Unrelated")], [event])["false_matches"]
    event["timestamp"] = "2026-03-01T00:00:00+00:00"
    assert not audit_rule_use(batch, [tx()], [event])["missed_reuse"]


def test_trip_and_exact_roads_keep_scopes():
    r = UserRule.model_validate(trip())
    assert rule_match(r, tx("Onnibuscom Oy", day="2026-06-09"))
    assert not rule_match(r, tx("Onnibuscom Oy", day="2026-06-15"))
    road = UserRule.model_validate(
        rule(
            "Lepolan yksityistie",
            {"type": "ENTITY_EXACT", "entity": "Lepolan yksityistie"},
            "MAINTENANCE",
            "FORESTRY",
            "ENTITY_CLASSIFICATION_RULE",
        )
    )
    assert rule_match(road, tx("Lepolan yksityistie"))
    assert not rule_match(road, tx("Other yksityistie"))


def test_candidates_not_approved_and_onboard_not_travel():
    t = tx("iberia-vta a bordo barcelona")
    rows = [obs(t["normalized_counterparty"], tid="new", value="OTHER")]
    result = propose({"transactions": [t]}, rows, [card(t["normalized_counterparty"])], [], [])
    assert result["semantic"][0]["authority"] == "SUGGESTED"
    assert result["semantic"][0]["concept"] == "AIRLINE"
    assert not result["mappings"] and not result["rules"]


def test_next_window_keeps_archive_and_freezes_uncertainty_provenance(queue):
    q = queue
    q.advance(None, initial=True)
    service = q.service()
    frozen = (q.root / "windows/W0001/preview.json").read_bytes()
    for i, cid in enumerate(service.cards):
        service.monitor.write(f"attempts/{i}.json", {"action": "SKIP", "card_id": cid})
    q.advance("W0001")
    batch = q.service().batch
    assert batch["uncertainty_version"] == "EXPLICIT_UNKNOWN_V1"
    assert batch["mapping_version"] == q.mappings.version()
    assert all("field_states" in c and "abstention_reasons" in c for c in batch["cards"])
    assert (q.root / "windows/W0001/preview.json").read_bytes() == frozen


def test_replay_unknown_removes_superseded_projection():
    from tapio.knowledge.store import rebuild
    from tapio.knowledge.uncertainty import replay_unknown

    events = unknown_events([obs()])
    assert len(rebuild(replay_unknown(events, [obs()])).items) == 1
    assert not rebuild(replay_unknown(events, [obs(value="OTHER")])).items
    assert events[0].claims[0].value["value"] == "UNKNOWN"


def test_classification_friction_requires_prior_same_field_value():
    from tapio.knowledge.uncertainty import classification_friction

    c = {
        "records": [
            {
                "transaction_id": "new",
                "field": "category",
                "final_value": "OTHER",
                "outcome": "HUMAN_COMPLETED_KNOWN_VALUE",
                "review_id": "new-r",
            }
        ]
    }
    assert (
        classification_friction(c, [obs(value="OTHER")], [tx("Synthetic Shop")])[
            "repeated_manual_fields"
        ]
        == 1
    )
    assert (
        classification_friction(c, [obs()], [tx("Synthetic Shop")])["repeated_manual_fields"] == 0
    )
    assert (
        classification_friction(
            c, [obs(value="OTHER"), obs(tid="conflict", value="TRAVEL")], [tx("Synthetic Shop")]
        )["repeated_manual_fields"]
        == 0
    )


def test_mapping_api_preview_commit_reload_and_csrf(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tapio.confirmation import api

    (tmp_path / "candidates.json").write_text(
        json.dumps(
            [
                {
                    "id": "mapping",
                    "concept_candidate_id": "concept",
                    "concept": "PHARMACY",
                    "category": "OTHER",
                    "conflicts": [],
                }
            ]
        )
    )
    review = MappingReview(tmp_path)
    monkeypatch.setattr(
        api, "persistent_queue", lambda: SimpleNamespace(mappings=review, enabled=lambda: True)
    )
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        base = "/pilot/confirmation/mappings"
        data = client.get(base + "/cards").json()
        body = {"candidate_id": "mapping", "action": "CONFIRM_MAPPING", "expected_state": "PENDING"}
        assert client.post(base + "/preview", json=body).status_code == 403
        headers = {"Origin": "http://testserver", "X-Tapio-CSRF": data["csrf"]}
        p = client.post(base + "/preview", json=body, headers=headers)
        assert p.status_code == 200
        commit = {"token": p.json()["token"], "explicit_click": "APPLY_MAPPING_DECISION"}
        result = client.post(base + "/commit", json=commit, headers=headers).json()
        assert result["record"]["active"]
        assert client.get(base + "/cards").json()["records"][0] == result["record"]
        assert (
            client.post(base + "/commit", json=commit, headers=headers).json()["status"]
            == "ALREADY_APPLIED"
        )
        assert len(review.events()) == 1


@pytest.mark.parametrize("field", ["category", "context"])
def test_card_contract_rejects_reguessing_human_unknown(field):
    from pydantic import ValidationError

    from apps.api.tests.test_suggestion_cards import card as generated_card
    from apps.api.tests.test_suggestion_cards import generator, review
    from tapio.suggestions.models import Card

    row = review(2, None, None)
    row["confirmed_category" if field == "category" else "confirmed_business_context"] = "UNKNOWN"
    result = generated_card(generator(reviews=[review(1), row]))
    assert getattr(result.suggestion, field) is None
    data = result.model_dump()
    data["suggestion"][field] = "OTHER" if field == "category" else "PERSONAL"
    with pytest.raises(ValidationError, match="AUTHORITATIVE"):
        Card.model_validate(data)


def test_fully_confirmed_unknown_is_not_a_new_review_candidate():
    from apps.api.tests.test_suggestion_cards import card as generated_card
    from apps.api.tests.test_suggestion_cards import generator, review

    with pytest.raises(ValueError, match="INELIGIBLE"):
        generated_card(generator(reviews=[review(1), review(2, "UNKNOWN", "UNKNOWN")]))
