✅ Dependencies
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