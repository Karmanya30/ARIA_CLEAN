"""Conversation-memory retrieval cost vs the owner's archive size (the cost is paid inside EVERY chat turn: shared/conversation_memory.retrieve).
Scratch SQLite, synthetic turns (~4.6 KB response JSON each). Modes: bm25 (semantic off), stub-semantic (zero-cost fake encoder: isolates DB/Python overhead of
the 200-candidate x 2 embedding lookups), real-semantic (only with --real: loads SBERT). Output: results/memory_scaling.json"""
import json, os, sys, time, random, uuid, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority, rss_mb, peak_rss_mb
os.environ["ARIA_WARMUP"] = "0"; os.environ["ARIA_AUTH_MODE"] = "private"; os.environ.setdefault("HF_HUB_OFFLINE", "1")
assert "aria_perf_" in os.environ.get("DB_URL", ""), "refusing: DB_URL must be a scratch perf DB"
lower_priority(); block_network()
from loguru import logger; logger.remove(); logger.add(sys.stderr, level="ERROR")  # keep output small
ap = argparse.ArgumentParser(); ap.add_argument("--sizes", default="100,500,1000,2500,5000,10000"); ap.add_argument("--real", action="store_true")
args = ap.parse_args()
from datetime import datetime, timezone, timedelta
from shared import user_store as store, conversation_memory as M
assert "user_profiles" not in str(store._engine.url)
rnd = random.Random(3); OWNER = "mem-owner"
TOPICS = ["sip", "emi", "nifty", "tcs", "hdfc bank", "tax regime", "ppf", "gold", "inflation", "mutual fund", "reliance", "retirement"]
t0 = datetime.now(timezone.utc) - timedelta(days=100)
def add(n, start):
    with store._SessionLocal() as db:
        if start == 0:
            db.add(M.Conversation(id="m0", owner_id=OWNER, title="m", created_at=t0.isoformat(), updated_at=t0.isoformat())); db.commit()
        for k in range(start, start + n):
            q = f"{rnd.choice(TOPICS)} question {k} {uuid.uuid4().hex[:6]}"
            body = f"Answer to {q}. " + "Detail sentence about markets and returns. " * 40
            db.add(M.Turn(conversation_id="m0", request_id=uuid.uuid4().hex, query=q, status="complete", created_at=(t0 + timedelta(minutes=k)).isoformat(),
                          response_json=json.dumps({"domain": "finance", "response": body, "blocks": [{"type": "text", "content": body}]})))
        db.commit()
tok = store.current_owner.set(OWNER)
QS = ["what did we discuss about sip", "compare it with the previous one", "nifty question 3"]
def run(label, reps=3):
    xs = []
    for _ in range(reps):
        for q in QS:
            t = time.perf_counter(); _, d = M.retrieve("m0", q); xs.append((time.perf_counter() - t) * 1000)
    return {"n": len(xs), "p50_ms": round(pct(xs, 50), 1), "p95_ms": round(pct(xs, 95), 1), "max_ms": round(max(xs), 1), "records": d["archive_records"], "semantic": d["semantic"]}
res = {"bm25": [], "stub_semantic_cold": [], "stub_semantic_warm": []}
done = 0
class FakeEnc:
    def encode(self, texts, **k):
        import numpy as np
        out = []
        for t in texts:
            r = np.random.RandomState(abs(hash(t)) % (2**31)); v = r.randn(384); out.append(v / np.linalg.norm(v))
        return np.array(out)
import shared.vector_store as vs
for size in [int(s) for s in args.sizes.split(",")]:
    add(size - done, done); done = size
    os.environ["ARIA_MEMORY_SEMANTIC"] = "0"; r = run("bm25"); res["bm25"].append(r); print("bm25", size, r, flush=True)
    if size <= 5000:
        vs._encoder = FakeEnc(); os.environ["ARIA_MEMORY_SEMANTIC"] = "1"
        with store._SessionLocal() as db:
            db.query(M.Embedding).delete(); db.commit()
        r = run("cold", reps=1); res["stub_semantic_cold"].append(r); print("stub cold", size, r, flush=True)
        r = run("warm"); res["stub_semantic_warm"].append(r); print("stub warm", size, r, flush=True)
        vs._encoder = None
if args.real:
    os.environ["ARIA_MEMORY_SEMANTIC"] = "1"
    with store._SessionLocal() as db:
        db.query(M.Embedding).delete(); db.commit()
    t = time.perf_counter(); vs._get_encoder(); res["sbert_load_s"] = round(time.perf_counter() - t, 1)
    r = run("cold", reps=1); res["real_semantic_cold"] = r; print("real cold", r, flush=True)
    r = run("warm"); res["real_semantic_warm"] = r; print("real warm", r, flush=True)
    with store._SessionLocal() as db:
        res["embedding_rows_after"] = db.query(M.Embedding).count()
res["peak_rss_mb"] = peak_rss_mb()
store.current_owner.reset(tok)
(RESULTS / ("memory_scaling_real.json" if args.real else "memory_scaling.json")).write_text(json.dumps(res, indent=1), encoding="utf-8")
