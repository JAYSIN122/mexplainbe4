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


def _closure_rate(t_list, deg_series, min_days=150, max_days=300):
    if len(t_list) < 20 or len(deg_series) < 20:
        return None
    phase_rad = _unwrap_deg_to_rad(deg_series)
    t_end = t_list[-1]
    t_start = t_end - timedelta(days=max_days)
    idx = [i for i, t in enumerate(t_list) if t >= t_start]
    if len(idx) < 20:
        idx = list(range(max(0, len(t_list) - 200), len(t_list)))
    t_sel = [t_list[i] for i in idx]
    if (t_sel[-1] - t_sel[0]).days < min_days:
        return None
    y = phase_rad[idx]
    t0 = t_sel[0]
    x = np.array([(t - t0).total_seconds() / 86400.0 for t in t_sel], dtype=float)
    for _ in range(2):
        if len(x) < 10:
            break
        coeffs = np.polyfit(x, y, 1)
        m, b = coeffs[0], coeffs[1]
        yhat = m * x + b
        resid = y - yhat
        q1, q3 = np.percentile(resid, [5, 95])
        keep = (resid >= q1) & (resid <= q3)
        x, y = x[keep], y[keep]
    if len(x) < 2:
        return None
    m, b = np.polyfit(x, y, 1)
    phi_now = float(phase_rad[idx[-1]])
    return {"slope_rad_per_day": float(m), "phase_gap_rad": float(phi_now)}


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


def _closure_rate(t_list, deg_list, max_days=90):
    """Compute closing slope (rad/day) and latest phase gap (rad)."""
    if len(t_list) < 2:
        return None, None
    t_end = t_list[-1]
    t_start = t_end - timedelta(days=max_days)
    idx = [i for i, t in enumerate(t_list) if t >= t_start]
    if len(idx) < 2:
        idx = list(range(max(0, len(t_list) - 30), len(t_list)))
    t_sel = [t_list[i] for i in idx]
    y_deg = [deg_list[i] for i in idx]
    y = _unwrap_deg_to_rad(y_deg)
    t0 = t_sel[0]
    x = np.array([(t - t0).total_seconds() / 86400.0 for t in t_sel], dtype=float)
    if len(x) < 2:
        return None, None
    m, b = np.polyfit(x, y, 1)
    latest_gap = float(y[-1])
    return float(m), latest_gap


@app.get("/api/zero_reset")
def api_zero_reset():
    """Assess proximity to the 0000 reset condition."""
    t_list, deg_list = _load_phase_history()
    slope, gap = _closure_rate(t_list, deg_list)
    phase_gap_deg = np.rad2deg(gap) if gap is not None else None

    latest_gti = _get_latest_gti()
    gti_val = f64(latest_gti.gti_value) if latest_gti else None

    now = datetime.now(timezone.utc)
    cond_slope = slope is not None and slope < 0
    cond_gap = phase_gap_deg is not None and abs(phase_gap_deg) < 1.0
    cond_gti = gti_val is not None and gti_val >= 0.8
    cond_recent = t_list and (now - t_list[-1]) <= timedelta(days=3)

    is_0000 = bool(cond_slope and cond_gap and cond_gti and cond_recent)

    slope_deg_per_day = np.rad2deg(abs(slope)) if slope is not None else 0.0
    slope_factor = min(1.0, slope_deg_per_day / 1.0)
    gti_factor = min(1.0, gti_val if gti_val is not None else 0.0)
    confidence = float(slope_factor * gti_factor)

    return {
        "is_0000": is_0000,
        "phase_gap_deg": f64(phase_gap_deg),
        "gti": f64(gti_val),
        "confidence": f64(confidence),
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


# Mount existing Flask app for compatibility with current routes and templates
app.mount("/", WSGIMiddleware(flask_app))
