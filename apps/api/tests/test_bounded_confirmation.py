"""Frozen larger batches and partial review safety; all DB writes use disposable fixtures."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Transaction
from apps.api.tests.test_confirmation_workflow import apply
from apps.api.tests.test_confirmation_workflow import setup as setup
from apps.api.tests.test_controlled_confirmation import factory as factory
from apps.api.tests.test_general_confirmation import candidate, general_service
from apps.api.tests.test_suggestion_cards import NOW, generator, review, tx
from tapio.confirmation.batch import freeze_batch, prepare_candidates
from tapio.confirmation.outcomes import outcome_metrics
from tapio.confirmation.service import Commit, ConfirmationService, review_state, row_data
from tapio.knowledge.models import digest


def bounded_service(setup, *, partial=False):
    original, c, source = general_service(setup)
    baseline = {}
    if partial:
        apply(original, c, fields={"category": "OTHER"})
        with original.factory() as db:
            state, version, _ = review_state(db, db.get(Transaction, source["id"]))
            baseline = {
                str(r.id): digest(row_data(r)) for r in db.scalars(select(ConfirmationRevision))
            }
        c["current_state"] = state
        c["initial_state_hash"] = version
        c["suggestion"].update(category=None, context="PERSONAL")
    cards = [c]
    for _ in range(29):
        clone = deepcopy(c)
        clone["card_id"] = str(uuid4())
        clone["transaction"]["id"] = str(uuid4())
        cards.append(clone)
    batch = {
        "version": "BOUNDED_CONFIRMATION_V1",
        "batch_id": "SYNTHETIC_BOUNDED",
        "cards": cards,
        "cards_hash": digest(cards),
        "baseline_revisions": baseline,
    }
    return ConfirmationService(original.factory, batch, enabled=lambda: True), c, source


@pytest.mark.parametrize("size", [25, 30, 50])
def test_bounded_freeze(size):
    cards = [candidate(i, ["ABSTENTION"]) for i in range(50)]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    batch = freeze_batch(cards, "knowledge", {}, {}, size=size, bounded=True, created_at=now)
    assert len(batch["cards"]) == size and batch["created_at"] == now.isoformat()
    assert batch["version"] == "BOUNDED_CONFIRMATION_V1"
    cards[0]["transaction"]["id"] = "changed"
    assert digest(batch["cards"]) == batch["cards_hash"]


@pytest.mark.parametrize("size", [24, 51])
def test_outside_bounded_limit_rejected(size):
    with pytest.raises(ValueError):
        freeze_batch(
            [candidate(i, []) for i in range(60)], "k", {}, {}, size, bounded=True, created_at=NOW
        )


def test_partial_eligibility_keeps_confirmed_field_authoritative():
    rows = [tx(1, "Synthetic merchant"), tx(2, "Synthetic merchant")]
    for row in rows:
        row.update(source_transaction_id="synthetic-" + row["id"], amount="-12.34")
    reviews = [review(1, "OTHER", context=None), review(2, "OTHER", context="UNKNOWN")]
    g = generator(rows, reviews)
    states = {
        "1": (
            {
                "category": "OTHER",
                "context": None,
                "authority": {"category": "HUMAN_CONFIRMED", "context": "UNKNOWN"},
            },
            "v1",
        ),
        "2": (
            {
                "category": "OTHER",
                "context": "UNKNOWN",
                "authority": {"category": "HUMAN_CONFIRMED", "context": "HUMAN_CONFIRMED"},
            },
            "v2",
        ),
    }
    tables = {
        "transactions": rows,
        "transaction_label_reviews": reviews,
        "confirmation_revisions": [{"transaction_id": "1"}, {"transaction_id": "2"}],
    }
    cards = prepare_candidates(tables, g.snapshot, NOW, states, bounded=True)
    assert len(cards) == 1 and cards[0]["transaction"]["id"] == "1"
    assert cards[0]["suggestion"]["category"] is None
    assert cards[0]["current_state"]["category"] == "OTHER"


def test_partial_baseline_is_ready_and_completion_appends(setup, factory):
    s, c, source = bounded_service(setup, partial=True)
    assert s.card_status(c["card_id"])["write_state"] == "READY_TO_CONFIRM"
    _, result = apply(s, c, fields={"context": "PERSONAL"})
    assert result["state"]["category"] == "OTHER"
    with factory() as db:
        rows = [
            row_data(r)
            for r in db.scalars(
                select(ConfirmationRevision).order_by(ConfirmationRevision.sequence)
            )
        ]
    assert len(rows) == 2 and rows[1]["previous_id"] == rows[0]["id"]
    assert digest(rows[0]) == s.batch["baseline_revisions"][rows[0]["id"]]
    assert rows[1]["audit"]["field_outcomes"] == {
        "category": "NOT_APPLICABLE",
        "context": "SUGGESTION_ACCEPTED",
    }
    assert (
        "SUGGESTION_ACCEPTED"
        in rows[1]["knowledge_event"]["claims"][0]["provenance"]["extraction_method"]
    )
    assert rows[1]["transaction_id"] == source["id"]


def test_stale_receipt_and_suggestion_block_before_write(setup, factory):
    s, c, _ = bounded_service(setup)
    s.evidence_check = lambda card: True
    p = s.preview(
        {"card_id": c["card_id"], "action": "CONFIRM", "fields": {"category": "OTHER"}}, "browser"
    )
    s.evidence_check = lambda card: False
    with pytest.raises(ValueError, match="STALE_STATE_RECEIPT"):
        s.commit(Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser")
    with factory() as db:
        assert not list(db.scalars(select(ConfirmationRevision)))
    s.evidence_check = lambda card: True
    c["suggestion"]["category"] = "FUEL"
    with pytest.raises(ValueError, match="STALE_STATE_EVIDENCE"):
        s.preview({"card_id": c["card_id"], "action": "SKIP"}, "browser")


def test_primary_metrics_do_not_count_manual_completion_as_changed():
    cards = {"a": {"card_id": "a", "suggestion": {"category": "OTHER"}, "current_state": {}}}
    rows = [
        {
            "sequence": 1,
            "audit": {
                "card_id": "a",
                "field_outcomes": {
                    "category": "SUGGESTION_ACCEPTED",
                    "context": "MANUALLY_COMPLETED",
                },
            },
        }
    ]
    result = outcome_metrics(cards, rows, set())
    assert result["suggested_fields_accepted"] == 1
    assert result["suggested_fields_changed"] == 0
    assert result["unsuggested_fields_manually_completed"] == 1


def test_new_revision_from_other_batch_is_stale_before_preview(setup, factory):
    s, c, _ = bounded_service(setup)
    original, original_card, _ = setup
    apply(original, original_card, fields={"category": "OTHER"})
    assert s.card_status(c["card_id"])["write_state"] == "STALE"
    with pytest.raises(ValueError, match="STALE_CARD"):
        s.preview(
            {"card_id": c["card_id"], "action": "CHANGE", "fields": {"context": "PERSONAL"}},
            "browser",
        )
