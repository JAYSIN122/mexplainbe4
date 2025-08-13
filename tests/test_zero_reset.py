from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import types
scipy_stub = types.ModuleType("scipy")
signal_mod = types.ModuleType("signal")
windows_mod = types.ModuleType("windows")
def _hilbert(x): raise NotImplementedError
def _dpss(*args, **kwargs): raise NotImplementedError
def _savgol_filter(*args, **kwargs): raise NotImplementedError
signal_mod.hilbert = _hilbert
signal_mod.savgol_filter = _savgol_filter
windows_mod.dpss = _dpss
signal_mod.windows = windows_mod
scipy_stub.signal = signal_mod
sys.modules.setdefault("scipy", scipy_stub)
sys.modules.setdefault("scipy.signal", signal_mod)
sys.modules.setdefault("scipy.signal.windows", windows_mod)
stats_mod = types.ModuleType("stats")
class _Norm: pass
stats_mod.norm = _Norm
scipy_stub.stats = stats_mod
sys.modules.setdefault("scipy.stats", stats_mod)
opt_mod = types.ModuleType("optimize")
def _minimize(*args, **kwargs): raise NotImplementedError
opt_mod.minimize = _minimize
scipy_stub.optimize = opt_mod
sys.modules.setdefault("scipy.optimize", opt_mod)
sklearn_stub = types.ModuleType("sklearn")
decomp_mod = types.ModuleType("decomposition")
class _PCA: pass
decomp_mod.PCA = _PCA
sklearn_stub.decomposition = decomp_mod
sys.modules.setdefault("sklearn", sklearn_stub)
sys.modules.setdefault("sklearn.decomposition", decomp_mod)
cross_mod = types.ModuleType("cross_decomposition")
class _CCA: pass
cross_mod.CCA = _CCA
sklearn_stub.cross_decomposition = cross_mod
sys.modules.setdefault("sklearn.cross_decomposition", cross_mod)


import fastapi_app


class DummyGTI(SimpleNamespace):
    """Simple object mimicking the GTICalculation model."""
    pass


def make_history(values):
    """Create a phase-gap history with given degree values."""
    now = datetime.now(timezone.utc)
    times = [now - timedelta(days=i) for i in reversed(range(len(values)))]
    return times, values


def test_zero_reset_meets_conditions(monkeypatch):
    """Should flag is_0000 when phase gap and GTI meet thresholds."""
    history = make_history([1.0, 0.5, 0.05])
    monkeypatch.setattr(fastapi_app, "_load_phase_history", lambda: history)
    gti_obj = DummyGTI(gti_value=0.95, phase_gap=0.05, timestamp=datetime.now(timezone.utc))
    monkeypatch.setattr(fastapi_app, "_get_latest_gti", lambda: gti_obj)

    client = TestClient(fastapi_app.app)
    resp = client.get("/api/zero_reset")
    assert resp.status_code == 200
    data = resp.json()

    assert set(data.keys()) == {"is_0000", "phase_gap_deg", "gti", "confidence"}
    assert data["is_0000"] is True
    assert data["phase_gap_deg"] == pytest.approx(0.05)
    assert data["gti"] == pytest.approx(0.95)
    assert isinstance(data["confidence"], str)


def test_zero_reset_fails_conditions(monkeypatch):
    """Should not flag is_0000 when metrics are outside thresholds."""
    history = make_history([5.0, 4.5, 4.0])
    monkeypatch.setattr(fastapi_app, "_load_phase_history", lambda: history)
    gti_obj = DummyGTI(gti_value=0.2, phase_gap=4.0, timestamp=datetime.now(timezone.utc))
    monkeypatch.setattr(fastapi_app, "_get_latest_gti", lambda: gti_obj)

    client = TestClient(fastapi_app.app)
    resp = client.get("/api/zero_reset")
    assert resp.status_code == 200
    data = resp.json()

    assert set(data.keys()) == {"is_0000", "phase_gap_deg", "gti", "confidence"}
    assert data["is_0000"] is False
    assert data["phase_gap_deg"] == pytest.approx(4.0)
    assert data["gti"] == pytest.approx(0.2)
    assert isinstance(data["confidence"], str)
