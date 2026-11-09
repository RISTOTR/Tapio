"""Final reconciliation must preserve decisions and reject stale pending review cards."""

import json

import pytest
from sqlalchemy import select

from apps.api.app.domain.models import Document
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_group_review import factory as factory
from apps.api.tests.test_group_review import grouped as grouped
from apps.api.tests.test_group_review import queue as queue
from data_pipeline.load.bank import import_bank_bytes
from tapio.confirmation.groups import GroupReview
from tapio.confirmation.reconciliation import exit_decision, review_metrics
from tapio.confirmation.service import Commit, Selection


def test_completed_history_stays_out_when_new_transaction_arrives(grouped):
    g, old = grouped
    p = g.preview(old["plan_id"], old["groups"][0]["id"], "browser")
    g.commit(old["plan_id"], p["token"], "browser")
    empty = g.live(old["plan_id"])
    assert empty["summary"]["total_pending"] == 0
    assert exit_decision(empty)["status"] == "READY_FOR_ONGOING_REVIEW_MODE"
    assert exit_decision(empty, accidental_unknown=1)["status"] == "HISTORICAL_REVIEW_MODE"
    result = import_bank_bytes(
        source_bytes(
            [
                source_row(
                    Arkistointitunnus="ongoing-new-transaction",
                    **{"Saaja/Maksaja": "New synthetic entity"},
                )
            ]
        ),
        source_filename="ongoing.csv",
        account_key="queue-test",
        session_factory=g.queue.factory,
    )
    assert result.status == "imported"
    new = GroupReview(g.queue).live(empty["plan_id"])
    assert new["budget"] == 5
    assert len(new["cards"]) == 1
    assert new["cards"][0]["transaction"]["id"] not in {
        c["transaction"]["id"] for c in old["cards"]
    }
    assert exit_decision(new)["status"] == "HISTORICAL_REVIEW_MODE"


def test_stale_manual_pending_preview_and_commit_are_blocked(grouped):
    g, old = grouped
    _, s = g.get(old["plan_id"])
    selections = [
        Selection(
            card_id=c["card_id"],
            action="CHANGE",
            fields={"category": "OTHER", "context": "PERSONAL"},
            touched_fields=["category", "context"],
            correction_reason="Synthetic decision",
            review_version=s.current_review(c["card_id"])["review_version"],
        )
        for c in old["cards"][:2]
    ]
    previews = [
        g.individual_preview(old["plan_id"], selection, "browser") for selection in selections
    ]
    g.individual_commit(
        old["plan_id"],
        Commit(token=previews[0]["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
        "browser",
    )
    with pytest.raises(ValueError, match="STALE_PENDING"):
        g.individual_preview(old["plan_id"], selections[1], "browser")
    with pytest.raises(ValueError, match="STALE_GROUP_HISTORY"):
        g.individual_commit(
            old["plan_id"],
            Commit(token=previews[1]["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
            "browser",
        )
    # Retrying an already saved decision is still idempotent.
    g.individual_commit(
        old["plan_id"],
        Commit(token=previews[0]["token"], explicit_click="APPLY_DISPLAYED_CHANGES"),
        "browser",
    )
    fresh = g.live(old["plan_id"])
    assert fresh["summary"]["total_pending"] == 2


def test_metrics_distinguish_grouped_members_from_avoided_confirmations(grouped):
    g, old = grouped
    p = g.preview(old["plan_id"], old["groups"][0]["id"], "browser")
    g.commit(old["plan_id"], p["token"], "browser")
    with g.queue.factory() as db:
        tables = {
            name: [dict(r) for r in db.execute(select(Document.metadata.tables[name])).mappings()]
            for name in ["transactions", "transaction_label_reviews", "confirmation_revisions"]
        }
    metrics = review_metrics(json.loads(json.dumps(tables, default=str)))
    assert metrics["historical_transactions_reviewed"] == 3
    assert metrics["remaining_unresolved"] == 0
    assert metrics["grouped_confirmation_transactions"] == 3
    assert metrics["separate_confirmations_avoided"] == 2
    assert metrics["estimated_manual_actions_saved"] == 10
    assert metrics["grouped_confirmation_rate"] == 1
    assert metrics["repeated_review_rate"] == 0
