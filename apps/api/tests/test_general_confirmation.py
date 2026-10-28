"""Bounded general review safety, using synthetic sources and disposable schemas."""

from copy import deepcopy
from uuid import uuid4

import pytest

from apps.api.tests.test_confirmation_workflow import apply
from apps.api.tests.test_confirmation_workflow import setup as setup
from apps.api.tests.test_controlled_confirmation import factory as factory
from apps.api.tests.test_suggestion_cards import NOW, generator, review, tx
from tapio.confirmation.batch import freeze_batch, prepare_candidates
from tapio.confirmation.controlled import general_metrics
from tapio.confirmation.service import ConfirmationService, Selection
from tapio.knowledge.models import digest


def candidate(i, tags):
    return {"card_id": str(i), "transaction": {"id": str(i)}, "pilot_tags": tags}


def test_freeze_is_bounded_stable_and_detached():
    cards = [candidate(i, ["BOTH"]) for i in range(25)]
    cards[24]["pilot_tags"] = ["DOCUMENT", "CONTEXT_ONLY"]
    frozen = freeze_batch(cards, "knowledge", {}, {}, 20)
    assert len(frozen["cards"]) == 20
    assert frozen["composition"]["DOCUMENT"] == 1
    assert frozen == freeze_batch(cards, "knowledge", {}, {}, 20)
    cards[24]["pilot_tags"].append("MUTATED")
    assert "MUTATED" not in frozen["cards"][0]["pilot_tags"]
    with pytest.raises(ValueError):
        freeze_batch(cards, "knowledge", {}, {}, 26)


def test_paytrail_and_multi_context_gate_without_tax_inference():
    rows = [tx(i, "Paytrail Oyj") for i in range(1, 7)] + [tx(7, "Tokmanni"), tx(8, "Tokmanni")]
    for t, recipient in zip(
        rows,
        [
            "Shop Alpha",
            "Shop Alpha",
            "Shop Beta / Prepaid",
            "Shop Beta / Prepaid",
            "Unknown",
            "Unclear",
            "",
            "",
        ],
        strict=True,
    ):
        t.update(
            amount="-12.34",
            source_transaction_id="archive-" + t["id"],
            raw_source={"Viesti": "Lopullinen saaja: " + recipient},
        )
    reviews = [review(1, "FUEL"), review(3, "SUBSCRIPTION"), review(7, "MAINTENANCE", "FORESTRY")]
    g = generator(rows, reviews)
    tables = {"transactions": rows, "transaction_label_reviews": reviews}
    states = {t["id"]: ({"category": None, "context": None}, "version") for t in rows}
    cards = prepare_candidates(tables, g.snapshot, NOW, states)
    by_id = {c["transaction"]["id"]: c for c in cards}
    assert by_id["2"]["paytrail_purpose"] == "PARTIAL_PURPOSE"
    assert by_id["2"]["suggestion"]["category"] == "FUEL"
    assert by_id["4"]["paytrail_purpose"] == "PURPOSE_VISIBLE"
    assert by_id["4"]["suggestion"]["category"] == "SUBSCRIPTION"
    assert by_id["5"]["paytrail_purpose"] == "STILL_OPAQUE"
    assert by_id["5"]["suggestion"]["category"] is None
    assert by_id["8"]["multi_context"] and by_id["8"]["suggestion"]["context"] is None
    assert all(set(c["suggestion"]) == {"category", "context", "authority"} for c in cards)
    assert all(c["suggestion"]["authority"] == "SUGGESTED" for c in cards)
    assert not {"1", "3", "7"} & by_id.keys()
    rows[1]["amount"] = "-588.07"
    tables["transaction_reversal_candidates"] = [{"debit_id": "4", "credit_id": "6"}]
    ids = {c["transaction"]["id"] for c in prepare_candidates(tables, g.snapshot, NOW, states)}
    assert not {"2", "4", "6"} & ids


def general_service(setup, abstain=False):
    original, c, source = setup
    c = deepcopy(c)
    c.update(source_stable_id="synthetic", multi_context=False, paytrail_purpose=None)
    c["transaction"]["amount"] = source["amount"]
    c["current_state"] = {"category": None, "context": None}
    if abstain:
        c["suggestion"].update(category=None, context=None)
        c["paytrail_purpose"] = "STILL_OPAQUE"
    cards = [c]
    for i in range(14):
        extra = deepcopy(c)
        extra["card_id"] = str(uuid4())
        extra["transaction"]["id"] = str(uuid4())
        extra["source_stable_id"] = str(i)
        cards.append(extra)
    batch = {
        "version": "GENERAL_CONFIRMATION_V1",
        "batch_id": "SYNTHETIC_GENERAL",
        "cards": cards,
        "cards_hash": digest(cards),
    }
    return ConfirmationService(original.factory, batch, enabled=lambda: True), c, source


def test_abstention_manual_change_and_audit(setup, factory):
    from sqlalchemy import select

    from apps.api.app.domain.models import ConfirmationRevision, Transaction
    from tapio.confirmation.service import row_data

    s, c, source = general_service(setup, abstain=True)
    with pytest.raises(ValueError, match="SHOWN_SUGGESTION"):
        apply(s, c)
    _, result = apply(s, c, action="CHANGE", fields={"category": "FUEL"})
    assert result["state"]["context"] is None
    with factory() as db:
        r = db.scalar(select(ConfirmationRevision))
        assert r.audit["batch_id"] == "SYNTHETIC_GENERAL"
        assert r.audit["reason_codes"] == c["reasons"]
        assert r.audit["suggestion_snapshot"]["category"] is None
        assert len(r.knowledge_event["claims"]) == 1
        assert row_data(db.get(Transaction, source["id"])) == source


def test_general_allowlist_and_suggestion_field_restriction(setup):
    s, c, _ = general_service(setup)
    c["suggestion"]["context"] = None
    with pytest.raises(ValueError, match="SHOWN_SUGGESTION"):
        apply(s, c, fields={"context": "PERSONAL"})
    with pytest.raises(ValueError, match="NOT_ALLOWLISTED"):
        s.preview(Selection(card_id="outside", action="SKIP"), "browser")
    _, result = apply(s, c, fields={"category": "OTHER"})
    assert result["state"]["context"] is None
    tampered = deepcopy(s.batch)
    tampered["cards"][0]["source_messages"]["Viesti"] = "changed"
    with pytest.raises(ValueError, match="BATCH_HASH"):
        ConfirmationService(s.factory, tampered)


def test_outcome_metrics_distinguish_abstention_and_manual_fields():
    cards = {
        "a": {
            "suggestion": {"category": None, "context": None},
            "reasons": [],
            "paytrail_purpose": "STILL_OPAQUE",
        },
        "b": {
            "suggestion": {"category": "FUEL", "context": None},
            "reasons": [{"code": "SOURCE_MESSAGE_MATCH"}],
            "multi_context": True,
        },
    }
    row = {
        "sequence": 1,
        "audit": {"card_id": "b"},
        "state": {"category": "FUEL", "context": "PROPERTY"},
    }
    result = general_metrics(cards, [row], {"a"})
    assert result["suggestion_vs_final"] == {
        "no_suggestion_skipped": 1,
        "suggestion_partially_changed": 1,
    }
    assert result["paytrail_skips"] == 1 and result["multi_context_cases"] == 1


def test_disposable_general_correction_preserves_history(setup, factory):
    from sqlalchemy import select

    from apps.api.app.domain.models import ConfirmationRevision
    from tapio.confirmation.replay import replay_confirmations
    from tapio.confirmation.service import row_data

    s, c, source = general_service(setup)
    apply(s, c, fields={"category": "OTHER", "context": "PERSONAL"})
    apply(
        s, c, action="CHANGE", fields={"context": "PROPERTY"}, reason="Disposable correction test"
    )
    with factory() as db:
        rows = [
            row_data(r)
            for r in db.scalars(
                select(ConfirmationRevision).order_by(ConfirmationRevision.sequence)
            )
        ]
    assert len(rows) == 2 and rows[0]["state"]["context"] == "PERSONAL"
    assert rows[1]["state"]["context"] == "PROPERTY" and rows[1]["state"]["category"] == "OTHER"
    snapshot, _ = replay_confirmations([], rows, {source["id"]: "Synthetic merchant"})
    assert not any(i.claim.value == "PERSONAL" for i in snapshot.items)
    assert all(
        i.claim.scope == source["id"]
        for i in snapshot.items
        if i.claim.kind == "MERCHANT_OBSERVATION"
    )
    assert s.card_status(c["card_id"])["write_state"] == "CHANGED"
