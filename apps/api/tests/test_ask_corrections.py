"""Ask correction writes use the existing append-only writer in disposable schemas."""

import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Transaction
from apps.api.tests.test_import_workspace import factory as factory
from apps.api.tests.test_import_workspace import queue as queue
from apps.api.tests.test_import_workspace import workflow as workflow
from tapio.confirmation.service import Commit
from tapio.pilot.corrections import Corrections, parse_correction

QUESTION = (
    "Change Synthetic queue shop transaction 15/01/2025 to category OTHER "
    "and business context FORESTRY"
)


def test_parse_exact_request_and_independent_fields():
    p = parse_correction(
        "Change Example Shop Oy transaction 22/05/2026 to be Category OTHER\n"
        "Business context FORESTRY."
    )
    assert p["merchant"] == "Example Shop Oy" and str(p["date"]) == "2026-05-22"
    assert p["fields"] == {"category": "OTHER", "context": "FORESTRY"}
    assert parse_correction("Change Example Shop transaction 2026-05-22 category OTHER")[
        "fields"
    ] == {"category": "OTHER"}
    assert parse_correction("Show forestry expenses in 2026") is None


@pytest.mark.parametrize(
    "question",
    [
        "Change Example Shop category OTHER",
        "Change Example Shop May 2026 category OTHER",
        "Change Example Shop 22/05/2026 category INVALID",
        "Change Example Shop 22/05/2026 category OTHER category TAX",
        "Change Example Shop 22/05/2026 category OTHER and delete records",
    ],
)
def test_ambiguous_or_unsupported_corrections_fail_closed(question):
    with pytest.raises(ValueError):
        parse_correction(question)


def request(c, sid="browser", question=QUESTION):
    resolved = c.resolve(question, sid)
    assert len(resolved["candidates"]) == 35  # Must choose, never write all matches.
    tx = resolved["candidates"][0]["id"]
    p = c.preview(resolved["ticket"], tx, sid)
    return resolved["ticket"], tx, p


def apply(c, ticket, tx, preview, sid="browser"):
    return c.commit(
        ticket, tx, Commit(token=preview["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), sid
    )


def test_preview_write_correction_retry_and_current_projection(workflow):
    from tapio.confirmation.projection import current_classified_transactions

    c = Corrections(workflow.queue)
    before = workflow.read_tables()
    ticket, tx, p = request(c)
    assert workflow.read_tables() == before
    assert p["would_change"]["context"]["new"] == "FORESTRY"
    result = apply(c, ticket, tx, p)
    assert result["status"] == "APPLIED"
    assert apply(c, ticket, tx, p)["status"] == "ALREADY_APPLIED"
    # Fully reviewed transaction can be corrected again; omitted context is preserved.
    ticket2, tx2, p2 = request(
        c, question=QUESTION.split(" and business")[0].replace("OTHER", "TRAVEL")
    )
    assert tx2 == tx and p2["untouched_fields"] == ["context"]
    result = apply(c, ticket2, tx, p2)
    assert result["state"]["category"] == "TRAVEL" and result["state"]["context"] == "FORESTRY"
    after = workflow.read_tables()
    for table in before:
        if table != "confirmation_revisions":
            assert after[table] == before[table]
    with workflow.queue.factory() as db:
        tx_row, review = current_classified_transactions(db, [], transaction_ids=[tx])[0]
        assert review.confirmed_category == "TRAVEL"
        rows = db.scalars(
            select(ConfirmationRevision)
            .where(ConfirmationRevision.transaction_id == tx_row.id)
            .order_by(ConfirmationRevision.sequence)
        ).all()
        assert len(rows) == 2 and rows[1].previous_id == rows[0].id
        assert rows[1].audit["old_values"]["category"] == "OTHER"
        assert rows[1].audit["correction_reason"]
        assert all(claim["subject"] == tx for claim in rows[1].knowledge_event["claims"])


def test_stale_preview_foreign_session_and_wrong_transaction(workflow):
    c = Corrections(workflow.queue)
    ticket, tx, p = request(c)
    with pytest.raises(ValueError):
        c.preview(ticket, str(uuid4()), "browser")
    with pytest.raises(ValueError):
        apply(c, ticket, tx, p, "other")
    other, _, newer = request(c)
    apply(c, other, tx, newer)
    with pytest.raises(ValueError, match="STALE"):
        apply(c, ticket, tx, p)


def test_disabled_and_expired_cannot_write(workflow, monkeypatch):
    c = Corrections(workflow.queue)
    ticket, tx, p = request(c)
    monkeypatch.setattr(workflow.queue, "enabled", lambda: False)
    # Existing service retains bound callable; change its gate to model runtime seal revocation.
    c.pending[ticket]["services"][tx].enabled = workflow.queue.enabled
    with pytest.raises(ValueError, match="DISABLED"):
        apply(c, ticket, tx, p)
    c.pending[ticket]["expires"] = time.time() - 1
    with pytest.raises(ValueError, match="expired"):
        apply(c, ticket, tx, p)


def test_source_change_after_preview_is_rejected(workflow):
    from uuid import UUID

    c = Corrections(workflow.queue)
    ticket, tx, p = request(c)
    service = c.pending[ticket]["services"][tx]
    with workflow.queue.factory.begin() as db:
        row = db.get(Transaction, UUID(tx))
        row.message = "Changed synthetic source"
    with pytest.raises(ValueError, match="STALE"):
        service.commit(
            Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser"
        )


def test_http_csrf_and_explicit_click_required(workflow, monkeypatch):
    from tapio.pilot import corrections as module

    c = Corrections(workflow.queue)
    monkeypatch.setattr(module, "corrections", lambda: c)
    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)
    assert client.post("/pilot/corrections/resolve", json={"question": QUESTION}).status_code == 403
    csrf = client.get("/pilot/corrections/session").json()["csrf"]
    headers = {"Origin": "http://testserver", "X-Tapio-CSRF": csrf}
    d = client.post(
        "/pilot/corrections/resolve", json={"question": QUESTION}, headers=headers
    ).json()
    body = {"ticket": d["ticket"], "transaction_id": d["candidates"][0]["id"]}
    p = client.post("/pilot/corrections/preview", json=body, headers=headers).json()
    assert (
        client.post(
            "/pilot/corrections/commit",
            json={**body, "commit": {"token": p["token"]}},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/pilot/corrections/commit",
            json={
                **body,
                "commit": {"token": p["token"], "explicit_click": "APPLY_DISPLAYED_CHANGES"},
            },
            headers=headers,
        ).status_code
        == 200
    )


def test_correction_browser(workflow):
    import os
    import subprocess

    result = subprocess.run(
        [os.environ.get("TAPIO_BROWSER_NODE", "node"), "apps/api/tests/js/correction_browser.cjs"],
        env={
            **os.environ,
            "BROWSER_TEST_DATABASE_URL": workflow.queue.factory.kw["bind"].url.render_as_string(
                hide_password=False
            ),
            "IMPORT_TEST_ROOT": str(workflow.queue.root),
        },
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CORRECTION_BROWSER_PASS" in result.stdout
