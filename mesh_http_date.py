
# mesh_http_date.py
import os, time, math, socket, ssl, http.client
from datetime import datetime, timezone
from statistics import median
import psycopg
import logging
from urllib.parse import urlparse

log = logging.getLogger("mesh_http_date")

DEFAULT_PEERS = [
  "https://google.com",
  "https://cloudflare.com",
  "https://github.com",
  "https://microsoft.com",
  "https://apple.com",
  "https://akamai.com",
]

PEERS = [p.strip() for p in os.getenv("HTTP_DATE_PEERS","").split(",") if p.strip()] or DEFAULT_PEERS
INTERVAL = int(os.getenv("MESH_INTERVAL_SEC","60"))
DB_URL = os.getenv("DATABASE_URL")

def _now_utc():
    return datetime.now(timezone.utc)

def _fetch_date_head(url:str, timeout=5.0):
    """
    HEAD request, parse Date header.
    Returns dict: {peer, rtt_ms, server_date(datetime), local_date(datetime), offset_ms}
    """
    u = urlparse(url)
    host = u.hostname
    port = u.port or 443
    path = u.path or "/"

    t0 = time.perf_counter()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                conn = http.client.HTTPSConnection(host=host, port=port, timeout=timeout)
                # Hijack the existing tls socket
                conn.sock = ssock
                conn.putrequest("HEAD", path or "/")
                conn.putheader("Host", host)
                conn.putheader("User-Agent", "gti-mesh/1.0")
                conn.endheaders()
                resp = conn.getresponse()
                date_hdr = resp.getheader("Date")
                # Close connection quickly
                resp.read(0)
    except Exception as e:
        raise RuntimeError(f"{url} HEAD failed: {e}")

    t1 = time.perf_counter()
    rtt = (t1 - t0) * 1000.0
    local_recv = _now_utc()

    if not date_hdr:
        raise RuntimeError(f"{url} missing Date header")

    # Example: 'Sun, 11 Aug 2025 08:45:02 GMT'
    try:
        server_dt = datetime.strptime(date_hdr, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        # Some servers use 'GMT' literal but strptime above handles %Z=GMT; keep this simple
        raise RuntimeError(f"{url} unparseable Date header: {date_hdr}")

    # offset ≈ server - local - (rtt/2)
    offset_s = (server_dt - local_recv).total_seconds() - (rtt/1000.0)/2.0
    return {
        "peer": url,
        "rtt_ms": rtt,
        "server_date": server_dt,
        "local_date": local_recv,
        "offset_ms": offset_s * 1000.0
    }

def _save_sample(conn, s, ok=True):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO mesh_sample (peer, method, rtt_ms, server_date, local_date, offset_ms, ok) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (s["peer"], "http-date", float(s["rtt_ms"]), s["server_date"], s["local_date"], float(s["offset_ms"]), ok)
        )

def poll_once():
    results = []
    for p in PEERS:
        try:
            s = _fetch_date_head(p, timeout=6.0)
            results.append(s)
            log.info("HTTP-Date %s: offset=%.3f ms rtt=%.1f ms", p, s["offset_ms"], s["rtt_ms"])
        except Exception as e:
            log.warning("HTTP-Date fail %s: %s", p, e)

    if not results:
        return None

    # Robust combine: median offset, IQR as quality
    offsets = sorted(x["offset_ms"] for x in results)
    mid = median(offsets)
    lo = offsets[len(offsets)//4]
    hi = offsets[(3*len(offsets))//4]
    iqr = hi - lo
    return {
        "n": len(results),
        "offset_ms_median": mid,
        "offset_ms_iqr": iqr,
        "samples": results
    }

def run_forever():
    if not DB_URL:
        log.error("DATABASE_URL missing")
        return
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        log.info("HTTP-Date mesh running with %d peers, interval=%ss", len(PEERS), INTERVAL)
        while True:
            summary = poll_once()
            if summary:
                for s in summary["samples"]:
                    try:
                        _save_sample(conn, s, ok=True)
                    except Exception as e:
                        log.error("DB insert failed: %s", e)
                log.info("Mesh summary: n=%d median=%.3fms iqr=%.3fms",
                         summary["n"], summary["offset_ms_median"], summary["offset_ms_iqr"])
            else:
                log.warning("No HTTP-Date peers succeeded this round")
            time.sleep(INTERVAL)
