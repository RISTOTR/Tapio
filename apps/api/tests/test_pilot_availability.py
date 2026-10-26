"""Database availability must not invoke models or expose private errors."""

import pytest
from fastapi.testclient import TestClient

from tapio.pilot import api, health


@pytest.mark.parametrize("available", [True, False])
def test_health_is_model_free_and_safe(monkeypatch, available):
    monkeypatch.setenv("TAPIO_PILOT_MODE", "true")

    def forbidden():
        pytest.fail("Health must not initialize the model-backed pilot")

    def probe():
        if not available:
            raise RuntimeError("PRIVATE_SQL PRIVATE_SECRET")

    monkeypatch.setattr(api, "get_pilot", forbidden)
    monkeypatch.setattr(api, "database_available", probe)
    response = TestClient(api.app).get("/pilot/health")
    assert response.status_code == (200 if available else 503)
    assert response.json()["status"] == ("READY" if available else "DATABASE_UNAVAILABLE")
    assert "PRIVATE_" not in response.text
    assert response.headers["cache-control"] == "no-store"
    if not available:
        assert response.json()["detail"] == health.DATABASE_HELP


def test_startup_stops_before_database_on_invalid_configuration(monkeypatch, capsys):
    def invalid():
        raise ValueError("PRIVATE_SECRET")

    def forbidden():
        pytest.fail("Invalid configuration must stop startup")

    monkeypatch.setattr(health, "load_config", invalid)
    monkeypatch.setattr(health, "readonly_engine", forbidden)
    assert health.preflight() == 1
    assert "PRIVATE_SECRET" not in capsys.readouterr().out
