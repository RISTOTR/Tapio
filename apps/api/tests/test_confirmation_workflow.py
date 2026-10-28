"""Real commit/rollback/correction tests restricted to an isolated synthetic PostgreSQL schema."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.domain.models import ConfirmationRevision, Transaction
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_energy_load import factory as factory
from apps.api.tests.test_suggestion_cards import card, generator
from data_pipeline.load.bank import import_bank_bytes
from tapio.confirmation.replay import replay_confirmations
from tapio.confirmation.service import (
    Commit,
    ConfirmationService,
    Selection,
    review_state,
    row_data,
)
from tapio.knowledge.models import digest


@pytest.fixture
def setup(factory):
    key = "confirm-" + uuid4().hex
    result = import_bank_bytes(
        source_bytes([source_row(Arkistointitunnus=key)]),
        source_filename="synthetic.csv",
        account_key=key,
        session_factory=factory,
    )
    assert result.status == "imported"
    with factory() as db:
        tx = db.scalar(select(Transaction).where(Transaction.import_run_id == result.import_run_id))
        source = row_data(tx)
        current, version, _ = review_state(db, tx)
    c = card(generator()).model_dump(mode="json")
    c["card_id"] = key
    c["transaction"]["id"] = source["id"]
    c["source_hash"] = digest(source)
    c["initial_state_hash"] = version
    c["source_messages"] = {"Selitys": "Synthetic description", "Viesti": "Synthetic message"}
    batch = {"cards": [c], "cards_hash": digest([c])}
    return (
        ConfirmationService(
            factory, batch, signing_key=b"synthetic-test-key", enabled=lambda: True
        ),
        c,
        source,
    )


def selection(c, action="CONFIRM", fields=None, reason=""):
    return Selection(
        card_id=c["card_id"],
        action=action,
        fields={"category": "OTHER"} if fields is None else fields,
        correction_reason=reason,
    )


def apply(s, c, **kwargs):
    p = s.preview(selection(c, **kwargs), "browser")
    return p, s.commit(
        Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser"
    )


@pytest.mark.parametrize(
    "fields",
    [{"category": "OTHER"}, {"context": "PERSONAL"}, {"category": "OTHER", "context": "PERSONAL"}],
)
def test_confirm_independent_fields_source_unchanged(setup, factory, fields):
    s, c, source = setup
    p, r = apply(s, c, fields=fields)
    assert not p["persisted"] and r["status"] == "APPLIED"
    for f in ("category", "context"):
        assert r["state"][f] == fields.get(f)
        assert r["state"]["authority"][f] == ("HUMAN_CONFIRMED" if f in fields else "UNKNOWN")
    with factory() as db:
        tx = db.get(Transaction, source["id"])
        assert row_data(tx) == source
        rev = db.get(ConfirmationRevision, r["revision_id"])
        assert rev.audit["suggestion_snapshot"]["authority"] == "SUGGESTED"
        assert rev.audit["knowledge_event_ids"] == [r["knowledge_event_id"]]
        assert len(rev.knowledge_event["claims"]) == len(fields)


def test_change_correction_history_and_replay(setup, factory):
    s, c, source = setup
    _, first = apply(s, c, fields={"category": "OTHER", "context": "PERSONAL"})
    _, second = apply(
        s,
        c,
        action="CHANGE",
        fields={"category": "MAINTENANCE", "context": "PROPERTY"},
        reason="Explicit synthetic correction",
    )
    with factory() as db:
        rows = [
            row_data(r)
            for r in db.scalars(
                select(ConfirmationRevision)
                .where(ConfirmationRevision.transaction_id == source["id"])
                .order_by(ConfirmationRevision.sequence)
            )
        ]
    assert len(rows) == 2 and rows[1]["previous_id"] == first["revision_id"]
    assert rows[0]["state"]["context"] == "PERSONAL" and rows[1]["state"]["context"] == "PROPERTY"
    snap, _ = replay_confirmations([], rows, {source["id"]: "Tokmanni"})
    assert not snap.contradictions
    assert any(
        i.claim.value == "PROPERTY" and i.claim.kind == "MERCHANT_OBSERVATION" for i in snap.items
    )
    assert not any(i.claim.value == "PERSONAL" for i in snap.items)
    assert all(i.claim.predicate != "merchant_classification_rule" for i in snap.items)
    assert second["state"]["category"] == "MAINTENANCE"


def test_skip_disabled_and_feedback_not_authority(setup, factory):
    s, c, _ = setup
    p, r = apply(s, c, action="SKIP", fields={})
    assert (
        r == {"status": "SKIPPED", "classification_written": False} and p["event_preview"] is None
    )
    s.enabled = lambda: False
    p = s.preview(selection(c), "browser")
    with pytest.raises(ValueError, match="WRITES_DISABLED"):
        s.commit(Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser")
    for action in ["CORRECT", "PARTIALLY_USEFUL", "WRONG", "INSUFFICIENT_EVIDENCE"]:
        with pytest.raises(ValidationError):
            selection(c, action=action)
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConfirmationRevision)
                .where(ConfirmationRevision.transaction_id == c["transaction"]["id"])
            )
            == 0
        )


def test_stale_preview_idempotency_and_tampering(setup):
    s, c, _ = setup
    p = s.preview(selection(c), "browser")
    request = Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES")
    stale = s.preview(selection(c, action="CHANGE", fields={"category": "FUEL"}), "browser")
    assert s.commit(request, "browser")["status"] == "APPLIED"
    assert s.commit(request, "browser")["status"] == "ALREADY_APPLIED"
    with pytest.raises(ValueError, match="STALE_STATE"):
        s.commit(Commit(token=stale["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser")
    with pytest.raises(ValueError, match="INVALID_OR_EXPIRED"):
        s.commit(request, "another-browser")
    with pytest.raises(ValueError, match="INVALID_OR_EXPIRED"):
        s.commit(
            Commit(
                token=p["token"].replace("OTHER", "FUEL"), explicit_click="APPLY_DISPLAYED_CHANGES"
            ),
            "browser",
        )


def test_append_only_database_and_atomic_failure(setup, factory, monkeypatch):
    s, c, source = setup
    import tapio.confirmation.service as module

    original = module.KnowledgeEvent

    def fail(**kwargs):
        raise ValueError("synthetic event failure")

    monkeypatch.setattr(module, "KnowledgeEvent", fail)
    with pytest.raises(ValueError, match="synthetic event failure"):
        apply(s, c)
    with factory() as db:
        assert not db.scalar(
            select(ConfirmationRevision).where(ConfirmationRevision.transaction_id == source["id"])
        )
    monkeypatch.setattr(module, "KnowledgeEvent", original)
    _, r = apply(s, c)
    for sql in [
        "DELETE FROM confirmation_revisions WHERE id=:id",
        "UPDATE confirmation_revisions SET action=action WHERE id=:id",
    ]:
        with pytest.raises(DBAPIError), factory.begin() as db:
            db.execute(text(sql), {"id": r["revision_id"]})


def test_no_unlisted_or_ambiguous_cards_and_confirm_exact_value(setup):
    s, c, _ = setup
    with pytest.raises(ValueError, match="NOT_ALLOWLISTED"):
        s.preview(selection({**c, "card_id": "not-listed"}), "browser")
    with pytest.raises(ValueError, match="SHOWN_SUGGESTION"):
        s.preview(selection(c, fields={"category": "FUEL"}), "browser")
    bad = {**c, "transaction": {**c["transaction"], "merchant": "Paytrail Oyj"}}
    with pytest.raises(ValueError, match="UNSAFE_PREVIEW"):
        ConfirmationService(s.factory, {"cards": [bad], "cards_hash": digest([bad])})


def test_browser_requires_session_origin_and_csrf(setup, monkeypatch):
    from tapio.confirmation import api
    from tapio.pilot.api import app

    s, c, _ = setup
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    monkeypatch.setattr(api, "service", lambda: s)
    client = TestClient(app)
    data = client.get("/pilot/confirmation/cards").json()
    payload = selection(c).model_dump()
    assert client.post("/pilot/confirmation/preview", json=payload).status_code == 403
    headers = {"origin": "http://testserver", "X-Tapio-CSRF": data["csrf"]}
    p = client.post("/pilot/confirmation/preview", json=payload, headers=headers)
    assert p.status_code == 200 and not p.json()["persisted"]
    response = client.post(
        "/pilot/confirmation/commit",
        json={"token": p.json()["token"], "explicit_click": "APPLY_DISPLAYED_CHANGES"},
        headers=headers,
    )
    assert response.status_code == 200 and response.json()["status"] == "APPLIED"


def test_current_projection_and_labels_hidden(setup, factory):
    from tapio.pilot.transaction_search import SearchPlan, retrieve_search

    s, c, source = setup
    _, r = apply(s, c, action="CHANGE", fields={"category": "FUEL"})
    plan = SearchPlan(intent="TRANSACTION_SEARCH", terms=["FUEL"], date_range=None)
    found = retrieve_search(plan, factory)
    row = next(t for t in found["items"] if t["id"] == source["id"])
    assert row["category"] == "FUEL" and row["business_context"] is None
    assert row["field_authority"] == {"category": "HUMAN_CONFIRMED", "context": "UNKNOWN"}
    assert not any(
        t["id"] == source["id"] for t in retrieve_search(plan, factory, hide_labels=True)["items"]
    )
    assert r["state"]["context"] is None
