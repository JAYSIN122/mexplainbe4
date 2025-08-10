
#!/usr/bin/env python3
"""
eta_runner.py
Standalone ETA calculator + stability checks + placebo + bootstrap CI.
- Pulls from your live API if available (0000event.replit.app),
- Or accepts manual numbers for current_value + trend_rate.
- Produces JSON and a human-readable text report.

Usage examples:
  python eta_runner.py --source live
  python eta_runner.py --manual-current 0.17168922515641238 --manual-slope -2.0233986255718243e-07 --slope-units rad_per_sec
  python eta_runner.py --source live --save report.json

Outputs:
- Prints a text summary to stdout
- Optionally writes JSON to --save
"""

import argparse, json, sys, math, time
from datetime import datetime, timezone, timedelta
import numpy as np
from scipy.stats import kendalltau
import requests

LIVE_BASE = "https://0000event.replit.app"

def now_utc():
    return datetime.now(timezone.utc)

def seconds_to_date(dt0, seconds):
    return (dt0 + timedelta(seconds=seconds)).date().isoformat()

def compute_eta_from_instantaneous(phase_value, slope_value, slope_units="rad_per_sec"):
    """
    phase_value: assumed radians (if using the phase method)
    slope_value: slope magnitude in slope_units
    slope_units: 'rad_per_sec' or 'rad_per_day' or 'unit_per_day' (if not phase)

    Returns: eta_days (float), assumptions str.
    """
    if slope_value >= 0:
        return None, "Slope not closing (>= 0)."

    # Convert slope to per-second if needed
    if slope_units == "rad_per_sec":
        slope_rad_per_sec = slope_value
    elif slope_units == "rad_per_day":
        slope_rad_per_sec = slope_value / 86400.0
    else:
        # Unknown units—treat as per-day unit and warn
        slope_rad_per_sec = slope_value / 86400.0

    eta_seconds = abs(phase_value) / (-slope_rad_per_sec)
    eta_days = eta_seconds / 86400.0
    return eta_days, f"Assumptions: phase in radians; slope units={slope_units}"

def robust_eta_from_history(history):
    """
    history: list of dicts with keys like:
        {
          "as_of_utc": "...",
          "phase_gap": float (radians) or None,
          "slope_rad_per_day": float (optional),
          "eta_days": float (optional),
          ...
        }
    Strategy:
      - Prefer entries that already have eta_days.
      - Otherwise compute from phase_gap + slope_rad_per_day when available.
      - Compute stability band (IQR, last 12 months).
      - Kendall tau monotonicity on slope sign over last window.
    """
    if not history:
        return None

    # Collect tuples (asof_ts, eta_days)
    rows = []
    for h in history:
        ts = None
        try:
            ts = datetime.fromisoformat(h.get("as_of_utc").replace("Z","+00:00")).timestamp()
        except Exception:
            continue

        eta_days = h.get("eta_days")
        if eta_days is None:
            # try compute if we have phase + slope per day
            ph = h.get("phase_gap")
            sl = h.get("slope_rad_per_day")
            if (ph is not None) and (sl is not None) and sl < 0:
                eta_days = abs(float(ph)) / (-float(sl))
        if eta_days is not None and 0 < eta_days < 36500: # sanity (100 years)
            rows.append((ts, float(eta_days)))

    if not rows:
        return None

    rows.sort(key=lambda x: x[0])
    asof_ts, eta_days_latest = rows[-1]

    # Stability over last 12 months worth of entries
    ONE_YR = 365.2422 * 86400.0
    cutoff = rows[-1][0] - ONE_YR
    recent = [r[1] for r in rows if r[0] >= cutoff]
    if len(recent) < 10:
        # fallback to last 50 if a year is sparse
        recent = [r[1] for r in rows[-50:]]

    if recent:
        q1, q3 = np.percentile(recent, [25, 75])
        iqr = float(q3 - q1)
    else:
        iqr = None

    # Monotonicity check on slope sign (if present)
    slopes = [h.get("slope_rad_per_day") for h in history if h.get("slope_rad_per_day") is not None]
    tau, p_tau = (None, None)
    if len(slopes) >= 8:
        # Use Kendall tau on slopes series; a consistently negative trend → evidence of closing
        # If p-value is small and tau < 0, trend is coherent.
        # If near zero with large p, noise.
        try:
            tau, p_tau = kendalltau(range(len(slopes)), slopes)
        except Exception:
            tau, p_tau = (None, None)

    return {
        "eta_days_latest": float(eta_days_latest),
        "eta_date_latest": seconds_to_date(now_utc(), eta_days_latest*86400.0),
        "band_iqr_days": float(iqr) if iqr is not None else None,
        "kendall_tau_on_slopes": None if tau is None else float(tau),
        "kendall_pvalue": None if p_tau is None else float(p_tau),
        "n_points": len(rows)
    }

def placebo_eta(history, n_trials=200, seed=123):
    """
    Shuffle dates vs values to break any real temporal relation. Compute ETA distribution.
    Return: median_days, iqr_days
    """
    rng = np.random.default_rng(seed)
    # extract valid pairs as (ts, eta_days)
    pairs = []
    for h in history:
        try:
            ts = datetime.fromisoformat(h.get("as_of_utc").replace("Z","+00:00")).timestamp()
        except Exception:
            continue
        ed = h.get("eta_days")
        if ed is None:
            # try compute from phase and slope
            ph, sl = h.get("phase_gap"), h.get("slope_rad_per_day")
            if (ph is not None) and (sl is not None) and sl < 0:
                ed = abs(float(ph)) / (-float(sl))
        if ed is not None and 0 < ed < 36500:
            pairs.append((ts, float(ed)))
    if len(pairs) < 12:
        return None

    ts_arr = np.array([p[0] for p in pairs])
    ed_arr = np.array([p[1] for p in pairs])

    meds = []
    for _ in range(n_trials):
        perm = rng.permutation(len(pairs))
        # random shuffle destroys structure; take last K to mimic "latest"
        shuffled_ed = ed_arr[perm]
        # choose the last dozen as a pseudo-recent distribution
        sample = shuffled_ed[-12:]
        meds.append(np.median(sample))

    meds = np.array(meds)
    return {
        "placebo_median_days": float(np.median(meds)),
        "placebo_iqr_days": float(np.percentile(meds, 75) - np.percentile(meds, 25)),
        "n_trials": n_trials
    }

def bootstrap_eta_band(history, n_boot=300, seed=321):
    """
    Block bootstrap: sample with replacement from last 12 months (or last 50 pts if sparse),
    compute IQR of ETA for each bootstrap, then aggregate.
    """
    rng = np.random.default_rng(seed)
    # collect recent eta_days
    pairs = []
    for h in history:
        try:
            ts = datetime.fromisoformat(h.get("as_of_utc").replace("Z","+00:00")).timestamp()
        except Exception:
            continue
        ed = h.get("eta_days")
        if ed is None:
            ph, sl = h.get("phase_gap"), h.get("slope_rad_per_day")
            if (ph is not None) and (sl is not None) and sl < 0:
                ed = abs(float(ph)) / (-float(sl))
        if ed is not None and 0 < ed < 36500:
            pairs.append((ts, float(ed)))
    if not pairs:
        return None
    pairs.sort(key=lambda x: x[0])

    ONE_YR = 365.2422 * 86400.0
    cutoff = pairs[-1][0] - ONE_YR
    recent = [p[1] for p in pairs if p[0] >= cutoff]
    if len(recent) < 10:
        recent = [p[1] for p in pairs[-50:]]

    if len(recent) < 5:
        return None

    iqr_list = []
    for _ in range(n_boot):
        sample = rng.choice(recent, size=len(recent), replace=True)
        q1, q3 = np.percentile(sample, [25, 75])
        iqr_list.append(q3 - q1)

    iqr_arr = np.array(iqr_list)
    return {
        "bootstrap_iqr_median_days": float(np.median(iqr_arr)),
        "bootstrap_iqr_95pct_days": float(np.percentile(iqr_arr, 95)),
        "n_boot": n_boot
    }

def pull_live_forecast():
    r = requests.get(f"{LIVE_BASE}/api/forecast", timeout=30)
    r.raise_for_status()
    return r.json()

def pull_live_history():
    r = requests.get(f"{LIVE_BASE}/api/forecast_history", timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["live","manual"], default="live")
    ap.add_argument("--manual-current", type=float, help="phase/current value (assumed radians if using phase method)")
    ap.add_argument("--manual-slope", type=float, help="trend rate (negative = closing)")
    ap.add_argument("--slope-units", choices=["rad_per_sec","rad_per_day","unit_per_day"], default="rad_per_sec")
    ap.add_argument("--save", help="write JSON result to this file")
    args = ap.parse_args()

    out = {
        "as_of_utc": now_utc().isoformat().replace("+00:00","Z"),
        "source": args.source,
        "eta": None,
        "stability": None,
        "placebo": None,
        "bootstrap": None,
        "notes": []
    }

    # 1) Instantaneous ETA
    if args.source == "manual":
        if args.manual_current is None or args.manual_slope is None:
            print("For --source manual, provide --manual-current and --manual-slope", file=sys.stderr)
            sys.exit(2)
        eta_days, note = compute_eta_from_instantaneous(args.manual_current, args.manual_slope, args.slope_units)
        if eta_days is not None:
            out["eta"] = {
                "eta_days": float(eta_days),
                "eta_date": seconds_to_date(now_utc(), eta_days*86400.0),
                "method": "instantaneous",
                "assumptions": note
            }
        else:
            out["notes"].append(note)
    else:
        # live
        try:
            f = pull_live_forecast()
            # Try instantaneous with explicit assumptions:
            fv = f.get("forecast", {})
            curr = float(fv.get("current_value"))
            slope = float(fv.get("trend_rate"))
            eta_days, note = compute_eta_from_instantaneous(curr, slope, "rad_per_sec")
            if eta_days is not None:
                out["eta"] = {
                    "eta_days": float(eta_days),
                    "eta_date": seconds_to_date(now_utc(), eta_days*86400.0),
                    "method": "instantaneous",
                    "assumptions": note
                }
            else:
                out["notes"].append(note)
        except Exception as e:
            out["notes"].append(f"Instantaneous ETA failed: {e}")

    # 2) History-based ETA + stability + placebo + bootstrap
    history = None
    try:
        if args.source == "live":
            H = pull_live_history()
            history = H.get("history") or H.get("data") or []
    except Exception as e:
        out["notes"].append(f"Could not load history: {e}")

    if history:
        robust = robust_eta_from_history(history)
        if robust:
            out["stability"] = robust
            # Placebo
            pl = placebo_eta(history, n_trials=300)
            if pl: out["placebo"] = pl
            # Bootstrap
            bs = bootstrap_eta_band(history, n_boot=400)
            if bs: out["bootstrap"] = bs

    # Print readable summary
    print("=== ETA REPORT ===")
    if out.get("eta"):
        print(f"Method: {out['eta']['method']}")
        print(f"ETA Days: {out['eta']['eta_days']:.2f}")
        print(f"ETA Date: {out['eta']['eta_date']}")
        if out['eta'].get("assumptions"): print(out['eta']['assumptions'])
    else:
        print("No instantaneous ETA (units or slope not closing).")

    if out.get("stability"):
        s = out["stability"]
        print("\n--- Stability (history) ---")
        print(f"Latest ETA (days): {s['eta_days_latest']:.2f}")
        print(f"Latest ETA (date): {s['eta_date_latest']}")
        print(f"IQR band (days): {s['band_iqr_days']:.2f}" if s['band_iqr_days'] is not None else "IQR band: n/a")
        if s['kendall_tau_on_slopes'] is not None:
            print(f"Kendall τ on slopes: {s['kendall_tau_on_slopes']:.3f} (p={s['kendall_pvalue']:.3g})")
        print(f"N points: {s['n_points']}")
        # Simple decision heuristic
        if s['band_iqr_days'] is not None:
            if s['band_iqr_days'] > 90:
                print("Decision: likely NO real convergence (band too wide).")
            elif s['band_iqr_days'] <= 45:
                print("Decision: persistent narrow band — interesting, monitor.")
            else:
                print("Decision: borderline band width — needs more data.")
    else:
        print("\nNo history-based stability available.")

    if out.get("placebo"):
        p = out["placebo"]
        print("\n--- Placebo ---")
        print(f"Placebo median ETA (days): {p['placebo_median_days']:.2f}")
        print(f"Placebo IQR (days): {p['placebo_iqr_days']:.2f}")
        print(f"Trials: {p['n_trials']}")

    if out.get("bootstrap"):
        b = out["bootstrap"]
        print("\n--- Bootstrap CI on IQR ---")
        print(f"Median IQR (days): {b['bootstrap_iqr_median_days']:.2f}")
        print(f"95th pct IQR (days): {b['bootstrap_iqr_95pct_days']:.2f}")
        print(f"Bootstraps: {b['n_boot']}")

    if out["notes"]:
        print("\nNotes:")
        for n in out["notes"]:
            print(" -", n)

    # Optional JSON save
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\nSaved JSON → {args.save}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
