#!/usr/bin/env python3
"""
Backfill real phase-gap history from BIPM UTC(k) per-lab files.

Reads utcr-<lab> files from data/bipm/utcrlab, computes phase gap in degrees
between a PRIMARY lab and either:
  - the daily median of all labs (mode=median), or
  - a specific reference lab (mode=lab --ref <LAB>).

Writes merged results into artifacts/phase_gap_history.json.
Requires requests only if you wish to fetch missing files from BIPM.
"""

import argparse, json, re, math, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Default settings; adjust as needed
PRIMARY_LAB   = "NIST"
T_REF_SECONDS = 86400.0
ARTIFACT_PATH = Path("artifacts/phase_gap_history.json")

def mjd_to_date(mjd):
    epoch = datetime(1858,11,17, tzinfo=timezone.utc)
    dt    = epoch + timedelta(days=float(mjd))
    return dt.date().isoformat()

def parse_line(line):
    """Parse various formats: MJD offset or YYYY-MM-DD offset."""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        return None
    parts = re.split(r"\s+", line)
    if len(parts) < 2:
        return None
    # ISO date
    if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
        d = parts[0]
        try:
            x = float(parts[1])
        except ValueError:
            return None
        # Convert large numbers (μs/ns) to seconds
        if abs(x) > 1e3:
            if abs(x) < 1e9:
                off_sec = x * 1e-6
            else:
                off_sec = x * 1e-9
        else:
            off_sec = x
        return d, off_sec
    # MJD date
    if re.match(r"^\d{5}(?:\.\d+)?$", parts[0]):
        try:
            mjd = float(parts[0])
        except Exception:
            return None
        d = mjd_to_date(mjd)
        try:
            x = float(parts[1])
        except ValueError:
            return None
        if abs(x) > 1e3:
            if abs(x) < 1e9:
                off_sec = x * 1e-6
            else:
                off_sec = x * 1e-9
        else:
            off_sec = x
        return d, off_sec
    return None

def load_lab_series(dir_path, lab):
    """Return dict {date: offset_seconds} for a lab file."""
    data = {}
    f = dir_path / f"utcr-{lab}"
    if not f.exists():
        print(f"[WARN] Missing file: {f}", file=sys.stderr)
        return data
    for line in f.read_text().splitlines():
        parsed = parse_line(line)
        if parsed:
            d, off = parsed
            data[d] = off
    return data

def save_history(path, records):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"history": records}, ensure_ascii=False))

def load_existing(path):
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text())
        return obj.get("history", [])
    except Exception:
        return []

def merge_histories(existing, new):
    """Merge lists; avoid duplicates per date (existing wins)."""
    existing_by_day = { rec["as_of_utc"][:10]: rec for rec in existing }
    for rec in new:
        day = rec["as_of_utc"][:10]
        if day not in existing_by_day:
            existing_by_day[day] = rec
    out = list(existing_by_day.values())
    out.sort(key=lambda r: r["as_of_utc"])
    return out

def backfill_phase(dir_path, primary, mode, ref_lab, tref):
    # Load all labs present in directory
    labs = sorted({p.name.replace("utcr-", "") for p in dir_path.glob("utcr-*")})
    if primary not in labs:
        print(f"[ERROR] PRIMARY lab '{primary}' not found among {labs}", file=sys.stderr)
        return []

    series = { lab: load_lab_series(dir_path, lab) for lab in labs }
    primary_series = series.get(primary, {})

    # Determine dates for which primary has data
    dates = sorted(primary_series.keys())
    out = []
    for d in dates:
        sig = primary_series.get(d)
        if sig is None:
            continue
        if mode == "lab":
            ref_val = series.get(ref_lab, {}).get(d)
            if ref_val is None:
                continue
            delta = sig - ref_val
        else:
            vals = [series[L].get(d) for L in labs if series[L].get(d) is not None]
            if len(vals) < 3:
                continue
            vals_sorted = sorted(vals)
            med = vals_sorted[len(vals_sorted)//2] if len(vals_sorted) % 2 == 1 else 0.5*(vals_sorted[len(vals_sorted)//2-1] + vals_sorted[len(vals_sorted)//2])
            delta = sig - med
        phase_deg = (delta / tref) * 360.0
        ts = datetime.fromisoformat(d + "T12:00:00+00:00").astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        out.append({"as_of_utc": ts, "phase_deg": float(phase_deg)})
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-dir", required=True, help="directory containing utcr-<lab> files")
    parser.add_argument("--primary", default=PRIMARY_LAB, help="primary lab name (default NIST)")
    parser.add_argument("--mode", choices=["median","lab"], default="median", help="median or specific lab reference")
    parser.add_argument("--ref", help="reference lab when mode=lab")
    parser.add_argument("--tref", type=float, default=T_REF_SECONDS, help="reference cycle seconds (default 86400)")
    parser.add_argument("--dryrun", action="store_true", help="show counts but don't write file")
    args = parser.parse_args()

    if args.mode == "lab" and not args.ref:
        print("[ERROR] --mode lab requires --ref LAB")
        sys.exit(2)

    dir_path = Path(args.local_dir)
    existing = load_existing(ARTIFACT_PATH)
    new_data = backfill_phase(dir_path, args.primary, args.mode, args.ref, args.tref)
    if not new_data:
        print("[WARN] No backfill data created")
        return 0

    merged = merge_histories(existing, new_data)
    if args.dryrun:
        print(f"[DRYRUN] Would write {len(merged)} total records (added {len(merged)-len(existing)})")
    else:
        save_history(ARTIFACT_PATH, merged)
        print(f"[OK] Wrote {len(merged)} records to {ARTIFACT_PATH} (added {len(merged)-len(existing)})")
    return 0

if __name__ == "__main__":
    main()
