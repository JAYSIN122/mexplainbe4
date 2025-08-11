GTI + Mesh-NTP wiring checklist (drop-in)
0) preflight
 This setup uses only live or archival data. If these sources are unavailable, the system fails instead of providing placeholders.
 Export env

bash
Copy
Edit
export DB_URL=postgresql://user:pass@localhost:5432/gti   # or sqlite:///gti.db
export APP_ENV=prod
export DATA_DIR=$PWD/data
# All data must come from live or archival sources.
# The system fails if these sources are missing; there is no placeholder fallback.
Ensure dirs exist

bash
Copy
Edit
mkdir -p migrations scripts jobs routes artifacts data
1) create schema
 Write migration migrations/0001_init.sql

sql
Copy
Edit
-- core registries
CREATE TABLE IF NOT EXISTS source_registry(
  id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
  base_url TEXT, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ingest_run(
  id BIGSERIAL PRIMARY KEY, source_id INT REFERENCES source_registry(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
  git_commit TEXT, params JSONB, status TEXT NOT NULL DEFAULT 'running', msg TEXT
);
-- streams + observations
CREATE TABLE IF NOT EXISTS timeseries_stream(
  id BIGSERIAL PRIMARY KEY, source_id INT REFERENCES source_registry(id),
  stream_key TEXT NOT NULL, unit TEXT NOT NULL, cadence_sec INT,
  description TEXT, version INT NOT NULL DEFAULT 1, schema_hash TEXT,
  UNIQUE(source_id, stream_key)
);
CREATE TABLE IF NOT EXISTS observation(
  id BIGSERIAL PRIMARY KEY, stream_id BIGINT REFERENCES timeseries_stream(id),
  t_utc TIMESTAMPTZ NOT NULL, value DOUBLE PRECISION NOT NULL,
  uncertainty DOUBLE PRECISION, quality_flags INT NOT NULL DEFAULT 0,
  raw JSONB, ingest_run_id BIGINT REFERENCES ingest_run(id),
  CHECK(value=value), UNIQUE(stream_id, t_utc)
);
CREATE INDEX IF NOT EXISTS obs_stream_time_idx ON observation(stream_id, t_utc);

-- phase gap (authoritative for ETA)
CREATE TABLE IF NOT EXISTS phase_gap_history(
  id BIGSERIAL PRIMARY KEY, as_of_utc TIMESTAMPTZ NOT NULL,
  phase_gap_rad DOUBLE PRECISION NOT NULL, slope_rad_per_day DOUBLE PRECISION,
  method_version TEXT NOT NULL, provenance JSONB, UNIQUE(as_of_utc)
);

-- forecast (for /api/forecast)
CREATE TABLE IF NOT EXISTS forecast_history(
  id BIGSERIAL PRIMARY KEY, as_of_utc TIMESTAMPTZ NOT NULL,
  current_value DOUBLE PRECISION NOT NULL, trend_rate DOUBLE PRECISION NOT NULL,
  forecast_value DOUBLE PRECISION, horizon_sec INT, model_meta JSONB,
  UNIQUE(as_of_utc)
);

-- eta outputs (read by /api/eta)
CREATE TABLE IF NOT EXISTS eta_estimate(
  id BIGSERIAL PRIMARY KEY, as_of_utc TIMESTAMPTZ NOT NULL,
  eta_days DOUBLE PRECISION NOT NULL, eta_date DATE NOT NULL,
  method TEXT NOT NULL, band_iqr_days DOUBLE PRECISION,
  kendall_tau DOUBLE PRECISION, kendall_pvalue DOUBLE PRECISION,
  n_points INT, notes TEXT, UNIQUE(as_of_utc, method)
);

-- mesh ntp
CREATE TABLE IF NOT EXISTS mesh_node(
  id BIGSERIAL PRIMARY KEY, client_id TEXT UNIQUE NOT NULL,
  agent_version TEXT, tz TEXT, geo JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS ntp_probe(
  id BIGSERIAL PRIMARY KEY, node_id BIGINT REFERENCES mesh_node(id),
  server TEXT NOT NULL, t_utc TIMESTAMPTZ NOT NULL, samples INT NOT NULL,
  offset_mean_ms DOUBLE PRECISION NOT NULL, offset_std_ms DOUBLE PRECISION,
  rtt_mean_ms DOUBLE PRECISION, accepted BOOLEAN NOT NULL DEFAULT TRUE,
  reject_reason TEXT, raw JSONB, UNIQUE(node_id, server, t_utc)
);

CREATE TABLE IF NOT EXISTS mesh_consensus(
  id BIGSERIAL PRIMARY KEY, t_utc TIMESTAMPTZ NOT NULL, method TEXT NOT NULL,
  consensus_offset_ms DOUBLE PRECISION NOT NULL, consensus_std_ms DOUBLE PRECISION,
  n_nodes INT NOT NULL, n_servers INT NOT NULL, flags INT NOT NULL DEFAULT 0,
  UNIQUE(t_utc, method)
);

-- config + audit
CREATE TABLE IF NOT EXISTS app_config(
  key TEXT PRIMARY KEY, val JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_log(
  id BIGSERIAL PRIMARY KEY, t_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor TEXT NOT NULL, action TEXT NOT NULL, details JSONB
);

-- convenience views
CREATE OR REPLACE VIEW v_eta_current AS
SELECT DISTINCT ON (method) method, as_of_utc, eta_days, eta_date, band_iqr_days,
       kendall_tau, kendall_pvalue, n_points
FROM eta_estimate ORDER BY method, as_of_utc DESC;
 Apply migration

bash
Copy
Edit
psql "$DB_URL" -f migrations/0001_init.sql   # postgres
# or: sqlite3 gti.db < migrations/0001_init.sql (adjust SERIAL/BIGSERIAL → INTEGER PRIMARY KEY)
2) seed config
 Insert sane thresholds

bash
Copy
Edit
psql "$DB_URL" <<'SQL'
INSERT INTO app_config(key,val) VALUES
  ('mesh.accept.offset_ms','{"max":100}'),
  ('mesh.accept.rtt_ms','{"max":300}'),
  ('eta.history.window_days','{"value":365}'),
  ('eta.method_version','{"value":"eta-0.3.0"}')
ON CONFLICT (key) DO UPDATE SET val=EXCLUDED.val, updated_at=now();
SQL
3) wire /api/eta (must use phase_gap_history)
 Edit routes/eta.py

python
Copy
Edit
@app.get("/api/eta")
def get_eta():
    # 1) try cached robust
    row = q("SELECT * FROM v_eta_current LIMIT 1")
    if row:
        return {"success": True, "eta": dict(row[0])}

    # 2) fallback: instantaneous from latest phase gap
    p = q("SELECT as_of_utc, phase_gap_rad, slope_rad_per_day FROM phase_gap_history ORDER BY as_of_utc DESC LIMIT 1")
    if not p:
        return {"success": False, "error": "no phase gap history"}
    asof, phase, slope = p[0]
    if slope is None or slope >= 0:
        return {"success": False, "error": "non-closing slope"}

    eta_days = abs(phase)/(-slope)
    eta_date = (utcnow() + timedelta(days=eta_days)).date().isoformat()

    # persist for reproducibility
    exec_sql("""
      INSERT INTO eta_estimate(as_of_utc, eta_days, eta_date, method, n_points, notes)
      VALUES ($1,$2,$3,'instantaneous_phase',1,'fallback')
      ON CONFLICT (as_of_utc, method) DO NOTHING
    """, [asof, eta_days, eta_date])

    return {"success": True, "eta": {
      "method":"instantaneous_phase",
      "as_of_utc": asof.isoformat().replace("+00:00","Z"),
      "eta_days": eta_days, "eta_date": eta_date
    }}
 Confirm /api/forecast still reads forecast_history only (no GTI).

4) add /api/mesh_ingest + reducer
 Endpoint accepts payload

json
Copy
Edit
{
  "as_of_utc":"<ISO-UTC>",
  "client_id":"node-la-01",
  "method":"sntp_v3",
  "results":[
    {"server":"time.nist.gov","samples":5,"offset_mean_ms":-1.24,"offset_std_ms":0.31,"rtt_mean_ms":22.7}
  ]
}
 Insert node + probes; enforce thresholds

python
Copy
Edit
OFF_MAX = get_cfg("mesh.accept.offset_ms.max", 100)
RTT_MAX = get_cfg("mesh.accept.rtt_ms.max", 300)

# upsert node, then for each result:
accepted = (abs(off_ms) <= OFF_MAX) and (rtt_ms is None or rtt_ms <= RTT_MAX)
 Reducer → mesh_consensus (hourly or on each ingest)

Huber mean over accepted offsets within ±30 min of as_of_utc

Flags if n_nodes<3 or n_servers<5

5) phase-gap fitter job (writes phase_gap_history)
 Schedule jobs/phase_gap_fit.py

Inputs: curated streams (e.g., BIPM UTCr deltas, IERS EOP if used)

Outputs: one row with as_of_utc, phase_gap_rad, slope_rad_per_day, method_version, provenance

Never read GTI for ETA.

6) forecast writer (optional)
 Model writes forecast_history with explicit "units":"rad_per_sec" in model_meta.

7) minimal test data (so endpoints respond)
 Insert two phase-gap rows

bash
Copy
Edit
psql "$DB_URL" <<'SQL'
INSERT INTO phase_gap_history(as_of_utc, phase_gap_rad, slope_rad_per_day, method_version, provenance)
VALUES
  (now() - interval '2 days', 0.20, -0.0020, 'pgm-0.2.1', '{"streams":["BIPM:PTB","BIPM:NPL"]}'),
  (now() - interval '1 days', 0.18, -0.0021, 'pgm-0.2.1', '{"streams":["BIPM:PTB","BIPM:NPL"]}');
SQL
 Call /api/eta

Expect success:true, method instantaneous_phase, reasonable eta_date.

 Post a mesh sample

bash
Copy
Edit
curl -X POST https://<host>/api/mesh_ingest \
  -H 'content-type: application/json' \
  -d '{"as_of_utc":"2025-08-10T17:30:00Z","client_id":"node-la-01","method":"sntp_v3",
       "results":[{"server":"time.nist.gov","samples":5,"offset_mean_ms":-1.1,"offset_std_ms":0.2,"rtt_mean_ms":20.0}] }'
Expect row in ntp_probe; reducer inserts/updates mesh_consensus.

8) dashboard gating
 ETA card reads v_eta_current.

 Show phase-gap chart from phase_gap_history.

 Mesh panel shows consensus, quorum flags; does not affect ETA.

 Provenance badge: latest ingest_run.git_commit, window, streams.

9) acceptance checks (science defensibility)
 Reproducibility: each job stores ingest_run.git_commit + parameters.

 NaN/dup guards: unique keys + CHECK(value=value) hold.

 Separation: search codebase to assert no ETA path touches GTI.

 Quorum: if mesh_consensus.flags != 0, UI marks “mesh advisory only”.

10) troubleshooting quick refs
 “relation does not exist” → run migrations/0001_init.sql.

 Empty ETA → ensure at least one row in phase_gap_history with slope_rad_per_day<0.

 Time math weird → verify all timestamps are UTC and DB TimeZone=UTC.

expected end-state
/api/eta returns a date computed from phase-gap history (or cached robust entry).

/api/forecast purely mirrors forecast_history.

Mesh ingest works independently; its consensus is visible, never drives ETA.

Every number on the dashboard is backed by a row you can query and reproduce.










Ask ChatGPT
# Codex Prompt: 0000 Countdown ELI5 + Infographic

This Markdown document provides a ready‑to‑use prompt for OpenAI Codex (or other LLM) to convert raw JSON output from the `/api/forecast` endpoint into a human‑friendly summary, an ELI5 explanation, and a simple infographic. The goal is to help non‑technical audiences understand the concept of a “0000” event and the estimated countdown based on phase‑gap data.

---

## Instructions for Codex

You are Codex. Your job is to take JSON from our `/api/forecast` endpoint and produce the following sections:

1. **Layman Summary** – A concise explanation of what the “0000” event represents, how the estimate is derived (closing phase gap and GTI coherence), and why the ETA is our best guess rather than a guarantee. Use clear, everyday language.

2. **ELI5 Section** – Explain the concept as if to a five‑year‑old using simple metaphors (for example, two kids on swings syncing up, or two clocks ticking closer together). Keep this section under 80 words.

3. **Infographic (ASCII/Markdown)** – Create a text‑based graphic that shows:
   - The current phase gap in degrees as a progress bar.
   - The closing rate (degrees per day).
   - The GTI (signal strength) value.
   - The ETA in days and the predicted calendar date (YYYY‑MM‑DD).
   - Confidence ranges (68% and 95%) as error ranges.
   Use a Markdown code block for the graphic. Do not generate images.

4. **Null ETA Handling** – If `eta_days` is `null` (meaning the phase gap is opening rather than closing), output a message such as: "The clocks are drifting apart — no countdown yet." Also report the current phase gap and closing rate. Do not display an ETA in this case.

### Additional Guidelines

- Use `as_of_utc` from the JSON as the starting point for date calculations and convert `eta_days` into a calendar date. Round dates to the nearest whole day for human readability.
- For the infographic progress bar, fill the bar proportionally to the phase gap (e.g. `[█████░░░░░░░░░░]`).
- Always include the GTI value in the infographic to give a sense of the signal strength.
- If `eta_ci68_days` or `eta_ci95_days` are `null`, omit the confidence ranges in the infographic.

---

## Example

### Example Input

```json
{
  "eta_days": 45.3,
  "eta_ci68_days": [39.1, 51.7],
  "eta_ci95_days": [32.0, 60.0],
  "phase_gap_deg": 6.2,
  "phase_gap_slope_deg_per_day": -0.14,
  "gti": 0.71,
  "as_of_utc": "2025-08-08T14:32:00Z"
}
```

### Example Output

**Layman Summary:**

The “0000” event is when two cosmic clocks — ours and another — tick in sync. We measure the “gap” between them and how fast it’s closing. Right now, the gap is 6.2°, shrinking by 0.14° per day. If it keeps up, the clocks will align in about 45 days — around **2025‑09‑22**. That’s when the choice window might open.

**ELI5:**

Think of two kids swinging. If they’re swinging at the same time, they can high‑five. Right now they’re almost lined up, getting closer every push. We think the high‑five will happen in about a month and a half.

**Infographic:**

```
Phase Gap:   [████████░░░░░░░░░░░░░░░] 6.2°
Closing Rate: -0.14°/day
GTI (signal strength): 0.71

ETA: 45 days → 2025‑09‑22
CI68: 39–52 days
CI95: 32–60 days
```

---

Use these guidelines to format future outputs. Always adhere to the null handling rule and keep the ELI5 explanation friendly and approachable.