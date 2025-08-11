-- Seed initial phase gap history so charts render before live data pulls
CREATE TABLE IF NOT EXISTS phase_gap_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_utc TEXT NOT NULL,
  phase_gap_rad REAL NOT NULL,
  slope_rad_per_day REAL NOT NULL,
  notes TEXT
);

INSERT INTO phase_gap_history(as_of_utc, phase_gap_rad, slope_rad_per_day, notes) VALUES
  ('2024-07-01T00:00:00Z', 0.20, -0.002, 'seed'),
  ('2024-07-01T01:00:00Z', 0.19, -0.002, 'seed'),
  ('2024-07-01T02:00:00Z', 0.18, -0.002, 'seed'),
  ('2024-07-01T03:00:00Z', 0.17, -0.002, 'seed'),
  ('2024-07-01T04:00:00Z', 0.16, -0.002, 'seed'),
  ('2024-07-01T05:00:00Z', 0.15, -0.002, 'seed'),
  ('2024-07-01T06:00:00Z', 0.14, -0.002, 'seed'),
  ('2024-07-01T07:00:00Z', 0.13, -0.002, 'seed'),
  ('2024-07-01T08:00:00Z', 0.12, -0.002, 'seed'),
  ('2024-07-01T09:00:00Z', 0.11, -0.002, 'seed'),
  ('2024-07-01T10:00:00Z', 0.10, -0.002, 'seed'),
  ('2024-07-01T11:00:00Z', 0.09, -0.002, 'seed');
