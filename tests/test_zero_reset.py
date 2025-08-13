import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import fastapi_app


@pytest.fixture
def client():
    return TestClient(fastapi_app.app)


def make_history(values):
    now = datetime.now(timezone.utc)
    t_list = [now - timedelta(hours=len(values) - i) for i in range(len(values))]
    return t_list, values


def test_zero_reset_triggers_when_conditions_met(monkeypatch, client):
    t_list, deg_list = make_history([2.0, 1.0, 0.5, 0.2])
    monkeypatch.setattr(fastapi_app, "_load_phase_history", lambda: (t_list, deg_list))
    gti = types.SimpleNamespace(gti_value=0.8, timestamp=datetime.now(timezone.utc))
    monkeypatch.setattr(fastapi_app, "_get_latest_gti", lambda: gti)

    resp = client.get("/api/zero_reset")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"is_0000", "phase_gap_deg", "gti", "confidence"}
    assert data["is_0000"] is True
    assert data["phase_gap_deg"] == pytest.approx(0.2)
    assert data["gti"] == pytest.approx(0.8)
    assert 0 <= data["confidence"] <= 1


def test_zero_reset_fails_when_gti_low(monkeypatch, client):
    t_list, deg_list = make_history([2.0, 1.0, 0.5, 0.2])
    monkeypatch.setattr(fastapi_app, "_load_phase_history", lambda: (t_list, deg_list))
    gti = types.SimpleNamespace(gti_value=0.5, timestamp=datetime.now(timezone.utc))
    monkeypatch.setattr(fastapi_app, "_get_latest_gti", lambda: gti)

    resp = client.get("/api/zero_reset")
    data = resp.json()
    assert data["is_0000"] is False
    assert data["phase_gap_deg"] == pytest.approx(0.2)
    assert data["gti"] == pytest.approx(0.5)
    assert 0 <= data["confidence"] <= 1

