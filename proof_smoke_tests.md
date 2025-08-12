# Proof Endpoint Smoke Tests

Run these commands from the project root to exercise the proof-related endpoints. Each command should return JSON that `jq` can pretty-print.

```bash
curl -sS "http://127.0.0.1:5000/api/ping?url=https://webtai.bipm.org/ftp/pub/tai/other-products/utcrlab/" | jq
curl -sS http://127.0.0.1:5000/api/pull | jq
curl -sS "http://127.0.0.1:5000/api/provenance?n=5" | jq
curl -sS http://127.0.0.1:5000/api/forecast | jq
curl -sS http://127.0.0.1:5000/api/forecast_history | jq
```

After running the CLI checks, open [http://127.0.0.1:5000/proof](http://127.0.0.1:5000/proof) in a browser. Use the buttons on the page to confirm that each modal (Ping, Provenance, Forecast, Forecast History, Logs, etc.) displays the expected JSON output.

