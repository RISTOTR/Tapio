"""Offline pilot diagnostics and request-routing regressions; no live model calls."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from test_pilot import Model, ask, make_pilot

from tapio.agent.exclusive import ScopedTurn
from tapio.pilot import api
from tapio.pilot.diagnostics import exception_detail
from tapio.pilot.service import period_for


class PlannedModel(Model):
    def __init__(self, views, kind, contexts):
        super().__init__(views, kind)
        self.contexts = contexts

    async def generate_coordinated(self, *args, **kwargs):
        turn = await super().generate_coordinated(*args, **kwargs)
        if turn.plan:
            plan = turn.plan.model_dump(mode="json")
            plan["context_selection"] = (
                {"mode": "SELECTED", "contexts": self.contexts}
                if self.contexts
                else {"mode": "UNSPECIFIED"}
            )
            return ScopedTurn(plan=plan)
        return turn


def record(pilot, response):
    return json.loads((pilot.history.directory(response.session.id) / "question.json").read_text())


@pytest.mark.parametrize(
    "question,views,kind,contexts",
    [
        (
            "How much forestry income did I receive in 2025?",
            ["BANK_CASH_FLOW", "FORESTRY_SALE"],
            "income",
            ["FORESTRY"],
        ),
        (
            "What were my main property expenses in 2026?",
            ["BANK_CASH_FLOW", "COVERAGE"],
            "domain_cost",
            ["PROPERTY"],
        ),
        ("What do we know about the €588.07 payment?", ["RECONCILIATION"], "reconciliation", []),
        ("What transactions still need human review?", ["REVIEW_COVERAGE"], "review", []),
        (
            "Was fixed or spot electricity cheaper during the supported comparison period?",
            ["ELECTRICITY_SAVED_COMPARISON"],
            "comparison",
            [],
        ),
    ],
)
def test_supported_questions_reach_accepted_pipeline(
    tmp_path, monkeypatch, question, views, kind, contexts
):
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")
    monkeypatch.setenv("TAPIO_PILOT_DIAGNOSTICS", "true")
    pilot = make_pilot(tmp_path, PlannedModel(views, kind, contexts))
    monkeypatch.setattr(api, "get_pilot", lambda: pilot)
    with TestClient(api.app) as client:
        response = client.post("/pilot/ask", json={"question": question})
    assert response.status_code == 200
    public = response.json()
    assert public["evidence_state"] != "UNSUPPORTED"
    assert public["evidence"]
    assert public["coverage"]["status"] == "DETERMINED"
    assert public["session"]["model_calls"] == 2  # Scripted provider usage, not paid calls.
    history = json.loads(
        (pilot.history.directory(public["session"]["id"]) / "question.json").read_text()
    )
    d = history["diagnostics"]
    assert d["route_reached"] == "POST /pilot/ask"
    assert d["planner_called"] and d["coordinator_called"]
    assert d["evidence_views_requested"] and d["evidence_views_returned"]
    assert d["failure"] is None
    assert "FINAL_VALIDATION" in d["stages"] and "SOURCE_POSTFLIGHT" in d["stages"]
    assert history["source_fingerprints_verified"]
    assert "diagnostics" not in public


def test_unavailable_database_is_not_unsupported_question(tmp_path, monkeypatch):
    monkeypatch.setenv("TAPIO_PILOT_DIAGNOSTICS", "true")

    def refused(*args):
        raise OperationalError("PRIVATE_SQL", {}, Exception("connection refused PRIVATE_SECRET"))

    pilot = make_pilot(tmp_path, check=refused)
    response = ask(pilot, "How much forestry income did I receive in 2025?")
    r = record(pilot, response)
    d = r["diagnostics"]
    assert response.session.model_calls == 0
    assert not d["planner_called"] and not d["coordinator_called"]
    assert d["failure"]["stage"] == "SOURCE_PREFLIGHT"
    assert d["failure"]["category"] == "INFRASTRUCTURE_UNAVAILABLE"
    assert d["failure"]["code"] == "DATABASE_CONNECTION_REFUSED"
    assert d["failure"]["frames"]
    assert "PRIVATE_SECRET" not in json.dumps(r) and "PRIVATE_SQL" not in json.dumps(r)
    assert "local database is offline" in response.answer
    assert "./scripts/start_pilot.sh" in response.answer


def test_year_month_and_unsupported_range(tmp_path):
    assert period_for("How much forestry income did I receive in 2025?") == {
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
    }
    assert period_for("August 2026") == {"date_from": "2026-08-01", "date_to": "2026-08-31"}
    pilot = make_pilot(tmp_path)
    response = ask(pilot, "Compare my income between 2024 and 2026")
    assert response.evidence_state == "UNSUPPORTED" and not response.evidence
    assert response.session.model_calls == 0
    assert record(pilot, response)["diagnostics"]["failure"]["category"] == "QUESTION_TOO_BROAD"


def test_swallowed_provider_exception_preserved(tmp_path):
    class Unavailable(Model):
        request_count = 1

        async def generate_coordinated(self, *args, **kwargs):
            raise ValueError("LIVE_PROVIDER_HTTP_503")

    pilot = make_pilot(tmp_path, Unavailable())
    response = ask(pilot)
    d = record(pilot, response)["diagnostics"]
    assert response.session.model_calls == 1
    assert not response.session.usage_complete
    assert d["planner_called"] and not d["coordinator_called"]
    assert d["failure"]["code"] == "LIVE_PROVIDER_HTTP_503"
    assert d["failure"]["category"] == "INFRASTRUCTURE_UNAVAILABLE"


def test_configuration_failure_is_recorded(tmp_path):
    pilot = make_pilot(tmp_path)

    def missing():
        raise FileNotFoundError("private configuration filename")

    pilot.config_loader = missing
    response = ask(pilot)
    d = record(pilot, response)["diagnostics"]
    assert d["failure"]["category"] == "CONFIGURATION_ERROR"
    assert d["failure"]["stage"] == "CONFIGURATION"
    assert response.session.model_calls == 0
    assert "private configuration filename" not in json.dumps(d)


@pytest.mark.parametrize(
    "exc,stage,category",
    [
        (ValueError("UNSUPPORTED_QUESTION"), "QUESTION_PERIOD", "UNSUPPORTED_SCOPE"),
        (ValueError("PILOT_CONFIGURATION_CHANGED"), "CONFIGURATION", "CONFIGURATION_ERROR"),
        (
            ValueError("LIVE_KEY_NOT_CONFIGURED"),
            "MODEL_INITIALIZATION",
            "INFRASTRUCTURE_UNAVAILABLE",
        ),
        (ValueError("PILOT_EVIDENCE_INCOMPLETE"), "FINAL_VALIDATION", "EVIDENCE_INCOMPLETE"),
        (ValueError("INVALID_FINAL_CONTENT"), "FINAL_VALIDATION", "VALIDATION_ERROR"),
        (RuntimeError("private content"), "EVIDENCE_RETRIEVAL", "AGENT_EXECUTION_ERROR"),
        (ValueError("PILOT_REFERENCE_FAILURE"), "FINAL_VALIDATION", "SAFETY_REJECTION"),
    ],
)
def test_distinct_failure_categories(exc, stage, category):
    result = exception_detail(exc, stage)
    assert result["category"] == category
    assert "private content" not in json.dumps(result)
    assert "frames" not in result
