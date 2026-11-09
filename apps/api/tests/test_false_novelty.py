"""Regression coverage for proven aliases, taxonomy reuse and purpose boundaries."""

import hashlib
import hmac
import json
from copy import deepcopy

import pytest

from apps.api.tests.test_group_review import card, history
from apps.api.tests.test_semantic_concepts import apply as concept_apply
from apps.api.tests.test_semantic_concepts import candidate
from apps.api.tests.test_user_rules import active, rule, tx
from tapio.confirmation.grouping import analyze
from tapio.knowledge.models import digest
from tapio.knowledge.reuse import Reuse
from tapio.knowledge.user_rules import apply_user_rules


def reuse():
    return Reuse(
        {
            "entities": [
                {
                    "id": "road-1",
                    "canonical_name": "Example yksityistie",
                    "aliases": ["Example yksityistien tiekunta"],
                    "limitations": ["MULTI_CONTEXT", "MIXED_PURPOSE"],
                    "evidence": [{"table": "transactions", "id": "source", "hash": "proof"}],
                }
            ],
            "vocabulary": [
                {
                    "term": "taberna",
                    "concept": "RESTAURANT",
                    "anchors": ["ravintola"],
                    "evidence": [
                        {"table": "confirmation_revisions", "id": "review", "hash": "proof"}
                    ],
                }
            ],
        }
    )


def test_isoniemen_alias_shape_reuses_explicit_canonical_history():
    r = reuse()
    rows = [{**h, "identity": "Example yksityistie"} for h in history()]
    c = card(1, r.key("EXAMPLE   yksityistien tiekunta"))
    c["purpose_review_required"] = True
    p = analyze([c], r.history(rows))
    assert p["cards"][0]["review_analysis"]["known_entity"]
    assert p["cards"][0]["review_analysis"]["reason"] == "KNOWN_ENTITY_NEW_PURPOSE"
    assert "unseen_entity" not in p["cards"][0]["review_analysis"]["novelty_components"]
    assert p["groups"] == []  # The road's mixed-purpose caveat survives alias reuse.


@pytest.mark.parametrize(
    "name",
    [
        "Other yksityistie",
        "Example yksityistie extra",
        "yksityistie",
        "Example yksityistien tiekunta extra",
    ],
)
def test_alias_never_matches_other_private_roads(name):
    assert reuse().key(name) != reuse().key("Example yksityistie")


def test_canonical_history_survives_case_spacing_and_unicode_variants():
    r = reuse()
    assert r.key("EXAMPLE  yksityistie") == r.key("Example yksityistien tiekunta")
    assert Reuse().key("Synthetic Oy.") == Reuse().key("SYNTHETIC  OY")
    assert r.resolve("Example yksityistien tiekunta")["canonical_id"] == "road-1"


def taxonomy():
    return rule(
        "RESTAURANT",
        {"type": "USER_GLOBAL_TAXONOMY", "concept": "RESTAURANT", "terms": ["ravintola"]},
        kind="VOCABULARY_CLASSIFICATION_RULE",
    )


def test_taberna_reuses_existing_taxonomy_without_new_rule_or_authority():
    r = reuse()
    original = active(taxonomy())
    c = card(1, "taberna synthetic madrid")
    c["transaction"]["merchant"] = c["identity_key"]
    c["reasons"] = []
    result = apply_user_rules(c, tx(c["identity_key"]), [original], reuse=r)
    assert result["suggestion"] == {"category": "OTHER", "context": "PERSONAL"}
    assert result["current_state"]["authority"] == {}
    assert result["user_rules"][0]["event_id"] == original["event_id"]
    p = analyze([result], [])
    assert p["cards"][0]["review_analysis"]["reason"] == "ACTIVE_USER_RULE_MATCH"
    assert "unseen_entity" not in p["cards"][0]["review_analysis"]["novelty_components"]
    assert p["individual_ids"] == []  # One preview/apply; no repeated field classification.
    assert p["summary"]["known_single_confirmations"] == 1


def test_vocabulary_link_requires_active_compatible_taxonomy_and_token_boundary():
    r = reuse()
    for name, rules in [
        ("taberna synthetic", []),
        ("tabernacle synthetic", [active(taxonomy())]),
        ("taberna synthetic", [active(rule())]),
    ]:
        c = card(1, name)
        c["reasons"] = []
        result = apply_user_rules(c, tx(name), rules, reuse=r)
        assert not result["user_rules"]
        assert result["suggestion"]["context"] is None


def test_pending_concept_cannot_gain_authority_from_vocabulary_link():
    c = concept_apply(merchant="Taberna Synthetic", approved=False, reuse=reuse())
    assert not c["semantic_category_used"]
    assert not c["known_semantic_concepts"]


def test_confirmed_concept_reuses_vocabulary_for_category_only():
    c = concept_apply(merchant="Taberna Synthetic", reuse=reuse())
    assert c["semantic_category_used"]
    assert c["suggestion"]["category"] == "OTHER"
    assert c["suggestion"]["context"] is None


def test_known_airline_new_purchase_purpose_is_not_unknown_entity():
    c = concept_apply(
        candidate("iberia", "AIRLINE", "TRAVEL", mode="CHAIN_PREFIX"), merchant="Iberia-Vta a Bordo"
    )
    c["identity_key"] = "iberia-vta a bordo"
    c["transaction"].update(date="2026-01-01", amount="-5")
    c["card_id"] = "flight"
    p = analyze([c], [])
    assert p["cards"][0]["review_analysis"]["reason"] == "KNOWN_ENTITY_NEW_PURPOSE"
    assert not p["groups"]


def test_prior_exact_history_below_group_threshold_is_known_but_needs_evidence():
    c = analyze([card(1)], history()[:2])["cards"][0]
    assert c["review_analysis"]["known_entity"]
    assert c["review_analysis"]["reason"] == "INSUFFICIENT_EVIDENCE"


def test_reuse_store_checks_signature_and_source_evidence(tmp_path):
    row = {"id": "source", "name": "Synthetic"}
    data = deepcopy(reuse().data)
    data["vocabulary"] = []
    data["entities"][0]["evidence"][0]["hash"] = digest(row)
    (tmp_path / "queue.key").write_bytes(b"synthetic-test-key")
    signature = hmac.new(b"synthetic-test-key", digest(data).encode(), hashlib.sha256).hexdigest()
    path = tmp_path / "reuse.json"
    path.write_text(json.dumps({"data": data, "signature": signature}))
    assert Reuse.load(tmp_path, {"transactions": [row]}).key("Example yksityistie")
    with pytest.raises(ValueError, match="STALE_REUSE_EVIDENCE"):
        Reuse.load(tmp_path, {"transactions": [{**row, "name": "changed"}]})
    data["entities"][0]["aliases"].append("Other road")
    path.write_text(json.dumps({"data": data, "signature": signature}))
    with pytest.raises(ValueError, match="REUSE_INTEGRITY"):
        Reuse.load(tmp_path)


def test_alias_collision_fails_closed():
    data = deepcopy(reuse().data)
    data["entities"].append(deepcopy(data["entities"][0]))
    with pytest.raises(ValueError, match="COLLISION"):
        Reuse(data)


def test_partial_human_review_is_never_an_unseen_entity():
    c = card(1)
    c["current_state"] = {
        "category": "OTHER",
        "context": None,
        "authority": {"category": "HUMAN_CONFIRMED"},
    }
    result = analyze([c], [])["cards"][0]["review_analysis"]
    assert result["known_entity"]
    assert result["reason"] == "INSUFFICIENT_EVIDENCE"
