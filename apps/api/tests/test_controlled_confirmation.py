"""Controlled pilot reports and per-card states; synthetic isolated database only."""

import json

import pytest

from apps.api.tests.test_confirmation_workflow import apply, selection
from apps.api.tests.test_confirmation_workflow import setup as setup
from apps.api.tests.test_energy_load import factory as schema_factory
from tapio.confirmation.controlled import ControlledPilot
from tapio.confirmation.service import Commit
from tapio.knowledge.store import load_bundle, save_bundle


@pytest.fixture
def factory():
    # This pilot deliberately rejects any revision outside its fixed allowlist;
    # give every scenario its own database schema, not shared prior test rows.
    yield from schema_factory.__wrapped__()


@pytest.fixture
def monitored(setup, tmp_path, monkeypatch):
    s, c, source = setup
    base = tmp_path / "base"
    snapshot = save_bundle(base / "knowledge", [])
    (base / "knowledge_diff.json").write_text(json.dumps({"new_events_hash": snapshot.events_hash}))
    monitor = ControlledPilot(s, tmp_path / "pilot", base)
    monkeypatch.setattr(monitor, "verify_sources", lambda: {"synthetic": "unchanged"})
    s.monitor = monitor
    return s, c, source


def test_get_states_no_write_and_independent_confirmation(monitored):
    s, c, _ = monitored
    assert s.card_status(c["card_id"])["write_state"] == "READY_TO_CONFIRM"
    assert not s.monitor.root.exists()
    _, result = apply(s, c, fields={"category": "OTHER"})
    assert result["verification"]["unrelated_rows_changed"] == 0
    status = s.card_status(c["card_id"])
    assert status["write_state"] == "CONFIRMED"
    assert status["current_state"]["context"] is None
    report = json.loads((s.monitor.root / "report.json").read_text())
    assert report["CONFIRM"] == report["category_only"] == report["audit_records"] == 1
    assert report["knowledge_events"] == 1 and report["legacy_review_rows_changed"] == 0


def test_skip_recorded_only_on_explicit_commit(monitored):
    s, c, _ = monitored
    p = s.preview(selection(c, action="SKIP", fields={}), "browser")
    assert not s.monitor.root.exists()
    request = Commit(token=p["token"], explicit_click="APPLY_DISPLAYED_CHANGES")
    for _ in range(2):
        result = s.commit(request, "browser")
        assert result["verification"]["audit_records"] == 0
    assert s.card_status(c["card_id"])["write_state"] == "SKIPPED"
    report = json.loads((s.monitor.root / "report.json").read_text())
    assert report["SKIP"] == report["cards_reviewed"] == 1
    assert len(s.monitor.attempts()) == 1
    assert report["knowledge_diff"]["added"] == 0


def test_correction_replays_without_global_rule_and_reports_stale(monitored):
    s, c, _ = monitored
    old = s.preview(selection(c), "browser")
    apply(s, c)
    with pytest.raises(ValueError, match="STALE_STATE"):
        s.commit(Commit(token=old["token"], explicit_click="APPLY_DISPLAYED_CHANGES"), "browser")
    apply(s, c, action="CHANGE", fields={"context": "PROPERTY"}, reason="Synthetic correction")
    report = json.loads((s.monitor.root / "report.json").read_text())
    assert report["CHANGE"] == report["CONFIRM"] == report["context_only"] == 1
    assert report["stale_state_blocks"] == 1 and report["audit_records"] == 2
    assert s.card_status(c["card_id"])["write_state"] == "CHANGED"
    path = (
        s.monitor.root
        / "knowledge"
        / ("snapshot-" + report["knowledge_diff"]["events_hash"] + ".json")
    )
    snapshot = load_bundle(path)
    assert all(
        i.claim.scope == c["transaction"]["id"]
        for i in snapshot.items
        if i.claim.kind == "MERCHANT_OBSERVATION"
    )


def test_post_commit_failure_blocks_further_writes(monitored, monkeypatch):
    s, c, _ = monitored

    def fail():
        raise OSError("Synthetic report failure")

    monkeypatch.setattr(s.monitor, "refresh", fail)
    with pytest.raises(ValueError, match="WRITE_RECORDED_VERIFICATION_PENDING"):
        apply(s, c)
    assert (s.monitor.root / "blocked.json").exists()
    with pytest.raises(ValueError, match="VERIFICATION_REQUIRED"):
        apply(s, c, action="CHANGE", fields={"context": "PROPERTY"}, reason="Correction")
