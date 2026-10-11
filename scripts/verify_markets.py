"""Hit every Vitara Markets endpoint on a running API and check latency and schema. Usage: python scripts/verify_markets.py [base_url]"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.routes.markets import SCHEMA  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
CALLS = [("overview", "/overview"), ("movers", "/movers"), ("sectors", "/sectors"), ("news", "/news"),
         ("chart", "/chart?symbol=%5ENSEI&range=1D"), ("chart", "/chart?symbol=RELIANCE.NS&range=1Y"),
         ("quote", "/quote?symbol=RELIANCE.NS"), (None, "/search?q=tata")]

fail = 0
print(f"{'endpoint':<40}{'status':>7}{'secs':>7}  result")
for schema, path in CALLS:
    t = time.time()
    r = requests.get(f"{BASE}/api/markets{path}", timeout=60)
    dt = time.time() - t
    body = r.json()
    missing = sorted(SCHEMA[schema] - body.keys()) if schema and isinstance(body, dict) else []
    note = "missing " + ",".join(missing) if missing else "ok"
    if r.status_code != 200 or missing or (schema == "overview" and dt >= 1):
        fail += 1
        note = "FAIL " + note
    detail = len(body) if isinstance(body, list) else len(body.get("bars", body.get("items", body)))
    print(f"{path:<40}{r.status_code:>7}{dt:>7.2f}  {note} (n={detail})")
sys.exit(1 if fail else 0)
