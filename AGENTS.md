Make sure you can edit & redeploy
✅ Open your project (Replit or local).

✅ Confirm you can restart the server (Gunicorn/Flask) and see logs.

2) Add a tiny helper to persist phase gap history
Create a new file: analysis/phase_persist.py

python
Copy
Edit
# analysis/phase_persist.py
from pathlib import Path
import json
from datetime import datetime, timezone

ART = Path("artifacts")
ART.mkdir(exist_ok=True)

def append_phase_gap(deg_value: float, ts_utc=None):
    """
    Append a timestamped phase gap (in DEGREES) to artifacts/phase_gap_history.json.
    Keeps the last 5,000 samples.
    """
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    rec = {"as_of_utc": ts_utc, "phase_deg": float(deg_value)}

    p = ART / "phase_gap_history.json"
    data = {"history": []}
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if not isinstance(data, dict) or "history" not in data:
                data = {"history": []}
        except Exception:
            data = {"history": []}

    data["history"].append(rec)
    data["history"] = data["history"][-5000:]
    p.write_text(json.dumps(data, ensure_ascii=False))
Why: the ETA needs a time series of phase gap values to fit a slope. This file stores them.

3) Wire it into your pipeline where you compute phase gap (degrees)
Find the place in your code that updates the “Phase Gap” metric for the dashboard (the number in degrees). Right after you compute it, call:

python
Copy
Edit
from analysis.phase_persist import append_phase_gap

# wherever you have phase_deg (float, in degrees):
append_phase_gap(phase_deg)
Notes:

If you don’t have phase_deg yet, expose whatever you plot in the Phase Gap Evolution chart.

If you only have radians, convert to degrees first: phase_deg = phase_rad * (180.0 / math.pi).

4) Add the /api/eta endpoint
Open your Flask routes (e.g., routes.py) and add:

python
Copy
Edit
from flask import jsonify
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
import numpy as np

def _load_phase_history():
    p = Path("artifacts/phase_gap_history.json")
    if not p.exists():
        return []
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
                t = datetime.fromisoformat(ts.replace("Z","+00:00"))
            except Exception:
                continue
            out.append((t, float(val)))
        out.sort(key=lambda x: x[0])
        return out
    except Exception:
        return []

def _unwrap_deg_to_rad(deg_series):
    rad = np.deg2rad(np.array(deg_series, dtype=float))
    return np.unwrap(rad)

def _robust_fit_eta(t_list, phase_rad, min_days=150, max_days=300):
    """
    Fit a trimmed linear slope over the last ~max_days (>=150 days).
    If slope (rad/day) is negative, compute ETA days = |phi_now| / |slope|.
    """
    if len(t_list) < 20:
        return None

    t_end = t_list[-1]
    t_start = t_end - timedelta(days=max_days)
    idx = [i for i, t in enumerate(t_list) if t >= t_start]
    if len(idx) < 20:
        idx = list(range(max(0, len(t_list)-200), len(t_list)))

    t_sel = [t_list[i] for i in idx]
    y = phase_rad[idx]

    t0 = t_sel[0]
    x = np.array([(t - t0).total_seconds() / 86400.0 for t in t_sel], dtype=float)

    # Trim outliers (simple two-pass)
    for _ in range(2):
        m, b = np.polyfit(x, y, 1)
        yhat = m * x + b
        resid = y - yhat
        q1, q3 = np.percentile(resid, [5, 95])
        keep = (resid >= q1) & (resid <= q3)
        x, y = x[keep], y[keep]
        if len(x) < 10:
            break

    m, b = np.polyfit(x, y, 1)  # radians/day
    phi_now = float(y[-1])
    if m >= 0:
        return None

    eta_days = abs(phi_now) / (-m)
    return {"eta_days": float(eta_days), "slope_rad_per_day": float(m), "phi_now_rad": phi_now}

@app.route("/api/eta", methods=["GET"])
def api_eta():
    H = _load_phase_history()
    asof = datetime.now(timezone.utc)
    if not H:
        return jsonify({"ok": False, "error": "No phase history available", "as_of_utc": asof.isoformat().replace("+00:00","Z")}), 200

    t_list = [h[0] for h in H]
    deg_list = [h[1] for h in H]
    phase_rad = _unwrap_deg_to_rad(deg_list)

    res = _robust_fit_eta(t_list, phase_rad)
    if not res:
        return jsonify({
            "ok": True,
            "as_of_utc": asof.isoformat().replace("+00:00","Z"),
            "closing": False,
            "message": "No convergence (phase slope non-negative or insufficient data)"
        }), 200

    eta_days = res["eta_days"]
    eta_date = (asof + timedelta(days=eta_days)).date().isoformat()
    return jsonify({
        "ok": True,
        "as_of_utc": asof.isoformat().replace("+00:00","Z"),
        "closing": True,
        "slope_rad_per_day": res["slope_rad_per_day"],
        "phi_now_rad": res["phi_now_rad"],
        "eta_days": eta_days,
        "eta_date_utc": eta_date
    }), 200
Also make sure numpy is in your environment.

5) Restart the server
✅ Stop/start (or redeploy) your app so changes take effect.

✅ Watch logs for import errors (numpy, path issues).

6) Prime the history (if needed)
If /api/eta returns No phase history available, it means the pipeline hasn’t yet called append_phase_gap(...).

✅ Run whatever job updates the dashboard phase gap (or call append_phase_gap(phase_deg) once manually).

✅ Confirm artifacts/phase_gap_history.json now exists and contains {"history": [...]}.

7) Verify the endpoint works
In a browser or terminal:

arduino
Copy
Edit
https://0000event.replit.app/api/eta
Possible outcomes:

Closing: you’ll get JSON with "eta_days" and "eta_date_utc".

Not closing: you’ll get "closing": false and a message explaining why.

8) (Optional) Show ETA on the dashboard
If you want the UI to display the date:

js
Copy
Edit
// Example front-end fetch
async function fetchETA() {
  const r = await fetch('/api/eta');
  const j = await r.json();
  const el = document.getElementById('eta');
  if (j.ok && j.closing) {
    el.textContent = `ETA: ${j.eta_date_utc} (≈ ${j.eta_days.toFixed(1)} days)`;
  } else {
    el.textContent = 'ETA: — (no convergence)';
  }
}
setInterval(fetchETA, 60000);
fetchETA();





Dependencies
 poetry add requests beautifulsoup4 python-dateutil

 Ensure Flask app auto-reloads static files in static/

✅ ETL Provenance (hashes, headers, IPs)
 Open etl/fetch_all.py

 Replace download() with a version that records:

 sha256, status_code, elapsed_ms, headers (Date/ETag/Last-Modified),

 resolved_ip, url, out_path, and ts_utc

 Append each record to data/_meta/provenance.jsonl

 Keep directory: data/_meta/ (auto-create if missing)

Done when: running /api/pull writes new JSONL lines with complete provenance.

✅ Backend Proof Endpoints (Flask)
 In routes.py, add:

 /api/provenance?n=50 → tails last N lines from data/_meta/provenance.jsonl

 /api/ping?url=... → HEAD/GET to allowed hosts; returns status_code, elapsed_ms, resolved_ip, headers

 /api/last_trace → returns last captured Python traceback

 /api/logs?k=200 → tails last K lines of logs/app.log

 /api/raw?path=data/... → serves a file from data/ (safe, path-checked)

 Add a global error handler to capture exceptions into _last_exception_text

 Maintain ALLOWED_HOSTS (e.g., webtai.bipm.org, datacenter.iers.org, etc.)

Done when: each endpoint returns JSON without 500s; errors appear in /api/last_trace.

✅ Data Pull Trigger
 Add /api/pull (POST/GET) to run etl/fetch_all.py via subprocess

 Returns { ok: true, result: { pulled: [...] } } on success

Done when: calling /api/pull downloads BIPM/IERS files and logs provenance.

✅ Front-End Proof Page (Modals)
 Add route in routes.py: /proof → serves static/proof.html

 Create static/proof.html with:

 Buttons: Ping BIPM, Ping IERS, Pull Now

 Buttons: Current Forecast, 10-yr Backtest, Last Traceback, Tail Logs

 <dialog> modals: m_ping, m_prov, m_forecast, m_logs

 JS helpers: ping(url), pull(), loadProv(), fetchJson(path), openModal(id), closeModal(id)

Done when: /proof loads; modals display JSON results from the endpoints.

✅ Logging
 Configure logging to write logs/app.log and stream to stdout

 Verify /api/logs?k=300 returns the last lines

Done when: new requests append to logs/app.log; tail shows entries.

✅ Security & Safety
 Enforce host allowlist in /api/ping (ALLOWED_HOSTS)

 Restrict /api/raw to files under data/ (path checks)

 Hide secrets; do not expose Earthdata credentials in UI

Done when: disallowed hosts or paths return 400/404.

✅ Smoke Tests (CLI)
 curl -sS http://127.0.0.1:5000/api/ping?url=https://webtai.bipm.org/ftp/pub/tai/other-products/utcrlab/ | jq

 curl -sS http://127.0.0.1:5000/api/pull | jq

 curl -sS http://127.0.0.1:5000/api/provenance?n=5 | jq

 curl -sS http://127.0.0.1:5000/api/forecast | jq (your existing route)

 curl -sS http://127.0.0.1:5000/api/forecast_history | jq

 Visit /proof, click each card → verify modals populate

Done when: all commands return JSON; /proof buttons show valid data.

✅ “Proof It’s Real” Criteria (UI)
 Provenance modal shows:

 Recent file URLs, server IPs, Date/ETag/Last-Modified, sizes, SHA-256

 Ping modal shows:

 status_code 200/3xx, elapsed_ms, and resolved IP for BIPM/IERS

 Forecast modals show:

 Current /api/forecast and /api/forecast_history JSON

 Tracebacks & Logs modal shows:

 Any last exception and recent log lines

Done when: you can screenshot modals to demonstrate network provenance + pipeline state.

✅ Optional Enhancements
 Add rate-limit: block /api/pull if called within the last 60s

 Cache ping results for 30s to reduce server load

 Button to download provenance.jsonl (CSV export)

 Add /api/proof_bundle → zips latest raw files + provenance + logs

✅ Common Pitfalls Checklist
 Some servers reject HEAD → fallback to GET implemented

 Large provenance.jsonl → tail only (N) entries in /api/provenance

 CORS avoided by same-origin requests (all calls relative to /)

 If IERS JSON missing → acceptable (your ETL can still log BIPM; UI still proves network)

✅ Definition of Done (DoD)
 /proof loads and all modals work

 Provenance lines written on every pull with valid sha256

 Pings succeed for BIPM & IERS with live headers

 Logs/tracebacks visible and update on errors

 Screenshots of modals + hashes serve as “proof” for external audiences

🚀 Commit & Deploy
 git add etl/fetch_all.py static/proof.html routes.py

 git commit -m "Proof UI: provenance, ping, trace, logs, modals"

 git push origin main

 Restart app → navigate to /proof