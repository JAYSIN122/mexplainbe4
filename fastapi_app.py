from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from app import app as flask_app
from models import GTICalculation
import json
import numpy as np
from pathlib import Path

# Helper to ensure pure Python floats
f64 = lambda x: None if x is None else float(x)

app = FastAPI()


def _load_phase_history():
    p = Path("artifacts/phase_gap_history.json")
    if not p.exists():
        return [], []
    try:
        obj = json.loads(p.read_text())
        H = obj.get("history", [])
        out = []
        for h in H:
            ts = h.get("as_of_utc")
            val = h.get("phase_deg")
            if ts is None or val is None:
                continue
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            out.append((t, float(val)))
        out.sort(key=lambda x: x[0])
        t_list = [t for t, _ in out]
        deg_list = [deg for _, deg in out]
        return t_list, deg_list
    except Exception:
        return [], []


def _get_latest_gti():
    try:
        return GTICalculation.query.order_by(GTICalculation.timestamp.desc()).first()
    except Exception:
        return None


def _unwrap_deg_to_rad(deg_series):
    rad = np.deg2rad(np.array(deg_series, dtype=float))
    return np.unwrap(rad)


def _robust_fit_eta(t_list, phase_rad, min_days=150, max_days=300):
    if len(t_list) < 20:
        return None
    t_end = t_list[-1]
    t_start = t_end - timedelta(days=max_days)
    idx = [i for i, t in enumerate(t_list) if t >= t_start]
    if len(idx) < 20:
        idx = list(range(max(0, len(t_list) - 200), len(t_list)))
    t_sel = [t_list[i] for i in idx]
    y = phase_rad[idx]
    t0 = t_sel[0]
    x = np.array([(t - t0).total_seconds() / 86400.0 for t in t_sel], dtype=float)
    for _ in range(2):
        coeffs = np.polyfit(x, y, 1)
        m, b = coeffs[0], coeffs[1]
        yhat = m * x + b
        resid = y - yhat
        q1, q3 = np.percentile(resid, [5, 95])
        keep = (resid >= q1) & (resid <= q3)
        x, y = x[keep], y[keep]
        if len(x) < 10:
            break
    coeffs = np.polyfit(x, y, 1)
    m, b = coeffs[0], coeffs[1]
    phi_now = float(y[-1])
    if m >= 0:
        return None
    eta_days = abs(phi_now) / (-m)
    return {"eta_days": float(eta_days)}


def _evaluate_zero_reset():
    """Determine if recent phase history indicates a zero reset event."""
    t_list, deg_list = _load_phase_history()
    latest_gti = _get_latest_gti()

    phase_gap = deg_list[-1] if deg_list else None
    gti_val = float(getattr(latest_gti, "gti_value", 0.0)) if latest_gti else None

    phase_ok = phase_gap is not None and abs(phase_gap) <= 1.0
    gti_ok = gti_val is not None and gti_val >= 0.65

    closing_ok = False
    fresh_ok = False
    if t_list and deg_list:
        fresh_ok = (datetime.now(timezone.utc) - t_list[-1]) <= timedelta(hours=24)
        if len(deg_list) >= 4:
            recent = deg_list[-4:]
            diffs = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
            closing_ok = all(d < 0 for d in diffs)

    is_0000 = bool(phase_ok and gti_ok and closing_ok and fresh_ok)
    if gti_val is None:
        confidence = 0.0
    else:
        confidence = gti_val if is_0000 else gti_val / 2

    return {
        "is_0000": is_0000,
        "phase_gap_deg": float(phase_gap) if phase_gap is not None else None,
        "gti": gti_val,
        "confidence": float(confidence),
    }


@app.get("/api/forecast")
def api_forecast():
    """Return a simple forecast of GTI values."""
    with flask_app.app_context():
        recent_gtis = (
            GTICalculation.query.order_by(GTICalculation.timestamp.desc()).limit(50).all()
        )
    if len(recent_gtis) < 5:
        return {"success": False, "message": "Insufficient data for forecasting"}
    values = [f64(g.gti_value) for g in reversed(recent_gtis)]
    timestamps = [g.timestamp.timestamp() for g in reversed(recent_gtis)]
    if len(values) >= 2:
        time_diff = timestamps[-1] - timestamps[0]
        value_diff = values[-1] - values[0]
        trend_rate = value_diff / time_diff if time_diff > 0 else 0.0
        forecast_time = timestamps[-1] + 3600
        forecast_value = values[-1] + (trend_rate * 3600)
        forecast = {
            "current_value": f64(values[-1]),
            "forecast_value": f64(forecast_value),
            "forecast_time": datetime.fromtimestamp(forecast_time).isoformat(),
            "trend_rate": f64(trend_rate),
            "confidence": "Low" if len(values) < 10 else "Medium",
        }
    else:
        forecast = {
            "current_value": f64(values[-1]) if values else None,
            "forecast_value": None,
            "forecast_time": None,
            "trend_rate": 0.0,
            "confidence": "None",
        }
    return {"success": True, "forecast": forecast}


@app.get("/api/forecast_history")
def api_forecast_history():
    """Return historical GTI forecast data."""
    with flask_app.app_context():
        recent_gtis = (
            GTICalculation.query.order_by(GTICalculation.timestamp.desc()).limit(100).all()
        )
    if len(recent_gtis) < 10:
        return {"success": False, "message": "Insufficient historical data"}
    history = [
        {
            "timestamp": gti.timestamp.isoformat(),
            "gti_value": f64(gti.gti_value),
            "phase_gap": f64(gti.phase_gap),
            "coherence": f64(gti.coherence_median),
            "alert_level": gti.alert_level,
        }
        for gti in reversed(recent_gtis)
    ]
    return {"success": True, "history": history}


@app.get("/api/eta")
def api_eta():
    """Estimate time to alignment based on phase history."""
    t_list, deg_list = _load_phase_history()
    if not t_list:
        return {"eta_date": None, "eta_days": None, "confidence": "low"}
    phase_rad = _unwrap_deg_to_rad(deg_list)
    res = _robust_fit_eta(t_list, phase_rad)
    if not res:
        return {"eta_date": None, "eta_days": None, "confidence": "low"}
    eta_days = f64(res.get("eta_days"))
    eta_date = (datetime.now(timezone.utc) + timedelta(days=eta_days)).date().isoformat()
    confidence = "medium" if len(t_list) > 200 else "low"
    return {"eta_date": eta_date, "eta_days": eta_days, "confidence": confidence}


@app.get("/api/zero_reset")
def api_zero_reset():
    """Evaluate whether the phase gap has effectively reset to zero."""
    return _evaluate_zero_reset()


# Mount existing Flask app for compatibility with current routes and templates
app.mount("/", WSGIMiddleware(flask_app))
