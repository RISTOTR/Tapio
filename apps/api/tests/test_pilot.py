"""Pilot shell safety and ergonomics with synthetic evidence; no live provider calls."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_phase09f_scoped import Registry as SyntheticRegistry

from scripts.evaluate_phase09d import schema_hash
from tapio.agent.exclusive import ScopedTurn, run_scoped_agent
from tapio.agent.render_bounded import render_answer
from tapio.pilot import api
from tapio.pilot.config import MODEL, SETTINGS, load_config, readonly_engine, readonly_session
from tapio.pilot.contracts import Feedback, Session
from tapio.pilot.history import History
from tapio.pilot.presentation import present, public_text
from tapio.pilot.service import AcceptedModel, Pilot, isolated_engine, period_for

REVIEW = {"year": 2026, "total": 170, "human_reviewed": 75, "unresolved": 95}


class Registry(SyntheticRegistry):
    async def call(self, name, args, **kwargs):
        result = await super().call(name, args, **kwargs)
        if name == "summarize_finances":
            result["data"].update(transaction_count=170, confirmed_count=75)
        return result


class Model:
    def __init__(self, views=None, question_type="overview", bad=False):
        self.views = views or ["BANK_CASH_FLOW", "COVERAGE"]
        self.question_type = question_type
        self.bad = bad
        self.usage = []
        self.protocol_events = []

    async def generate_coordinated(self, messages, tools, *, planning, final_only=False):
        self.usage.append(
            {
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "prompt_tokens_details": {"cached_tokens": 20},
                }
            }
        )
        if planning:
            return ScopedTurn(
                plan={
                    "context_selection": {"mode": "UNSPECIFIED"},
                    "question_type": self.question_type,
                    "required_views": self.views,
                    "needs_coverage_check": False,
                    "needs_tax_boundary": self.question_type == "tax",
                    "needs_reconciliation": "RECONCILIATION" in self.views,
                }
            )
        contract = messages[-1]["content"]["finalization_contract"]
        handles = contract["required_final_handles"]
        if self.bad:
            handles = handles[:-1]
        return ScopedTurn(
            final={
                "references": [{"evidence_handle": h} for h in handles],
                "message_key": contract["allowed_message_keys"][0],
            }
        )


def make_pilot(tmp_path, model=None, registry=None, check=None):
    registry = registry or Registry()
    config = {
        "identifier": "PHASE09H_EXCLUSIVE_C_V1",
        "tool_registry_hash": schema_hash(registry.specifications()),
        "human_review_counts": REVIEW,
    }
    model = model or Model()
    return Pilot(
        history=History(tmp_path / "pilot"),
        model_factory=lambda path: model,
        config_loader=lambda: (config, {"bank_coverage": {}}),
        engine=object(),
        fingerprint_check=check or (lambda engine, config: {"stable": "source"}),
        registry_factory=lambda directory: registry,
        subject_loader=lambda question, session_factory: None,
    )


def ask(pilot, question="Show bank evidence"):
    return asyncio.run(pilot.ask(question))


def session():
    return Session(
        id=str(uuid4()),
        timestamp="2026-10-19T00:00:00Z",
        model_calls=2,
        rounds=2,
        input_tokens=200,
        cached_input_tokens=40,
        output_tokens=20,
        latency_seconds=1.0,
        estimated_cost_usd="0.01",
    )


def test_endpoint_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    monkeypatch.setattr(api, "get_pilot", lambda: make_pilot(tmp_path))
    with TestClient(api.app) as client:
        r = client.post("/pilot/ask", json={"question": "Show bank evidence"})
        assert r.status_code == 200
        assert r.json()["coverage"]["status"] == "DETERMINED"
        assert "no tax-deductibility decision" in r.json()["answer"]
        assert client.get("/pilot").status_code == 200
        assert client.get("/pilot/metrics").status_code == 200


def test_pilot_mode_fail_closed(monkeypatch):
    monkeypatch.delenv("TAPIO_PILOT_MODE", raising=False)
    with TestClient(api.app) as client:
        assert client.post("/pilot/ask", json={"question": "Hello"}).status_code == 503
    with pytest.raises(ValueError, match="PILOT_MODE_DISABLED"):
        load_config()


def test_missing_configuration_fail_closed(monkeypatch, tmp_path):
    from tapio.pilot import config

    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    monkeypatch.setattr(config, "CONFIG", tmp_path / "absent")
    with pytest.raises(FileNotFoundError):
        load_config()


def test_frozen_model_settings():
    assert MODEL == "gpt-5.4-mini-2026-03-17"
    assert SETTINGS == {
        "max_rounds": 6,
        "max_completion_tokens": 3000,
        "reasoning_effort": "none",
        "parallel_tool_calls": False,
        "store": False,
    }
    model = AcceptedModel("synthetic-key", model=MODEL)
    with pytest.raises(ValueError, match="PILOT_MODEL_SETTINGS_CHANGED"):
        model._post({"model": "different"})


def test_identical_engine_code_without_global_patch():
    before = run_scoped_agent.__globals__["ScopedCoordinator"]
    cloned = isolated_engine([])
    assert cloned.__code__ is run_scoped_agent.__code__
    assert run_scoped_agent.__globals__["ScopedCoordinator"] is before
    assert cloned.__kwdefaults__["max_rounds"] == 6


def test_readonly_db_rejects_update():
    url = os.getenv("TAPIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Local PostgreSQL required for mutation-negative test")
    engine = readonly_engine(url)
    with readonly_session(engine) as s:
        assert s.execute(text("SHOW transaction_read_only")).scalar() == "on"
        with pytest.raises(DBAPIError) as error:
            s.execute(text("UPDATE transactions SET amount=amount WHERE false"))
        assert error.value.orig.sqlstate == "25006"
    engine.dispose()


def test_supported_state():
    result = {"ok": True, "tool": "list_documents", "data": {"items": [], "truncated": False}}
    response = {
        "status": "COMPLETE",
        "results": [result],
        "message": "Evidence",
        "answer": render_answer([result], "Evidence"),
    }
    assert present(response, session(), REVIEW).evidence_state == "SUPPORTED"


def test_partial_coverage_and_review_count(tmp_path):
    response = ask(make_pilot(tmp_path))
    assert "PARTIAL_COVERAGE" in response.evidence_states
    assert response.coverage.snapshot_review.unresolved == 95
    assert response.coverage.snapshot_review.human_reviewed == 75
    assert response.coverage.snapshot_review.total == 170
    assert (
        response.coverage.bank[0].completeness == "IMPORTED_ROWS_ONLY_NOT_COMPLETE_BANK_STATEMENT"
    )
    assert response.human_review


def test_588_07_stays_ambiguous(tmp_path):
    response = ask(
        make_pilot(tmp_path, Model(["RECONCILIATION"], "reconciliation")),
        "What do we know about the €588.07 payment?",
    )
    assert response.evidence_state == "AMBIGUOUS"
    assert "588.07" in response.answer
    assert "Exact reversed debit is not established" in response.answer
    assert any(r.type == "AMBIGUOUS_PAYMENT" for r in response.human_review)


def test_tax_boundary(tmp_path):
    response = ask(
        make_pilot(tmp_path, Model(["TAX_BOUNDARY_CONTEXT"], "tax")),
        "Can I deduct the Oikea Konekauppa purchases?",
    )
    assert response.answer.startswith("Tax treatment")
    assert any("does not decide tax deductibility" in x for x in response.limitations)
    assert any(x.type == "TAX_REVIEW" for x in response.human_review)


def test_handles_and_source_ids_retained_privately(tmp_path):
    pilot = make_pilot(tmp_path, Model(["REVIEW_COVERAGE"], "review"))
    response = ask(pilot, "What still needs human review?")
    record = json.loads(
        (pilot.history.directory(response.session.id) / "question.json").read_text()
    )
    assert record["provenance"]["REQUIRED_FINAL_HANDLES"]
    assert record["final_references"]["references"]
    assert record["evidence_sources"]
    assert "id" in json.dumps(record["evidence_sources"])
    assert "evidence_handle" not in response.model_dump_json()
    assert "executed_tool_ledger" not in json.dumps(record)
    assert "system" not in record


def test_private_identifiers_omitted():
    identifier = str(uuid4())
    text = f"Source {identifier}, bank FI2112345600000785, private INVOICE-ABC123."
    clean = public_text(text, [{"data": {"id": identifier, "invoice_number": "INVOICE-ABC123"}}])
    assert identifier not in clean
    assert "FI2112345600000785" not in clean
    assert "INVOICE-ABC123" not in clean


def test_missing_handle_no_freeform_fallback(tmp_path):
    response = ask(make_pilot(tmp_path, Model(bad=True)))
    assert response.evidence_state == "UNSUPPORTED"
    assert response.evidence == []
    assert "no source-update operations" in response.answer


def test_changed_source_blocks_answer(tmp_path):
    calls = []

    def check(engine, config):
        calls.append(1)
        return {"source": len(calls)}

    response = ask(make_pilot(tmp_path, check=check))
    assert response.evidence_state == "UNSUPPORTED"
    assert not response.evidence


@pytest.mark.parametrize(
    "tool",
    ["update_transaction", "confirm_reconciliation", "gmail_search", "gmail_send", "write_file"],
)
def test_mutation_and_gmail_capabilities_unavailable(tmp_path, tool):
    registry = Registry()
    registry.tools[tool] = SimpleNamespace(classification="READ_ONLY")
    model = Model()
    response = ask(make_pilot(tmp_path, model, registry))
    assert response.evidence_state == "UNSUPPORTED"
    assert not model.usage


def test_feedback_storage_and_metrics(tmp_path):
    pilot = make_pilot(tmp_path)
    response = ask(pilot)
    pilot.history.feedback(
        response.session.id, Feedback(rating="INCOMPLETE", note="Need another receipt.")
    )
    metrics = pilot.history.metrics()
    assert metrics["questions_asked"] == 1
    assert metrics["feedback_distribution"] == {"INCOMPLETE": 1}
    assert metrics["tokens"]["input_tokens"] == 200
    assert metrics["model_calls"] == 2
    assert metrics["mean_latency_seconds"] >= 0
    assert float(metrics["total_estimated_cost_usd"]) > 0


def test_history_permissions_and_secret_redaction(tmp_path):
    pilot = make_pilot(tmp_path)
    response = ask(pilot, "Show bank evidence sk-syntheticSecret123")
    path = pilot.history.directory(response.session.id) / "question.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert pilot.history.root.stat().st_mode & 0o777 == 0o700
    assert "sk-syntheticSecret123" not in path.read_text()
    with pytest.raises(ValueError):
        pilot.history.directory("../escape")


def test_cost_latency_capture(tmp_path):
    response = ask(make_pilot(tmp_path))
    assert response.session.model_calls == 2
    assert response.session.rounds == 2
    assert response.session.input_tokens == 200
    assert response.session.cached_input_tokens == 40
    assert response.session.output_tokens == 20
    assert float(response.session.estimated_cost_usd) == pytest.approx(0.000213)


def test_saved_electricity_reused(tmp_path):
    registry = Registry()
    response = ask(
        make_pilot(tmp_path, Model(["ELECTRICITY_SAVED_COMPARISON"], "comparison"), registry),
        "Was fixed or spot electricity cheaper?",
    )
    assert response.coverage.energy
    assert any(t[0] == "get_saved_energy_comparison" for t in registry.calls)
    assert not any(
        t[0] in ("calculate_energy_cost", "simulate_energy_scenario") for t in registry.calls
    )


def test_no_historical_audit_writes(tmp_path):
    folder = Path("data/interim/phase09h/final_validation")
    before = set(folder.glob("*.json"))
    ask(make_pilot(tmp_path))
    assert set(folder.glob("*.json")) == before


def test_explicit_month_period():
    assert period_for("How much did electricity cost in August 2026?") == {
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
    }
    with pytest.raises(ValueError):
        period_for("Compare 2025 and 2026")


def test_cross_origin_blocked(monkeypatch):
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    with TestClient(api.app) as client:
        assert (
            client.post(
                "/pilot/ask",
                headers={"Origin": "https://unrelated.example"},
                json={"question": "Hello"},
            ).status_code
            == 403
        )


def test_feedback_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    pilot = make_pilot(tmp_path)
    monkeypatch.setattr(api, "get_pilot", lambda: pilot)
    with TestClient(api.app) as client:
        answer = client.post("/pilot/ask", json={"question": "Show bank evidence"}).json()
        path = "/pilot/feedback/" + answer["session"]["id"]
        assert (
            client.post(path, json={"rating": "GOOD", "note": "Clear evidence"}).status_code == 200
        )
        assert client.get("/pilot/metrics").json()["feedback_distribution"] == {"GOOD": 1}


def test_validation_errors_do_not_echo_private_input(monkeypatch):
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    with TestClient(api.app) as client:
        r = client.post("/pilot/ask", json={"question": {"iban": "FI2112345600000785"}})
        assert r.status_code == 422
        assert "FI2112345600000785" not in r.text


def test_raw_model_prose_never_returned(tmp_path):
    class BadModel(Model):
        async def generate_coordinated(self, *args, **kwargs):
            return {"answer": "INVENTED financial assertion"}

    response = ask(make_pilot(tmp_path, BadModel()))
    assert response.evidence_state == "UNSUPPORTED"
    assert "INVENTED" not in response.answer


def test_real_registry_has_no_write_or_gmail_tools(tmp_path):
    from tapio.agent.mandatory import coordinated_registry
    from tapio.pilot.presentation import TITLES

    registry = coordinated_registry(coverage={}, audit_path=tmp_path / "audit.jsonl")
    assert set(registry.tools) == set(TITLES)
    assert all(t.classification == "READ_ONLY" for t in registry.tools.values())
    result = asyncio.run(registry.call("gmail_search", {}))
    assert result["ok"] is False


def test_failed_provider_request_still_counted(monkeypatch):
    from tapio.agent.providers.openai_exclusive import OpenAIExclusiveModel

    def unavailable(self, payload):
        raise ValueError("LIVE_PROVIDER_HTTP_503")

    monkeypatch.setattr(OpenAIExclusiveModel, "_post", unavailable)
    model = AcceptedModel("synthetic-key", model=MODEL)
    with pytest.raises(ValueError, match="LIVE_PROVIDER_HTTP_503"):
        model._post({"model": MODEL, **{k: v for k, v in SETTINGS.items() if k != "max_rounds"}})
    assert model.request_count == 1
    assert model.usage == []
