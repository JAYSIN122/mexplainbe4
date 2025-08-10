
-- GTI + Mesh-NTP Database Schema Migration
-- Migration: 0001_init.sql

-- core registries
CREATE TABLE IF NOT EXISTS source_registry(
  id SERIAL PRIMARY KEY, 
  name TEXT UNIQUE NOT NULL, 
  kind TEXT NOT NULL,
  base_url TEXT, 
  active BOOLEAN NOT NULL DEFAULT TRUE, 
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_run(
  id BIGSERIAL PRIMARY KEY, 
  source_id INT REFERENCES source_registry(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), 
  finished_at TIMESTAMPTZ,
  git_commit TEXT, 
  params JSONB, 
  status TEXT NOT NULL DEFAULT 'running', 
  msg TEXT
);

-- streams + observations
CREATE TABLE IF NOT EXISTS timeseries_stream(
  id BIGSERIAL PRIMARY KEY, 
  source_id INT REFERENCES source_registry(id),
  stream_key TEXT NOT NULL, 
  unit TEXT NOT NULL, 
  cadence_sec INT,
  description TEXT, 
  version INT NOT NULL DEFAULT 1, 
  schema_hash TEXT,
  UNIQUE(source_id, stream_key)
);

CREATE TABLE IF NOT EXISTS observation(
  id BIGSERIAL PRIMARY KEY, 
  stream_id BIGINT REFERENCES timeseries_stream(id),
  t_utc TIMESTAMPTZ NOT NULL, 
  value DOUBLE PRECISION NOT NULL,
  uncertainty DOUBLE PRECISION, 
  quality_flags INT NOT NULL DEFAULT 0,
  raw JSONB, 
  ingest_run_id BIGINT REFERENCES ingest_run(id),
  CHECK(value=value), 
  UNIQUE(stream_id, t_utc)
);

CREATE INDEX IF NOT EXISTS obs_stream_time_idx ON observation(stream_id, t_utc);

-- phase gap (authoritative for ETA)
CREATE TABLE IF NOT EXISTS phase_gap_history(
  id BIGSERIAL PRIMARY KEY, 
  as_of_utc TIMESTAMPTZ NOT NULL,
  phase_gap_rad DOUBLE PRECISION NOT NULL, 
  slope_rad_per_day DOUBLE PRECISION,
  method_version TEXT NOT NULL, 
  provenance JSONB, 
  UNIQUE(as_of_utc)
);

-- forecast (for /api/forecast)
CREATE TABLE IF NOT EXISTS forecast_history(
  id BIGSERIAL PRIMARY KEY, 
  as_of_utc TIMESTAMPTZ NOT NULL,
  current_value DOUBLE PRECISION NOT NULL, 
  trend_rate DOUBLE PRECISION NOT NULL,
  forecast_value DOUBLE PRECISION, 
  horizon_sec INT, 
  model_meta JSONB,
  UNIQUE(as_of_utc)
);

-- eta outputs (read by /api/eta)
CREATE TABLE IF NOT EXISTS eta_estimate(
  id BIGSERIAL PRIMARY KEY, 
  as_of_utc TIMESTAMPTZ NOT NULL,
  eta_days DOUBLE PRECISION NOT NULL, 
  eta_date DATE NOT NULL,
  method TEXT NOT NULL, 
  band_iqr_days DOUBLE PRECISION,
  kendall_tau DOUBLE PRECISION, 
  kendall_pvalue DOUBLE PRECISION,
  n_points INT, 
  notes TEXT, 
  UNIQUE(as_of_utc, method)
);

-- mesh ntp
CREATE TABLE IF NOT EXISTS mesh_node(
  id BIGSERIAL PRIMARY KEY, 
  client_id TEXT UNIQUE NOT NULL,
  agent_version TEXT, 
  tz TEXT, 
  geo JSONB, 
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), 
  last_seen TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ntp_probe(
  id BIGSERIAL PRIMARY KEY, 
  node_id BIGINT REFERENCES mesh_node(id),
  server TEXT NOT NULL, 
  t_utc TIMESTAMPTZ NOT NULL, 
  samples INT NOT NULL,
  offset_mean_ms DOUBLE PRECISION NOT NULL, 
  offset_std_ms DOUBLE PRECISION,
  rtt_mean_ms DOUBLE PRECISION, 
  accepted BOOLEAN NOT NULL DEFAULT TRUE,
  reject_reason TEXT, 
  raw JSONB, 
  UNIQUE(node_id, server, t_utc)
);

CREATE TABLE IF NOT EXISTS mesh_consensus(
  id BIGSERIAL PRIMARY KEY, 
  t_utc TIMESTAMPTZ NOT NULL, 
  method TEXT NOT NULL,
  consensus_offset_ms DOUBLE PRECISION NOT NULL, 
  consensus_std_ms DOUBLE PRECISION,
  n_nodes INT NOT NULL, 
  n_servers INT NOT NULL, 
  flags INT NOT NULL DEFAULT 0,
  UNIQUE(t_utc, method)
);

-- config + audit
CREATE TABLE IF NOT EXISTS app_config(
  key TEXT PRIMARY KEY, 
  val JSONB NOT NULL, 
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log(
  id BIGSERIAL PRIMARY KEY, 
  t_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor TEXT NOT NULL, 
  action TEXT NOT NULL, 
  details JSONB
);

-- convenience views
CREATE OR REPLACE VIEW v_eta_current AS
SELECT DISTINCT ON (method) method, as_of_utc, eta_days, eta_date, band_iqr_days,
       kendall_tau, kendall_pvalue, n_points
FROM eta_estimate ORDER BY method, as_of_utc DESC;
