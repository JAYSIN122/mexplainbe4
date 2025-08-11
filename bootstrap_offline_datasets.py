#!/usr/bin/env python3
"""
Bootstrap 10-year historical datasets into app-local paths WITHOUT changing app code.

Targets created:
  - data/gnss/clock_data.csv       -> (unix_ts_sec, clock_sec)
  - data/vlbi/delays.csv           -> (unix_ts_sec, ut1_minus_utc_sec)
  - data/pta/residuals.csv         -> (unix_ts_sec, residual_sec)

Usage examples:
  python bootstrap_offline_datasets.py --bucket s3://my-bucket/ten_year_pack
  python bootstrap_offline_datasets.py --bucket file:///mnt/archive/ten_year_pack --dry-run
  python bootstrap_offline_datasets.py --bucket https://example.com/datasets

Dependencies:
  pip install fsspec s3fs pandas numpy
"""

import argparse
import hashlib
import json
import sys
import io
import re
from pathlib import Path
from datetime import datetime
import fsspec
import numpy as np
import pandas as pd

# ------------------------ Config & Helpers ------------------------

OUT_GNSS = Path("data/gnss/clock_data.csv")
OUT_VLBI = Path("data/vlbi/delays.csv")
OUT_PTA  = Path("data/pta/residuals.csv")

META_SUFFIX = ".meta.json"

def ensure_dirs():
    OUT_GNSS.parent.mkdir(parents=True, exist_ok=True)
    OUT_VLBI.parent.mkdir(parents=True, exist_ok=True)
    OUT_PTA.parent.mkdir(parents=True, exist_ok=True)

def to_unix_from_mjd(mjd: float) -> float:
    # Unix epoch = 1970-01-01, MJD epoch = 1858-11-17
    return (mjd - 40587.0) * 86400.0

def write_meta(csv_path: Path, source_urls: list[str], raw_hashes: list[str]):
    meta = {
        "source_urls": source_urls,
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256_sources": raw_hashes
    }
    with open(csv_path.with_suffix(csv_path.suffix + META_SUFFIX), "w") as f:
        json.dump(meta, f, indent=2)

def sanity_check(df: pd.DataFrame, name: str, units_hint: str, min_rows=50):
    if df.shape[1] != 2:
        raise ValueError(f"{name}: expected 2 columns, got {df.shape[1]}")
    if df.shape[0] < min_rows:
        raise ValueError(f"{name}: too few rows ({df.shape[0]} < {min_rows})")
    if not (np.diff(df.iloc[:200, 0].values) >= 0).all():
        raise ValueError(f"{name}: timestamps not non-decreasing")
    # Rough epoch sanity: 1970..now+1day
    nowp1 = datetime.utcnow().timestamp() + 86400
    if (df[0].min() < 0) or (df[0].max() > nowp1):
        raise ValueError(f"{name}: timestamp range looks wrong")
    # Value sanity (heuristics)
    if name == "GNSS":
        # clock seconds should be small (microsecond-scale)
        if (df[1].abs() > 0.1).any():
            raise ValueError("GNSS: clock seconds magnitude suspicious (>0.1 s)")
    # No unit conversion here; we assume bucket already has seconds (see mappers below)
    return True

# ------------------------ Mappers (Bucket → Local) ------------------------
# We don’t know your bucket’s exact layout, so we provide flexible pattern finders.
# If your bucket already *has* the exact final CSVs, we copy them 1:1.
# Otherwise, we try to derive from common archival formats.

class Bootstrapper:
    def __init__(self, bucket_url: str, dry_run: bool = False):
        self.bucket_url = bucket_url.rstrip("/")
        self.dry_run = dry_run
        self.fs, self.root = fsspec.core.url_to_fs(self.bucket_url)
        self.hashes = []

    def _hash_bytes(self, b: bytes) -> str:
        h = hashlib.sha256(b).hexdigest()
        self.hashes.append(h)
        return h

    def _read_text(self, path: str) -> str:
        with self.fs.open(path, "rb") as f:
            b = f.read()
        self._hash_bytes(b)
        return b.decode("utf-8", errors="ignore")

    def _read_bytes(self, path: str) -> bytes:
        with self.fs.open(path, "rb") as f:
            b = f.read()
        self._hash_bytes(b)
        return b

    def _list(self, pattern: str) -> list[str]:
        # Glob within bucket root
        return sorted(self.fs.glob(self.root + "/" + pattern))

    # ---------- Strategy: try exact-ready CSVs first ----------
    def try_copy_exact(self, rel_src: str, out_path: Path, name: str) -> bool:
        matches = self._list(rel_src)
        if not matches:
            return False
        # pick largest (most complete)
        src = max(matches, key=lambda p: self.fs.size(p))
        if self.dry_run:
            print(f"[DRY] Would copy {name} from {src} → {out_path}")
            return True
        with self.fs.open(src, "rb") as fsrc, open(out_path, "wb") as fdst:
            fdst.write(fsrc.read())
        # minimal load to sanity-check
        df = pd.read_csv(out_path, header=None)
        sanity_check(df, name, "seconds")
        write_meta(out_path, [src], self.hashes.copy())
        return True

    # ---------- GNSS: merge SP3-derived CSVs or parse SP3 if provided ----------
    def build_gnss(self) -> Path:
        name = "GNSS"
        # 1) If bucket already has a consolidated CSV with two columns
        if self.try_copy_exact("**/clock_data.csv", OUT_GNSS, name):
            return OUT_GNSS

        # 2) If bucket has multiple daily CSV parts: merge them
        parts = self._list("**/*clock*.csv")
        parts = [p for p in parts if not p.endswith("/clock_data.csv")]
        if parts:
            frames = []
            for p in parts:
                b = self._read_bytes(p)
                df = pd.read_csv(io.BytesIO(b), header=None)
                if df.shape[1] >= 2:
                    frames.append(df.iloc[:, :2])
            if frames:
                all_df = pd.concat(frames, axis=0, ignore_index=True).dropna()
                all_df = all_df.sort_values(by=0, kind="mergesort")
                # dedupe
                all_df = all_df.drop_duplicates(subset=[0], keep="last").reset_index(drop=True)
                sanity_check(all_df, name, "seconds", min_rows=50)
                if not self.dry_run:
                    OUT_GNSS.parent.mkdir(parents=True, exist_ok=True)
                    all_df.to_csv(OUT_GNSS, index=False, header=False)
                    write_meta(OUT_GNSS, parts, self.hashes.copy())
                else:
                    print(f"[DRY] Would write merged GNSS → {OUT_GNSS} [{len(all_df)} rows]")
                return OUT_GNSS

        # 3) If bucket has SP3 files: parse clock column (µs) → seconds
        sp3s = self._list("**/*.sp3") + self._list("**/*.sp3.gz") + self._list("**/*.sp3.Z")
        if sp3s:
            import gzip
            try:
                rows = []
                for p in sp3s:
                    raw = self._read_bytes(p)
                    text = raw
                    lp = p.lower()
                    if lp.endswith(".gz"):
                        text = gzip.decompress(raw)
                    elif lp.endswith(".z"):
                        try:
                            from unlzw3 import unlzw
                            text = unlzw(raw)
                        except Exception:
                            continue
                    s = text.decode("ascii", errors="ignore")
                    current_epoch = None
                    for L in s.splitlines():
                        if L.startswith("*"):  # epoch line
                            parts = L.split()
                            y, m, d, hh, mm = map(int, parts[1:6])
                            ss = float(parts[6])
                            current_epoch = datetime(y, m, d, hh, mm, int(ss), int((ss % 1) * 1e6))
                            # MJD:
                            mjd = (current_epoch - datetime(1858, 11, 17)).total_seconds() / 86400.0
                            ts = to_unix_from_mjd(mjd)
                        elif L.startswith("P") and current_epoch is not None:
                            parts = L.split()
                            if len(parts) >= 6:
                                try:
                                    clk_us = float(parts[5])
                                    clk_s = clk_us * 1e-6
                                    if abs(clk_s) < 0.1:
                                        rows.append((ts, clk_s))
                                except Exception:
                                    continue
                if rows:
                    df = pd.DataFrame(rows)
                    df = df.sort_values(by=0).drop_duplicates(subset=[0], keep="last").reset_index(drop=True)
                    sanity_check(df, name, "seconds")
                    if not self.dry_run:
                        OUT_GNSS.parent.mkdir(parents=True, exist_ok=True)
                        df.to_csv(OUT_GNSS, index=False, header=False)
                        write_meta(OUT_GNSS, sp3s, self.hashes.copy())
                    else:
                        print(f"[DRY] Would write parsed GNSS SP3 → {OUT_GNSS} [{len(df)} rows]")
                    return OUT_GNSS
            except Exception as e:
                raise RuntimeError(f"Failed to parse SP3 files: {e}")

        raise FileNotFoundError("GNSS source not found in bucket. Provide clock_data.csv, parts, or SP3s.")

    # VLBI: UT1–UTC tables 
    
    def build_vlbi(self) -> Path:
        name = "VLBI"
        # 1) Exact CSV already present?
        if self.try_copy_exact("**/delays.csv", OUT_VLBI, name):
            return OUT_VLBI

        # 2) Common UT1–UTC tables (.txt, .csv): expect columns MJD, UT1-UTC(s)
        candidates = self._list("**/*ut1*utc*.txt") + self._list("**/*ut1*utc*.csv") + self._list("**/*eop*.txt")
        if candidates:
            rows = []
            srcs = []
            for p in candidates:
                try:
                    b = self._read_bytes(p)
                    srcs.append(p)
                    # Try CSV first
                    try:
                        df = pd.read_csv(io.BytesIO(b), comment="#", delim_whitespace=True, header=None)
                    except Exception:
                        # fallback: splitlines
                        text = b.decode("utf-8", "ignore")
                        tmp = []
                        for L in text.splitlines():
                            if not L.strip() or L.strip().startswith("#"):
                                continue
                            parts = L.split()
                            if len(parts) >= 2:
                                tmp.append((parts[0], parts[1]))
                        df = pd.DataFrame(tmp)
                        df[0] = pd.to_numeric(df[0], errors="coerce")
                        df[1] = pd.to_numeric(df[1], errors="coerce")
                        df = df.dropna()

                    # assume col0=MJD, col1=UT1-UTC(s)
                    mjd = pd.to_numeric(df.iloc[:, 0], errors="coerce")
                    ut1 = pd.to_numeric(df.iloc[:, 1], errors="coerce")
                    valid = ~(mjd.isna() | ut1.isna())
                    for M, U in zip(mjd[valid], ut1[valid]):
                        ts = to_unix_from_mjd(float(M))
                        rows.append((ts, float(U)))
                except Exception:
                    continue

            if rows:
                df = pd.DataFrame(rows)
                df = df.sort_values(by=0).drop_duplicates(subset=[0], keep="last").reset_index(drop=True)
                sanity_check(df, name, "seconds")
                if not self.dry_run:
                    OUT_VLBI.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(OUT_VLBI, index=False, header=False)
                    write_meta(OUT_VLBI, srcs, self.hashes.copy())
                else:
                    print(f"[DRY] Would write VLBI UT1-UTC → {OUT_VLBI} [{len(df)} rows]")
                return OUT_VLBI

        raise FileNotFoundError("VLBI source not found. Provide delays.csv or a UT1–UTC table (MJD, seconds).")

    # ---------- PTA: residual tables ----------
    def build_pta(self) -> Path:
        name = "PTA"
        # 1) Exact CSV already present?
        if self.try_copy_exact("**/residuals.csv", OUT_PTA, name):
            return OUT_PTA

        # 2) Residual tables (*.res, *.txt, *.csv). Expect columns: MJD, residual (seconds or microseconds).
        candidates = (self._list("**/*.res") + self._list("**/*residual*.txt") +
                      self._list("**/*residual*.csv") + self._list("**/*.toa"))
        if candidates:
            rows = []
            srcs = []
            for p in candidates:
                try:
                    b = self._read_bytes(p)
                    srcs.append(p)
                    text = b.decode("utf-8", "ignore")
                    for L in text.splitlines():
                        if not L.strip() or L.strip().startswith("#"):
                            continue
                        parts = L.split()
                        if len(parts) < 2:
                            continue
                        # Heuristic: find the first numeric as MJD, last numeric as residual
                        nums = [w for w in parts if re.match(r"^[+-]?\d+(\.\d+)?$", w)]
                        if len(nums) < 2:
                            continue
                        mjd = float(nums[0]); resid = float(nums[-1])
                        # If magnitude > 1e-3, assume microseconds
                        resid_sec = resid * 1e-6 if abs(resid) > 1e-3 else resid
                        ts = to_unix_from_mjd(mjd)
                        rows.append((ts, resid_sec))
                except Exception:
                    continue

            if rows:
                df = pd.DataFrame(rows)
                df = df.sort_values(by=0).drop_duplicates(subset=[0], keep="last").reset_index(drop=True)
                sanity_check(df, name, "seconds")
                if not self.dry_run:
                    OUT_PTA.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(OUT_PTA, index=False, header=False)
                    write_meta(OUT_PTA, srcs, self.hashes.copy())
                else:
                    print(f"[DRY] Would write PTA residuals → {OUT_PTA} [{len(df)} rows]")
                return OUT_PTA

        raise FileNotFoundError("PTA source not found. Provide residuals.csv or per-pulsar residual tables.")

# ------------------------ CLI ------------------------

def main():
    p = argparse.ArgumentParser(description="Bootstrap offline datasets into app-local paths.")
    p.add_argument("--bucket", required=True, help="Bucket/dir URL: s3://... | file:///... | https://...")
    p.add_argument("--dry-run", action="store_true", help="List actions without writing outputs.")
    args = p.parse_args()

    ensure_dirs()
    boot = Bootstrapper(args.bucket, dry_run=args.dry_run)

    # Build each stream independently; fail fast with clear messages
    built = []
    try:
        built.append(("GNSS", boot.build_gnss()))
    except Exception as e:
        print(f"[ERROR] GNSS: {e}", file=sys.stderr); sys.exit(2)

    try:
        built.append(("VLBI", boot.build_vlbi()))
    except Exception as e:
        print(f"[ERROR] VLBI: {e}", file=sys.stderr); sys.exit(3)

    try:
        built.append(("PTA", boot.build_pta()))
    except Exception as e:
        print(f"[ERROR] PTA: {e}", file=sys.stderr); sys.exit(4)

    for name, path in built:
        print(f"[OK] {name} → {path}")

if __name__ == "__main__":
    main()
