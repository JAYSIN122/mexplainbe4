from datetime import datetime, timedelta
from fastapi.testclient import TestClient
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import fastapi_app


class DummyGTI:
    def __init__(self, gti_value: float, phase_gap: float):
        self.gti_value = gti_value
        self.phase_gap = phase_gap
        self.timestamp = datetime.now()


def test_zero_reset_conditions_met(monkeypatch):
    def mock_history():
        now = datetime.now()
        return [now - timedelta(days=1), now], [5.0, 0.01]

    monkeypatch.setattr(fastapi_app, "_load_phase_history", mock_history)
    monkeypatch.setattr(fastapi_app, "_get_latest_gti", lambda: DummyGTI(0.95, 0.01))

    client = TestClient(fastapi_app.app)
    resp = client.get("/api/zero_reset")
    data = resp.json()
    assert resp.status_code == 200
    assert set(["is_0000", "phase_gap_deg", "gti", "confidence"]).issubset(data)
    assert data["is_0000"] is True
    assert data["phase_gap_deg"] == 0.01
    assert data["gti"] == 0.95


def test_zero_reset_conditions_fail(monkeypatch):
    def mock_history():
        now = datetime.now()
        return [now - timedelta(days=1), now], [5.0, 5.0]

    monkeypatch.setattr(fastapi_app, "_load_phase_history", mock_history)
    monkeypatch.setattr(fastapi_app, "_get_latest_gti", lambda: DummyGTI(0.2, 5.0))

    client = TestClient(fastapi_app.app)
    resp = client.get("/api/zero_reset")
    data = resp.json()
    assert resp.status_code == 200
    assert set(["is_0000", "phase_gap_deg", "gti", "confidence"]).issubset(data)
    assert data["is_0000"] is False
