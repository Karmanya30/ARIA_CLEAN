"""GET /api/instruments/search typeahead cost (the Markets/Explore search box) with the real 39k-item catalogue, in-process via TestClient. Network blocked."""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", HF_HUB_OFFLINE="1")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove()
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app)
c.get("/api/instruments/search", params={"q": "tcs"})
Q = ["t", "ta", "tat", "tata", "tata m", "tata motors", "relia", "reliance", "nifty", "hdfc", "hdfc bank", "infy", "zomato", "paytm", "sbi bluechip", "gold", "bitcoin", "apple", "xyzq", "kaynes technology"]
out = {}
for q in Q:
    xs = []
    for _ in range(3):
        t = time.perf_counter(); r = c.get("/api/instruments/search", params={"q": q}); xs.append((time.perf_counter() - t) * 1000)
    out[q] = {"status": r.status_code, "ms": [round(x) for x in xs], "n_items": len(r.json().get("items", [])) if r.status_code == 200 else None}
    print(q, out[q], flush=True)
allms = [m for v in out.values() for m in v["ms"]]
out["_summary"] = {"n": len(allms), "p50_ms": round(pct(allms, 50)), "p95_ms": round(pct(allms, 95)), "max_ms": max(allms)}
print(out["_summary"])
(RESULTS / "instrument_search.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
