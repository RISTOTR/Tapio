from copy import deepcopy

import pytest

from tapio.confirmation.concept_review import ConceptReview
from tapio.knowledge.concepts import apply_concepts, generate_candidates
from tapio.knowledge.models import digest


def candidate(
    term="ravintola",
    concept="RESTAURANT",
    category="OTHER",
    kind="VOCABULARY_CONCEPT",
    mode="TOKEN",
):
    return {
        "id": "c",
        "kind": kind,
        "term": term,
        "match_mode": mode,
        "concept": concept,
        "authority": "SUGGESTED",
        "observed_labels": {},
        "support": [
            {"transaction_id": "old1", "identity": "Ravintola Alpha", "category": category},
            {"transaction_id": "old2", "identity": "Ravintola Beta", "category": category},
        ],
    }


def card(merchant="Ravintola Gamma"):
    return {
        "transaction": {"id": "new", "merchant": merchant},
        "source_hash": "s",
        "suggestion": {"category": None, "context": None, "authority": "SUGGESTED"},
        "current_state": {"category": None, "context": None, "authority": {}},
        "reasons": [],
        "multi_context": False,
    }


def apply(c=None, merchant="Ravintola Gamma", recipient=None, approved=True, **kwargs):
    c = c or candidate()
    tx = {"id": "new", "normalized_counterparty": merchant, "ultimate_recipient": recipient}
    decisions = (
        {
            c["id"]: {
                "id": "explicit-test-review",
                "action": "CONFIRM_CONCEPT",
                "concept": c["concept"],
            }
        }
        if approved
        else {}
    )
    return apply_concepts(kwargs.pop("base", card(merchant)), tx, [c], decisions, **kwargs)


def test_unseen_restaurant_category_without_personal_inference():
    result = apply(exclude_identity="Ravintola Gamma")
    assert result["suggestion"] == {"category": "OTHER", "context": None, "authority": "SUGGESTED"}
    assert result["semantic_category_added"]
    assert "INSUFFICIENT_TRANSACTION_SPECIFIC_EVIDENCE" in result["blocked_generalizations"]


def test_unseen_grocery_chain_no_context():
    c = candidate("k-supermarket", "GROCERY_RETAILER", "GROCERIES", "MERCHANT_TYPE", "CHAIN_PREFIX")
    result = apply(c, merchant="K-Supermarket NewBranch")
    assert result["suggestion"]["category"] == "GROCERIES"
    assert result["suggestion"]["context"] is None


def test_candidate_not_automatically_accepted():
    result = apply(approved=False)
    assert result["suggestion"]["category"] is None
    assert result["concept_candidates"][0]["authority"] == "SUGGESTED"
    assert not result["semantic_concepts"]


def test_processor_uses_exact_recipient_concept_only():
    c = candidate(
        "a-katsastus", "VEHICLE_INSPECTION", "MAINTENANCE", "RECIPIENT_CONCEPT", "CHAIN_PREFIX"
    )
    result = apply(c, merchant="Paytrail Oyj", recipient="A-Katsastus Oy")
    assert (
        result["suggestion"]["category"] == "MAINTENANCE"
        and result["suggestion"]["context"] is None
    )
    assert apply(c, merchant="Paytrail Oyj")["suggestion"]["category"] is None
    c["term"] = "paytrail"
    assert apply(c, merchant="Paytrail Oyj")["suggestion"]["category"] is None


def test_receipt_identity_can_support_recipient_but_not_context():
    c = candidate(
        "a-katsastus", "VEHICLE_INSPECTION", "MAINTENANCE", "RECIPIENT_CONCEPT", "CHAIN_PREFIX"
    )
    base = card("Paytrail Oyj")
    base["receipt_evidence"] = {
        "status": "RECEIPT_MATCHED",
        "candidates": [{"facts": [{"field": "merchant", "value": "A-Katsastus Oy"}]}],
    }
    assert apply(c, merchant="Paytrail Oyj", base=base)["suggestion"]["category"] == "MAINTENANCE"
    base["receipt_evidence"]["status"] = "MULTIPLE_RECEIPTS"
    assert apply(c, merchant="Paytrail Oyj", base=base)["suggestion"]["category"] is None


def test_tokmanni_context_stays_protected():
    c = candidate("tokmanni", "GENERAL_RETAILER", "OTHER", "MERCHANT_TYPE", "CHAIN_PREFIX")
    base = card("Tokmanni")
    base["suggestion"]["context"] = "PERSONAL"
    result = apply(c, merchant="Tokmanni", base=base)
    assert result["suggestion"]["category"] is None and result["suggestion"]["context"] is None
    assert "PURCHASE_PURPOSE_SUPPORT_REQUIRED" in result["blocked_generalizations"]


def test_hardware_requires_transaction_evidence():
    c = candidate("k-rauta", "HARDWARE_RETAILER", "MAINTENANCE", "MERCHANT_TYPE", "CHAIN_PREFIX")
    assert apply(c, merchant="K-Rauta")["suggestion"]["category"] is None
    base = card("K-Rauta")
    base["document_evidence"] = [{"invoice_id": "synthetic", "status": "CONFIRMED"}]
    result = apply(c, merchant="K-Rauta", base=base)
    assert result["suggestion"]["category"] is None and result["suggestion"]["context"] is None
    assert "HARDWARE_MAPPING_REQUIRES_SEPARATE_VALIDATION" in result["blocked_generalizations"]

    base["document_evidence"][0]["status"] = "CANDIDATE"
    assert apply(c, merchant="K-Rauta", base=base)["suggestion"]["category"] is None
    c["concept"] = "VEHICLE_SERVICE"
    decisions = {"c": {"id": "edit", "action": "EDIT_CONCEPT", "concept": "HARDWARE_RETAILER"}}
    result = apply_concepts(
        card("K-Rauta"), {"id": "new", "normalized_counterparty": "K-Rauta"}, [c], decisions
    )
    assert result["suggestion"]["category"] is None


def test_contradictory_concepts_and_support_block():
    c = candidate()
    d = deepcopy(c)
    d.update(id="d", concept="GROCERY_RETAILER")
    decisions = {
        x["id"]: {"id": x["id"], "action": "CONFIRM_CONCEPT", "concept": x["concept"]}
        for x in (c, d)
    }
    result = apply_concepts(
        card(), {"id": "new", "normalized_counterparty": "Ravintola Gamma"}, [c, d], decisions
    )
    assert result["suggestion"]["category"] is None
    assert "CONTRADICTORY_CONCEPTS" in result["blocked_generalizations"]
    c["support"][0]["category"] = "GROCERIES"
    assert apply(c)["suggestion"]["category"] is None


def test_exact_identity_held_out_and_no_majority_vote():
    c = candidate()
    c["support"][0]["identity"] = "Ravintola Gamma"
    assert apply(c, exclude_identity="Ravintola Gamma")["suggestion"]["category"] is None
    c["support"].append({"transaction_id": "old3", "identity": "Other", "category": "GROCERIES"})
    assert apply(c)["suggestion"]["category"] is None


def test_repeated_confirmations_and_notes_only_make_candidates():
    txs = [{"id": str(i), "normalized_counterparty": "Ravintola " + str(i)} for i in range(2)]
    reviews = [{"id": "r" + t["id"], "transaction_id": t["id"]} for t in txs]
    states = {
        t["id"]: (
            {
                "category": "OTHER",
                "context": "PERSONAL",
                "authority": {"category": "HUMAN_CONFIRMED"},
            },
            "v",
        )
        for t in txs
    }
    tables = {"transactions": txs, "transaction_label_reviews": reviews}
    candidates = generate_candidates(tables, states)
    assert len(candidates) == 1 and candidates[0]["authority"] == "SUGGESTED"
    txs[0]["normalized_counterparty"] = "Unclear"
    tables["confirmation_revisions"] = [
        {
            "id": "a",
            "sequence": 1,
            "transaction_id": "0",
            "fields": {"category": "OTHER"},
            "audit": {"correction_reason": "Ravintola is always other-personal"},
        }
    ]
    notes = generate_candidates(tables, states)
    assert notes and any(s["note"] for s in notes[0]["support"])
    assert notes[0]["authority"] == "SUGGESTED"


def store(tmp_path):
    import json

    c = candidate()
    (tmp_path / "candidates.json").write_text(json.dumps([c]))
    return ConceptReview(tmp_path, key=b"test-key"), c


def test_explicit_concept_confirmation_provenance_no_transaction_write(tmp_path):
    service, c = store(tmp_path)
    p = service.preview(
        {"candidate_id": "c", "action": "CONFIRM_CONCEPT", "concept": "RESTAURANT"}, "browser"
    )
    assert not service.events()
    event = service.commit(p["token"], "browser")
    assert service.commit(p["token"], "browser") == event
    claim = service.knowledge_events()[0].claims[0]
    assert claim.authority == "HUMAN_CONFIRMED" and claim.predicate == "semantic_concept"
    assert claim.provenance.confirmation_id == event["id"]
    assert claim.subject == "ravintola"


def test_edit_reject_defer_append_history_and_stale(tmp_path):
    s, c = store(tmp_path)
    old = s.preview(
        {"candidate_id": "c", "action": "CONFIRM_CONCEPT", "concept": "RESTAURANT"}, "b"
    )
    s.commit(old["token"], "b")
    p = s.preview(
        {"candidate_id": "c", "action": "EDIT_CONCEPT", "concept": "GENERAL_RETAILER"}, "b"
    )
    stale = s.preview({"candidate_id": "c", "action": "DEFER", "concept": "RESTAURANT"}, "b")
    s.commit(p["token"], "b")
    with pytest.raises(ValueError, match="STALE"):
        s.commit(stale["token"], "b")
    p = s.preview(
        {"candidate_id": "c", "action": "REJECT_CONCEPT", "concept": "GENERAL_RETAILER"}, "b"
    )
    s.commit(p["token"], "b")
    assert len(s.events()) == 3 and len(s.knowledge_events()) == 2
    result = apply_concepts(
        card(), {"id": "new", "normalized_counterparty": "Ravintola Gamma"}, [c], s.decisions()
    )
    assert result["suggestion"]["category"] is None
    assert len({digest(e) for e in s.events()}) == 3


def test_concept_token_browser_and_allowlist(tmp_path):
    s, _ = store(tmp_path)
    with pytest.raises(ValueError, match="ALLOWLIST"):
        s.preview(
            {"candidate_id": "arbitrary", "action": "CONFIRM_CONCEPT", "concept": "RESTAURANT"}, "a"
        )
    p = s.preview({"candidate_id": "c", "action": "DEFER", "concept": "RESTAURANT"}, "a")
    with pytest.raises(ValueError, match="INVALID"):
        s.commit(p["token"], "b")
