GTI + Mesh-NTP wiring checklist (drop-in)
0) preflight
 Export env

bash
Copy
Edit
export DB_URL=postgresql://user:pass@localhost:5432/gti   # or sqlite:///gti.db
export APP_ENV=prod
export DISABLE_SYNTHETIC=true
export DATA_DIR=$PWD/data
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
# Overview
Summary of repository structure
The top‑level repo directory holds the GTI system’s Python modules (gti_pipeline.py, data_ingestion.py, etc.), a config.py or YAML/JSON file where current configuration options (like data sources and thresholds) are defined, and a history directory holding cached phase‑gap history.

There are other files for building slides, but the app’s logic lives under repo/.

NTP is not currently referenced; the GTI pipeline ingests BIPM/TAI/GNSS data, computes phase gaps between atomic timescales and a modeled reference, then extrapolates an ETA when the gap will converge to zero.

Proposed mesh‑network NTP module
A simple NTP‑based mesh network can detect global timing anomalies by repeatedly measuring differences between the local clock and its peers. Each node would:

Periodically send “ping” requests to a list of peer nodes (using the Network Time Protocol).

Record the round‑trip delay and offset estimates for each peer.

Compute a local “mesh‑phase gap” as the median of offsets minus a baseline (e.g., average offset over the past 24 hours).

Use the same slope‑based ETA formula as the GTI pipeline: eta = |phase_gap| / |slope|, where the slope is the rate of change of the mesh‑phase gap (negative slopes indicate convergence).

Expose the mesh data via an API endpoint /api/mesh_status, returning JSON similar to the existing /api/forecast.

Simplified Python sketch for mesh monitoring
python
Copy
Edit
# repo/mesh_monitor.py
import time
import statistics
import ntplib

class MeshMonitor:
    def __init__(self, peers, interval=60):
        self.peers = peers       # list of NTP server hostnames or IPs
        self.interval = interval # seconds between measurements
        self.history = []        # list of (timestamp, phase_gap, slope) tuples

    def poll_peers(self):
        client = ntplib.NTPClient()
        offsets = []
        for peer in self.peers:
            try:
                response = client.request(peer, version=3)
                offsets.append(response.offset)
            except Exception:
                pass
        return offsets

    def update(self):
        offsets = self.poll_peers()
        if not offsets:
            return
        # current phase gap = median offset minus baseline
        median_offset = statistics.median(offsets)
        baseline = self.history[-1][1] if self.history else median_offset
        phase_gap = median_offset - baseline
        # compute slope (difference over last measurement interval)
        if len(self.history) >= 1:
            dt = time.time() - self.history[-1][0]
            slope = (phase_gap - self.history[-1][1]) / dt
        else:
            slope = 0.0
        self.history.append((time.time(), phase_gap, slope))

    def estimate_eta_days(self):
        # use instantaneous phase_gap and slope to estimate days to zero
        if not self.history: return None
        _, phase_gap, slope = self.history[-1]
        if slope >= 0: return None  # not converging
        eta_seconds = abs(phase_gap) / -slope
        return eta_seconds / 86400.0
Integration plan
Add new configuration flag in config.py, e.g., USE_MESH_MONITOR = False. When True, the backend should run the mesh monitor in parallel with the GTI pipeline.

Extend the API with /api/mesh_status returning:

json
Copy
Edit
{
  "phase_gap": ...,
  "slope": ...,
  "eta_days": ...,
  "timestamp": "..."
}
Expose toggle in the UI so users can select “Mesh only,” “GTI only,” or “Combined.” If combined, display both ETAs and highlight agreement or divergence.

Persist mesh history analogous to phase_gap_history.json, enabling robust statistics and stability checks similar to robust_eta_from_history.

Add a mesh‑monitor runner that polls NTP peers and publishes updates to the web front‑end. This runner can be scheduled via a background thread or task queue.

Expected benefit
A mesh NTP network provides a decentralized check on global timing. If the GTI’s astrophysical phase gap predicts a timeline collision and the mesh monitor shows increasing local clock skew across many nodes, confidence in an impending “0000 reset” grows. Conversely, if the mesh remains stable while GTI suggests convergence, the anomaly may be astrophysical rather than a global synchrony event. By modularizing the mesh monitor, the application can operate with or without the GTI system, giving flexibility for experimentation and independent verification.

This proposal outlines how to add the new module and toggle. Implementing it will require editing repository files (config.py, main.py, and API routes) and ensuring security for mesh peer lists.
This is a Flask-based temporal anomaly detection system that implements a Gravitational Time Interferometry (GTI) pipeline for analyzing timing data streams from multiple sources. The system monitors various timing standards (TAI, GNSS, VLBI, PTA) to detect potential temporal anomalies and calculate GTI metrics that could indicate timeline convergence events. It features a comprehensive web dashboard for real-time monitoring, advanced signal processing capabilities using multitaper analysis and Bayesian methods, and synthetic data generation for testing and demonstration purposes.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Web Framework**: Flask-based web application with Bootstrap dark theme
- **Template Engine**: Jinja2 templates organized in `templates/` directory
- **Static Assets**: CSS and JavaScript files in `static/` with Chart.js for visualizations
- **User Interface**: Dashboard, analysis, and configuration pages with real-time updates

## Backend Architecture
- **Core Framework**: Flask application with SQLAlchemy ORM using DeclarativeBase
- **Database Layer**: SQLite as default with PostgreSQL support through DATABASE_URL environment variable
- **Session Management**: Flask sessions with configurable secret key
- **Proxy Support**: ProxyFix middleware for deployment behind reverse proxies

## Data Processing Pipeline
- **GTI Pipeline**: 8-step process including multitaper spectral analysis, coherence calculation, and phase gap detection
- **Signal Processing**: Advanced algorithms using scipy for filtering, Hilbert transforms, and PCA analysis
- **Bayesian Analysis**: Model selection and parameter estimation for anomaly detection
- **Data Ingestion**: Multi-source timing data streams with synthetic data generation capability

## Database Schema
- **DataStream**: Stores timing data from different sources (TAI, GNSS, VLBI, PTA) with timestamps and metadata
- **GTICalculation**: Results of GTI analysis including phase gaps, coherence values, and alert levels
- **ProcessingConfiguration**: Configurable analysis parameters stored as JSON
- **AnalysisResult**: Additional analysis outputs and intermediate results

## Processing Components
- **Multitaper Analysis**: Configurable time-bandwidth products and taper counts for spectral estimation
- **Coherence Detection**: Pairwise coherence analysis across timing streams
- **Phase Gap Tracking**: Hilbert transform-based phase difference monitoring
- **Alert System**: Multi-level alerting (LOW, MEDIUM, HIGH, CRITICAL) based on GTI thresholds

# External Dependencies

## Core Libraries
- **Flask**: Web application framework with SQLAlchemy integration
- **Scientific Computing**: NumPy, SciPy for mathematical operations and signal processing
- **Machine Learning**: scikit-learn for PCA and canonical correlation analysis
- **Visualization**: Matplotlib for plot generation (non-interactive backend)

## Frontend Dependencies
- **Bootstrap**: Dark theme CSS framework via CDN
- **Chart.js**: Real-time data visualization library
- **Font Awesome**: Icon library for UI components

## Database Support
- **SQLite**: Default embedded database for development
- **PostgreSQL**: Production database support through DATABASE_URL configuration
- **Connection Pooling**: Configured with pool recycling and pre-ping health checks

## Environment Configuration
- **SESSION_SECRET**: Flask session encryption key
- **DATABASE_URL**: Database connection string with fallback to SQLite
- **Logging**: Configurable logging levels for debugging and monitoring

## Data Sources (Future Integration)
- **BIPM Circular-T**: International Atomic Time (TAI) data source
- **IGS Products**: Global Navigation Satellite System (GNSS) clock data
- **VLBI Networks**: Very Long Baseline Interferometry timing data
- **Pulsar Timing Arrays**: High-precision astronomical timing references