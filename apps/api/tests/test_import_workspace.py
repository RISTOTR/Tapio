"""Browser import boundaries using real loader + ongoing review in disposable schemas."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_group_review import factory as factory
from apps.api.tests.test_group_review import queue as queue
from data_pipeline.labels.snapshot import fingerprint
from tapio.confirmation.groups import GroupReview
from tapio.importing.service import ImportWorkflow, review_summary


@pytest.fixture
def workflow(queue, monkeypatch):
    w = ImportWorkflow(queue)
    before = w.read_tables()
    names = [n for n in before if n != "confirmation_revisions"]
    queue.save_manifest(
        {**queue.manifest(), "source_fingerprints": {n: fingerprint(before[n]) for n in names}}
    )

    # Real per-table verification against each test queue's own signed source state.
    def verify(group):
        expected = group.queue.manifest()["source_fingerprints"]
        tables = w.read_tables()
        actual = {n: fingerprint(tables[n]) for n in expected}
        assert actual == expected
        return actual

    monkeypatch.setattr(GroupReview, "verify_sources", verify)
    return w


def csv(identity="browser-new", **kwargs):
    return source_bytes([source_row(Arkistointitunnus=identity, **kwargs)])


def preview(w, raw):
    return w.preview(raw, "new.csv", "queue-test", "browser")


def test_preview_valid_date_range_no_write(workflow):
    before = workflow.read_tables()
    p = preview(
        workflow,
        source_bytes(
            [
                source_row(Arkistointitunnus="a"),
                source_row(Arkistointitunnus="b", **{"Kirjauspäivä": "2025-02-20"}),
            ]
        ),
    )
    assert p["validation"] == "VALID" and p["new_rows"] == 2
    assert (p["date_from"], p["date_to"]) == ("2025-01-15", "2025-02-20")
    assert workflow.read_tables() == before
    assert not workflow.root.exists()


@pytest.mark.parametrize(
    "raw,state",
    [
        (b"wrong;headers\nx;y", "UNSUPPORTED"),
        (b"", "INVALID"),
        (csv(**{"Määrä EUROA": "not-money"}), "INVALID"),
    ],
)
def test_invalid_validation_no_write(workflow, raw, state):
    before = workflow.read_tables()
    p = preview(workflow, raw)
    assert p["validation"] == state and "token" not in p
    assert workflow.read_tables() == before


def test_mixed_append_provenance_ongoing_and_retry(workflow):
    before = workflow.read_tables()
    windows = deepcopy(workflow.queue.manifest()["windows"])
    raw = source_bytes(
        [
            source_row(
                Arkistointitunnus="queue-synthetic-0", **{"Saaja/Maksaja": "Synthetic queue shop"}
            ),
            source_row(Arkistointitunnus="new-source", **{"Viesti": "Original source message"}),
        ]
    )
    p = preview(workflow, raw)
    assert (p["duplicates"], p["new_rows"]) == (1, 1)
    result = workflow.commit(p["token"], "browser")
    assert result["new_rows"] == 1 and result["review_items"] == 1
    after = workflow.read_tables()
    for name, rows in before.items():
        current = {r["id"]: r for r in after[name]}
        assert all(current[r["id"]] == r for r in rows)
    assert len(after["transactions"]) == len(before["transactions"]) + 1
    assert len(after["confirmation_revisions"]) == len(before["confirmation_revisions"])
    tx = next(r for r in after["transactions"] if r["source_transaction_id"] == "new-source")
    assert (
        tx["raw_source"]["Viesti"] == "Original source message" and tx["source_file"] == "new.csv"
    )
    assert workflow.queue.manifest()["windows"] == windows
    assert workflow.commit(p["token"], "browser") == result
    assert workflow.history()["recent"][0]["new_rows"] == 1


def test_all_duplicate_normal_completion_no_source_writes(workflow):
    raw = csv("queue-synthetic-0", **{"Saaja/Maksaja": "Synthetic queue shop"})
    before = workflow.read_tables()
    p = preview(workflow, raw)
    assert p["new_rows"] == 0 and p["duplicates"] == 1
    result = workflow.commit(p["token"], "browser")
    assert result["review_items"] == 0 and result["new_rows"] == 0
    assert workflow.read_tables() == before
    again = preview(workflow, raw)
    workflow.commit(again["token"], "browser")
    assert workflow.read_tables() == before


def test_conflicting_overlap_fails_before_write(workflow):
    p = preview(workflow, csv("queue-synthetic-0", **{"Määrä EUROA": "-999,99"}))
    assert p["validation"] == "INVALID" and "different source fields" in p["message"]


def test_stale_and_foreign_preview_rejected(workflow):
    p = preview(workflow, csv())
    with pytest.raises(ValueError, match="EXPIRED"):
        workflow.commit(p["token"], "another-browser")
    workflow.previews[p["token"]]["state"] = "stale"
    with pytest.raises(ValueError, match="STALE"):
        workflow.commit(p["token"], "browser")
    assert not workflow.root.exists()


def test_recovery_after_database_commit_without_duplicate(workflow, monkeypatch):
    import tapio.importing.service as module

    p = preview(workflow, csv())
    real = module.accept_bank_import
    monkeypatch.setattr(
        module, "accept_bank_import", lambda *a: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(OSError):
        workflow.commit(p["token"], "browser")
    after = workflow.read_tables()
    assert len(workflow.history()["pending"]) == 1
    monkeypatch.setattr(module, "accept_bank_import", real)
    restarted = ImportWorkflow(workflow.queue)
    result = restarted.commit(p["token"], "new-browser-after-restart")
    assert result["new_rows"] == 1 and restarted.read_tables() == after


def test_zero_review_summary_is_not_error():
    plan = {
        "cards": [],
        "groups": [],
        "excluded": [],
        "individual_ids": [],
        "summary": {"total_pending": 0},
    }
    assert review_summary(plan, set())["pending_total"] == 0
    assert review_summary(plan, set())["review_items"] == 0


def test_http_csrf_explicit_action_and_import_route(workflow, monkeypatch):
    from tapio.importing import api as imports
    from tapio.pilot.api import app

    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    monkeypatch.setattr(imports, "workflow", lambda: workflow)
    client = TestClient(app)
    assert client.get("/app/import").status_code == 200
    token = client.get("/app/import/status").json()["csrf"]
    assert client.post("/app/import/preview?account=queue-test", content=csv()).status_code == 403
    headers = {"Origin": "http://testserver", "X-Tapio-CSRF": token, "X-Filename": "source.csv"}
    p = client.post("/app/import/preview?account=queue-test", content=csv(), headers=headers).json()
    assert p["validation"] == "VALID"
    assert (
        client.post("/app/import/commit", headers=headers, json={"token": p["token"]}).status_code
        == 422
    )
    result = client.post(
        "/app/import/commit",
        headers=headers,
        json={"token": p["token"], "confirmation": "IMPORT_AND_ANALYZE"},
    )
    assert result.status_code == 200 and result.json()["new_rows"] == 1


def test_real_import_ask_browser(workflow, tmp_path):
    import os
    import subprocess

    from apps.api.tests.test_user_rules import rule

    q = workflow.queue
    q.rules.root.mkdir(exist_ok=True)
    candidate = {
        "id": "import-browser-rule",
        "rule": rule("Synthetic queue shop"),
        "support": [],
        "semantic_facts": [],
    }
    (q.rules.root / "candidates.json").write_text(json.dumps([candidate]))
    p = q.rules.preview(
        {
            "candidate_id": candidate["id"],
            "action": "CONFIRM_RULE",
            "rule": candidate["rule"],
            "expected_state": "PENDING",
        },
        "test",
    )
    q.rules.commit(p["token"], "test")
    group = GroupReview(q)
    plan = group.build()
    p = group.preview(plan["plan_id"], plan["groups"][0]["id"], "test")
    group.commit(plan["plan_id"], p["token"], "test")
    assert GroupReview(q).build()["summary"]["total_pending"] == 0
    duplicate = source_row(
        Arkistointitunnus="queue-synthetic-0", **{"Saaja/Maksaja": "Synthetic queue shop"}
    )
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("unsupported;headers\na;b")
    dup = tmp_path / "duplicate.csv"
    dup.write_bytes(source_bytes([duplicate]))
    new = tmp_path / "monthly.csv"
    new.write_bytes(
        source_bytes(
            [
                duplicate,
                *[
                    source_row(
                        Arkistointitunnus="browser-month-" + str(i),
                        **{"Saaja/Maksaja": "Synthetic queue shop"},
                    )
                    for i in range(2)
                ],
            ]
        )
    )
    env = {
        **os.environ,
        "BROWSER_TEST_DATABASE_URL": q.factory.kw["bind"].url.render_as_string(hide_password=False),
        "IMPORT_TEST_ROOT": str(q.root),
        "IMPORT_INVALID_CSV": str(invalid),
        "IMPORT_DUPLICATE_CSV": str(dup),
        "IMPORT_NEW_CSV": str(new),
    }
    result = subprocess.run(
        ["node", "apps/api/tests/js/import_browser.cjs"],
        env=env,
        capture_output=True,
        text=True,
        timeout=480,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "IMPORT_ASK_BROWSER_PASS" in result.stdout
