"""Utility to download remote files with provenance logging."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

import requests


PROV_PATH = "data/_meta/provenance.jsonl"


def _resolve_ip(hostname: str | None) -> str | None:
    """Return the IPv4 address for ``hostname`` or ``None`` if unresolved."""

    if not hostname:
        return None
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None


def download(url: str, out_path: str) -> str:
    """Fetch ``url`` to ``out_path`` and record provenance.

    A ``HEAD`` request is attempted first and falls back to ``GET`` if the
    server rejects it.  The returned provenance record is appended as a JSON
    line to ``data/_meta/provenance.jsonl``.
    """

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    session = requests.Session()

    # Attempt HEAD to discover the final URL and headers.
    head_resp = None
    try:
        head_resp = session.head(url, allow_redirects=True, timeout=30)
        if head_resp.status_code >= 400 or head_resp.status_code in (405, 501):
            head_resp = None
    except requests.RequestException:
        head_resp = None

    # Use the resolved URL from HEAD if we have it.
    get_url = head_resp.url if head_resp else url
    parsed = urlparse(get_url)
    resolved_ip = _resolve_ip(parsed.hostname)

    ts_utc = datetime.utcnow().isoformat() + "Z"
    start = time.time()
    record: dict = {}

    try:
        resp = session.get(get_url, allow_redirects=True, timeout=30)
        elapsed_ms = (time.time() - start) * 1000
        final_url = resp.url

        # Re-resolve in case of redirects to another host.
        parsed_final = urlparse(final_url)
        resolved_ip = _resolve_ip(parsed_final.hostname) or resolved_ip

        content = resp.content
        with open(out_path, "wb") as fh:
            fh.write(content)

        sha256 = hashlib.sha256(content).hexdigest()
        headers = {k: resp.headers.get(k) for k in ["Date", "ETag", "Last-Modified"]}

        record = {
            "ts_utc": ts_utc,
            "url": final_url,
            "out_path": out_path,
            "sha256": sha256,
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "resolved_ip": resolved_ip,
            "headers": headers,
        }

        return out_path

    except Exception as exc:  # pragma: no cover - provenance on failure
        elapsed_ms = (time.time() - start) * 1000
        headers = (
            {k: head_resp.headers.get(k) for k in ["Date", "ETag", "Last-Modified"]}
            if head_resp
            else {"Date": None, "ETag": None, "Last-Modified": None}
        )
        record = {
            "ts_utc": ts_utc,
            "url": get_url,
            "out_path": out_path,
            "sha256": None,
            "status_code": getattr(getattr(exc, "response", None), "status_code", None),
            "elapsed_ms": elapsed_ms,
            "resolved_ip": resolved_ip,
            "headers": headers,
            "error": str(exc),
        }
        raise

    finally:
        os.makedirs(os.path.dirname(PROV_PATH), exist_ok=True)
        with open(PROV_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def fetch_all() -> list[str]:
    """Fetch all remote resources and return a list of output paths."""

    sources = [
        {
            "url": "https://webtai.bipm.org/ftp/pub/tai/other-products/utcrlab/utcrlab.all",
            "out_path": "data/bipm/utcrlab.all",
        },
        {
            "url": "https://datacenter.iers.org/products/eop/rapid/standard/json/finals2000A.data.json",
            "out_path": "data/iers/finals2000A.data.json",
        },
    ]

    pulled: list[str] = []
    for src in sources:
        try:
            download(src["url"], src["out_path"])
            pulled.append(src["out_path"])
            print(f"✅ Downloaded {src['url']} → {src['out_path']}")
        except Exception as exc:  # pragma: no cover - logged but ignored
            print(f"❌ Failed {src['url']}: {exc}")

    return pulled


if __name__ == "__main__":  # pragma: no cover
    pulled = fetch_all()
    print(json.dumps({"pulled": pulled}, indent=2))

