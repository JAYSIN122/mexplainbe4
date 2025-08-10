
#!/usr/bin/env python3
"""
bipm_backfill.py
Backfill phase-gap history from real BIPM UTCr per-lab daily offsets.

Inputs:
- Local folder with utcr-<lab> files (e.g., data/bipm/utcrlab/)
  OR fetch directly from webtai (optional; see FETCH_REMOTE flag).

Outputs:
- artifacts/phase_gap_history.json with entries:
  {"as_of_utc": "...Z", "phase_deg": <float>}

Phase definition:
  phase_deg = ( (UTC(PRIMARY_LAB) - UTC(reference)) / T_REF_SECONDS ) * 360

Reference can be:
  - median of all labs that day, or
  - a specific REFERENCE_LAB

Usage:
  python etl/bipm_backfill.py --local-dir data/bipm/utcrlab --mode median
  python etl/bipm_backfill.py --local-dir data/bipm/utcrlab --mode lab --ref NIST

Notes:
- We DO NOT overwrite existing records; we merge/append deduplicated by date.
- We assume per-lab files contain MJD or YYYY-MM-DD and UTC-UTC(k) offset in seconds
  (some files use microseconds or nanoseconds; parser tries to detect and normalize).
"""

import argparse, re, json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# ---------- CONFIGURABLE ----------
T_REF_SECONDS = 86400.0             # reference cycle (1 sidereal day ≈ 86164; use 86400 for UTC day)
PRIMARY_LAB   = "NIST"              # which lab's UTC(k) to treat as the "signal"
FETCH_REMOTE  = False               # set True to fetch from webtai if local files missing
REMOTE_BASE   = "https://webtai.bipm.org/ftp/pub/tai/other-products/utcrlab/"
ARTIFACT_PATH = Path("artifacts/phase_gap_history.json")
# ----------------------------------

import sys
try:
    import requests
except Exception:
    requests = None

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-dir", required=True, help="Path to directory with utcr-<lab> files")
    ap.add_argument("--mode", choices=["median","lab"], default="median",
                    help="Use daily median across labs or a specific reference lab")
    ap.add_argument("--ref", help="REFERENCE_LAB when --mode=lab, e.g., NPL or PTB")
    ap.add_argument("--tref", type=float, default=T_REF_SECONDS,
                    help=f"Reference seconds per cycle (default {T_REF_SECONDS})")
    ap.add_argument("--primary", default=PRIMARY_LAB, help=f"Primary lab (default {PRIMARY_LAB})")
    ap.add_argument("--dryrun", action="store_true", help="Compute but do not write artifacts")
    return ap.parse_args()

def load_existing_history(artifact_path: Path):
    if not artifact_path.exists():
        return []
    try:
        obj = json.loads(artifact_path.read_text())
        H = obj.get("history", [])
        # normalize / sanity
        out = []
        for h in H:
            ts = h.get("as_of_utc")
            val = h.get("phase_deg")
            if ts is None or val is None:
                continue
            out.append({"as_of_utc": ts, "phase_deg": float(val)})
        return out
    except Exception:
        return []

def save_history(artifact_path: Path, history_list):
    artifact_path.parent.mkdir(exist_ok=True)
    obj = {"history": history_list}
    artifact_path.write_text(json.dumps(obj, ensure_ascii=False))

def mjd_to_date(mjd):
    # MJD epoch: 1858-11-17
    epoch = datetime(1858,11,17, tzinfo=timezone.utc)
    dt = epoch + timedelta(days=float(mjd))
    return dt.date().isoformat()

def parse_line_for_date_and_offset(line):
    """
    Try several formats:
      - MJD    offset_in_seconds
      - YYYY-MM-DD   offset
      - MJD    offset_in_nanoseconds
      - ...
    Return (date_iso, offset_seconds) or None
    """
    line = line.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        return None

    # split by whitespace
    parts = re.split(r"\s+", line)
    if len(parts) < 2:
        return None

    # detect date token
    date_iso = None
    offset_sec = None

    # Candidate 1: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
        date_iso = parts[0]
        val = parts[1]
        # guess unit
        try:
            x = float(val)
        except ValueError:
            return None
        # heuristics: if |x| < 1e-2 it's probably seconds; if |x| > 1e3 maybe microsec/nanosec
        if abs(x) > 1e3:
            # assume nanoseconds unless specified
            # we can refine by checking magnitude:
            # if 1e3 < |x| < 1e9 → microseconds
            if abs(x) < 1e9:
                offset_sec = x * 1e-6
            else:
                offset_sec = x * 1e-9
        else:
            offset_sec = x
        return (date_iso, float(offset_sec))

    # Candidate 2: MJD
    if re.match(r"^\d{5}(?:\.\d+)?$", parts[0]):
        try:
            mjd = float(parts[0])
        except Exception:
            return None
        date_iso = mjd_to_date(mjd)
        val = parts[1]
        try:
            x = float(val)
        except ValueError:
            return None
        if abs(x) > 1e3:
            if abs(x) < 1e9:
                offset_sec = x * 1e-6
            else:
                offset_sec = x * 1e-9
        else:
            offset_sec = x
        return (date_iso, float(offset_sec))

    # Fallback: try to find a YYYY-MM-DD somewhere, then value next
    m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
    if m:
        date_iso = m.group(1)
        rem = line[m.end():].strip()
        parts2 = re.split(r"\s+", rem)
        if parts2:
            try:
                x = float(parts2[0])
                if abs(x) > 1e3:
                    if abs(x) < 1e9:
                        offset_sec = x * 1e-6
                    else:
                        offset_sec = x * 1e-9
                else:
                    offset_sec = x
                return (date_iso, float(offset_sec))
            except Exception:
                pass

    return None

def gather_lab_series(local_dir: Path, lab: str):
    """
    Read utcr-<lab> file and return dict date_iso -> offset_seconds (UTC(lab) - UTC).
    If file missing and FETCH_REMOTE=True, try to fetch.
    """
    fname = f"utcr-{lab}"
    f = local_dir / fname
    data = {}
    if not f.exists():
        if FETCH_REMOTE and requests is not None:
            try:
                url = REMOTE_BASE + fname
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                text = r.text
            except Exception as e:
                print(f"[WARN] Could not fetch {url}: {e}", file=sys.stderr)
                return data
        else:
            print(f"[WARN] Missing file: {f}", file=sys.stderr)
            return data
    else:
        text = f.read_text()

    for line in text.splitlines():
        res = parse_line_for_date_and_offset(line)
        if res:
            date_iso, off_sec = res
            # Keep last value per date if duplicates
            data[date_iso] = off_sec
    return data

def build_daily_phase(local_dir: Path, primary_lab: str, mode: str, ref_lab: str|None, tref_seconds: float):
    """
    Returns list of tuples: (date_iso, phase_deg)
    """
    # Load all available labs (scan filenames utcr-<LAB>)
    lab_files = list(Path(local_dir).glob("utcr-*"))
    labs = sorted({p.name.replace("utcr-","") for p in lab_files})
    if primary_lab not in labs:
        print(f"[WARN] PRIMARY_LAB '{primary_lab}' not among {labs}", file=sys.stderr)

    # Gather series for each lab
    series_by_lab = {}
    for lab in labs:
        s = gather_lab_series(Path(local_dir), lab)
        if s:
            series_by_lab[lab] = s

    if primary_lab not in series_by_lab:
        print(f"[ERROR] No data for PRIMARY_LAB '{primary_lab}'.", file=sys.stderr)
        return []

    # Daily dates where primary has data
    primary = series_by_lab[primary_lab]
    dates = sorted(primary.keys())

    out = []
    for d in dates:
        sig = primary.get(d)
        if sig is None:
            continue

        if mode == "lab":
            if not ref_lab or ref_lab not in series_by_lab:
                print(f"[WARN] ref_lab '{ref_lab}' missing; skipping {d}", file=sys.stderr)
                continue
            ref = series_by_lab[ref_lab].get(d)
            if ref is None:
                # skip days ref has no value
                continue
            delta_sec = sig - ref
        else:
            # median of all labs with data on day d (excluding primary? choose inclusive median)
            vals = []
            for L, S in series_by_lab.items():
                v = S.get(d)
                if v is not None:
                    vals.append(v)
            if len(vals) < 3:
                # not enough for a robust median
                continue
            med = sorted(vals)[len(vals)//2] if len(vals) % 2 == 1 else 0.5*(sorted(vals)[len(vals)//2-1] + sorted(vals)[len(vals)//2])
            delta_sec = sig - med

        # Convert delta to phase degrees
        phase_deg = (delta_sec / tref_seconds) * 360.0
        # Use UTC noon for the day's timestamp (avoid TZ confusion)
        ts = datetime.fromisoformat(d + "T12:00:00+00:00").astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        out.append({"as_of_utc": ts, "phase_deg": float(phase_deg)})

    return out

def merge_histories(existing_list, new_list):
    """
    Merge by date (YYYY-MM-DD). If duplicate date, prefer existing (don't create double entries).
    """
    def daykey(tsz):
        return tsz[:10]  # YYYY-MM-DD
    existing_by_day = { daykey(h["as_of_utc"]): h for h in existing_list }
    for rec in new_list:
        dk = daykey(rec["as_of_utc"])
        if dk not in existing_by_day:
            existing_by_day[dk] = rec
    merged = list(existing_by_day.values())
    merged.sort(key=lambda r: r["as_of_utc"])
    return merged

def main():
    args = parse_args()
    local_dir = Path(args.local_dir)
    if args.mode == "lab" and not args.ref:
        print("[ERROR] --mode lab requires --ref <LAB>", file=sys.stderr)
        sys.exit(2)

    existing = load_existing_history(ARTIFACT_PATH)

    backfilled = build_daily_phase(
        local_dir=local_dir,
        primary_lab=args.primary,
        mode=args.mode,
        ref_lab=args.ref,
        tref_seconds=args.tref,
    )

    if not backfilled:
        print("[WARN] No backfill samples created (check lab names / files).", file=sys.stderr)
        return 0

    merged = merge_histories(existing, backfilled)

    if args.dryrun:
        print(f"[DRYRUN] Would write {len(merged)} total samples (added {len(merged)-len(existing)}).")
        return 0

    save_history(ARTIFACT_PATH, merged)
    print(f"[OK] Wrote {len(merged)} total samples to {ARTIFACT_PATH} (added {len(merged)-len(existing)}).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
