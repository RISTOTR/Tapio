import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from apps.api.app.domain.models import ConfirmationRevision, Transaction
from apps.api.tests.test_bank import source_bytes, source_row
from apps.api.tests.test_controlled_confirmation import factory as factory
from data_pipeline.load.bank import import_bank_bytes
from tapio.confirmation.persistent import PersistentQueue
from tapio.knowledge.models import digest
from tapio.knowledge.store import save_bundle


@pytest.fixture
def queue(tmp_path, factory, monkeypatch):
    from tapio.pilot import config

    class Engine:
        def dispose(self):
            pass

    monkeypatch.setattr(config, "load_config", lambda: ({}, {}))
    monkeypatch.setattr(config, "readonly_engine", lambda: Engine())
    monkeypatch.setattr(config, "source_fingerprints", lambda e, c: {})
    rows = [
        source_row(
            Arkistointitunnus=f"queue-synthetic-{i}", **{"Saaja/Maksaja": "Synthetic queue shop"}
        )
        for i in range(35)
    ]
    result = import_bank_bytes(
        source_bytes(rows),
        source_filename="queue-test.csv",
        account_key="queue-test",
        session_factory=factory,
    )
    assert result.status == "imported"
    with factory() as db:
        ids = [str(t.id) for t in db.scalars(select(Transaction))]
    (tmp_path / "queue.key").write_bytes(b"synthetic-private-key")
    (tmp_path / "candidates.json").write_text("[]")
    snap = save_bundle(tmp_path / "knowledge", [])
    q = PersistentQueue(factory, tmp_path)
    q.save_manifest(
        {
            "transaction_ids": ids,
            "active": None,
            "windows": {},
            "window_size": 30,
            "initial_knowledge_hash": snap.events_hash,
            "source_fingerprints": {},
        }
    )
    monkeypatch.setattr(q, "enabled", lambda: True)
    return q


def test_frozen_window_persists_and_pending_is_not_writable(queue):
    q = queue
    first = q.advance(None, initial=True)
    s = q.service()
    assert first["cards"] == 30 and q.progress()["pending"] == 5
    frozen = digest(s.batch)
    with pytest.raises(ValueError, match="COMPLETE"):
        q.advance("W0001")
    clone = PersistentQueue(q.factory, q.root)
    assert digest(clone.service().batch) == frozen
    outside = next(
        tx
        for tx in q.manifest()["transaction_ids"]
        if tx not in {c["transaction"]["id"] for c in s.cards.values()}
    )
    with pytest.raises(ValueError, match="ALLOWLIST"):
        s.card(outside)


def test_explicit_skip_then_next_bounded_tail_preserves_old_cards(queue):
    q = queue
    q.advance(None, initial=True)
    s = q.service()
    old = deepcopy(s.batch)
    # Synthetic test metadata only. Production SKIP goes through signed browser commit.
    for i, cid in enumerate(s.cards):
        s.monitor.write(f"attempts/{i}.json", {"action": "SKIP", "card_id": cid})
    assert q.progress()["can_advance"]
    next_window = q.advance("W0001")
    assert next_window["cards"] == 5 and q.progress()["pending"] == 0
    assert json.loads((q.root / "windows/W0001/preview.json").read_text()) == old
    assert not s.enabled()
    with q.factory() as db:
        assert not list(db.scalars(select(ConfirmationRevision)))
    assert q.progress()["window_states"] == {"READY": 5}


def test_manifest_tampering_and_stale_window_rejected(queue):
    q = queue
    q.advance(None, initial=True)
    with pytest.raises(ValueError, match="STALE_QUEUE"):
        q.advance("W0000")
    p = q.root / "queue.json"
    value = json.loads(p.read_text())
    value["data"]["active"] = "outside"
    p.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="QUEUE_INTEGRITY"):
        q.manifest()


def test_changed_concept_version_stales_and_explicit_refresh_preserves_history(queue):
    q = queue
    q.advance(None, initial=True)
    old = q.service().batch
    # Simulate an independently reviewed concept version; no fake production decisions.
    (q.root / "candidates.json").write_text('[{"id":"test-changed"}]')
    assert q.progress()["window_states"] == {"STALE": 30}
    # Restore candidate structure but a changed version, so a new window can be generated.
    (q.root / "candidates.json").write_text("[]")
    q.service().evidence_check = lambda card: False
    refreshed = q.advance("W0001", refresh=True)
    assert refreshed["cards"] == 30
    assert json.loads((q.root / "windows/W0001/preview.json").read_text()) == old


@pytest.mark.parametrize("action,active", [("CONFIRM_CONCEPT", True), ("DEFER", False)])
def test_next_window_uses_only_active_facts_and_preserves_all_old_files(
    queue, monkeypatch, action, active
):
    from apps.api.tests.test_semantic_concepts import candidate
    from tapio.knowledge.category_mappings import derive_mappings

    q = queue
    c = candidate("synthetic queue", "RESTAURANT", "OTHER", "MERCHANT_TYPE", "CHAIN_PREFIX")
    (q.root / "candidates.json").write_text(json.dumps([c]))
    monkeypatch.setattr(
        "tapio.confirmation.persistent.current_mappings", lambda *args: derive_mappings([c])
    )
    q.advance(None, initial=True)
    service = q.service()
    for i, cid in enumerate(service.cards):
        service.monitor.write(f"attempts/{i}.json", {"action": "SKIP", "card_id": cid})
    files = {p: p.read_bytes() for p in (q.root / "windows/W0001").rglob("*") if p.is_file()}
    preview = q.concepts.preview(
        {"candidate_id": "c", "action": action, "concept": "RESTAURANT"}, "test"
    )
    q.concepts.commit(preview["token"], "test")
    q.advance("W0001")
    assert all(c["semantic_category_used"] == active for c in q.service().cards.values())
    assert all(
        ("SEMANTIC_GENERALIZATION" in c["pilot_tags"]) == active for c in q.service().cards.values()
    )
    assert all(
        ("CATEGORY_ONLY" if active else "ABSTENTION") in c["pilot_tags"]
        for c in q.service().cards.values()
    )
    assert all(c["suggestion"]["context"] is None for c in q.service().cards.values())
    assert all(p.read_bytes() == content for p, content in files.items())
    assert not any(p not in files for p in (q.root / "windows/W0001").rglob("*") if p.is_file())


def test_pending_rules_gate_next_window_and_confirmed_rule_keeps_provenance(queue):
    from apps.api.tests.test_user_rules import rule

    q = queue
    q.advance(None, initial=True)
    old = q.service()
    for i, cid in enumerate(old.cards):
        old.monitor.write(f"attempts/{i}.json", {"action": "SKIP", "card_id": cid})
    frozen = {p: p.read_bytes() for p in (q.root / "windows/W0001").rglob("*") if p.is_file()}
    q.rules.root.mkdir()
    candidate = {
        "id": "rule",
        "rule": rule("Synthetic queue shop"),
        "support": [],
        "semantic_facts": [],
    }
    (q.rules.root / "candidates.json").write_text(json.dumps([candidate]))
    with pytest.raises(ValueError, match="REVIEW_USER_RULE_CANDIDATES_FIRST"):
        q.advance("W0001")
    preview = q.rules.preview(
        {
            "candidate_id": "rule",
            "action": "CONFIRM_RULE",
            "rule": candidate["rule"],
            "expected_state": "PENDING",
        },
        "test",
    )
    event = q.rules.commit(preview["token"], "test")
    q.advance("W0001")
    for c in q.service().cards.values():
        assert c["suggestion"]["context"] == "PERSONAL"
        assert c["user_rules"][0]["event_id"] == event["id"]
        assert c["user_rules"][0]["rule"]["scope"]["owner"] == "THIS_USER"
    assert q.service().batch["rule_version"] == q.rules.version()
    assert all(p.read_bytes() == content for p, content in frozen.items())
    with q.factory() as db:
        assert not list(db.scalars(select(ConfirmationRevision)))
