
from pathlib import Path
import json
from datetime import datetime, timezone

ART = Path("artifacts")
ART.mkdir(exist_ok=True)

def append_phase_gap(deg_value: float, ts_utc=None):
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rec = {"as_of_utc": ts_utc, "phase_deg": float(deg_value)}
    p = ART / "phase_gap_history.json"
    data = {"history": []}
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if not isinstance(data, dict) or "history" not in data:
                data = {"history": []}
        except Exception:
            data = {"history": []}
    data["history"].append(rec)
    data["history"] = data["history"][-5000:]
    p.write_text(json.dumps(data, ensure_ascii=False))
