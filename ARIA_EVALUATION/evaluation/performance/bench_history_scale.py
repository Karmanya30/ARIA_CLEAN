"""History / list / search / memory-retrieval at scale on a SCRATCH SQLite DB (synthetic data only), through the real FastAPI app via TestClient.
usage: python bench_history_scale.py [--convs 200 --per 50 --big 3000]   Output: results/history_scale.json
No LLM, no network. Conversation memory semantic mode is OFF here (ARIA_MEMORY_SEMANTIC=0); it is measured in bench_memory_semantic.py."""
import json, os, sys, time, random, argparse, uuid, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, ROOT, pct, block_network, lower_priority
os.environ["ARIA_MEMORY_SEMANTIC"] = "0"; os.environ["ARIA_WARMUP"] = "0"; os.environ["ARIA_AUTH_MODE"] = "private"
assert os.environ.get("DB_URL", "").startswith("sqlite:///") and "aria_perf_" in os.environ["DB_URL"], "refusing: DB_URL must be a scratch perf DB"
lower_priority(); block_network()
from loguru import logger; logger.remove(); logger.add(sys.stderr, level="ERROR")  # keep output small
ap = argparse.ArgumentParser(); ap.add_argument("--convs", type=int, default=200); ap.add_argument("--per", type=int, default=50); ap.add_argument("--big", type=int, default=3000)
args = ap.parse_args()
from common import rss_mb
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from shared import user_store as store
from shared import conversation_memory as M
from api.main import app
assert "user_profiles" not in str(store._engine.url), store._engine.url
c = TestClient(app)
OWNER = "perf-owner-1"
rnd = random.Random(7)
TOPICS = ["sip", "emi", "nifty", "tcs", "hdfc bank", "tax regime", "ppf", "gold", "inflation", "mutual fund", "reliance", "retirement"]
def resp_json(i, q):
    body = f"Here is the answer to {q}. " + ("Detail sentence about markets and returns. " * 40)
    blocks = [{"type": "text", "content": body}, {"type": "metric", "label": "x", "value": str(i)}]
    return json.dumps({"domain": "finance", "response": body, "blocks": blocks, "context": {"data": "synthetic " * 100}})
t0 = datetime.now(timezone.utc) - timedelta(days=200)
def seed(n_conv, per, owner, prefix):
    ids = []
    with store._SessionLocal() as db:
        rows_c, rows_t = [], []
        for ci in range(n_conv):
            cid = f"{prefix}-{ci}"; ids.append(cid)
            ts = (t0 + timedelta(hours=ci)).isoformat()
            rows_c.append(M.Conversation(id=cid, owner_id=owner, title=f"{rnd.choice(TOPICS)} chat {ci}", created_at=ts, updated_at=ts))
        db.add_all(rows_c); db.commit()
        for cid in ids:
            for k in range(per):
                q = f"{rnd.choice(TOPICS)} question {k} {uuid.uuid4().hex[:6]}"
                rows_t.append(M.Turn(conversation_id=cid, request_id=uuid.uuid4().hex, query=q, response_json=resp_json(k, q), status="complete",
                                     created_at=(t0 + timedelta(minutes=k)).isoformat()))
        db.add_all(rows_t); db.commit()
    return ids
t = time.perf_counter(); ids = seed(args.convs, args.per, OWNER, "c"); big = seed(1, args.big, OWNER, "big")[0]
seed(20, 20, "someone-else", "o")  # other owners' data must not slow or leak
total_turns = args.convs * args.per + args.big + 400
res = {"data": {"conversations": args.convs + 1, "turns_for_owner": args.convs * args.per + args.big, "turns_all_owners": total_turns,
                "avg_response_json_bytes": len(resp_json(0, "x")), "seed_s": round(time.perf_counter() - t, 1)}}
res["data"]["db_file_mb"] = round(os.path.getsize(store.DB_URL.replace("sqlite:///", "")) / 1e6, 1)

def bench(name, fn, n):
    xs, bad = [], 0; sizes = []
    for _ in range(n):
        t = time.perf_counter(); r = fn(); xs.append((time.perf_counter() - t) * 1000)
        if r.status_code != 200: bad += 1
        sizes.append(len(r.content))
    res[name] = {"n": n, "errors": bad, "p50_ms": round(pct(xs, 50), 1), "p95_ms": round(pct(xs, 95), 1), "p99_ms": round(pct(xs, 99), 1),
                 "max_ms": round(max(xs), 1), "resp_kb": round(sum(sizes) / len(sizes) / 1024, 1)}
    print(name, res[name], flush=True)
p = {"owner_id": OWNER}
bench("list_page1", lambda: c.get("/api/conversations", params=p), 40)
bench("list_page_deep_offset150", lambda: c.get("/api/conversations", params={**p, "offset": 150}), 20)
bench("search_title_hit(q=nifty)", lambda: c.get("/api/conversations", params={**p, "q": "nifty"}), 15)
bench("search_body_rare(q=question 7)", lambda: c.get("/api/conversations", params={**p, "q": "question 7"}), 15)
bench("search_miss(q=zzzqqq)", lambda: c.get("/api/conversations", params={**p, "q": "zzzqqq"}), 15)
bench("messages_page50_big", lambda: c.get(f"/api/conversations/{big}/messages", params=p), 40)
bench("messages_page50_small", lambda: c.get(f"/api/conversations/{ids[5]}/messages", params=p), 40)
bench("export_json_big", lambda: c.get(f"/api/conversations/{big}/export", params=p), 5)
bench("export_json_50turns", lambda: c.get(f"/api/conversations/{ids[7]}/export", params=p), 10)
bench("chat_history_unpaged_big", lambda: c.get("/api/chat/history", params={**p, "session_id": big}), 8)
bench("chat_history_unpaged_50turns", lambda: c.get("/api/chat/history", params={**p, "session_id": ids[9]}), 20)
# memory retrieval (called inside every chat turn): BM25 over ALL the owner's complete turns, semantic off
tok = M.store.current_owner.set(OWNER)
def mem(session):
    xs = []; recs = None
    for q in ["what did we discuss about sip", "compare it with the previous one", "nifty question 3"] * 3:
        t = time.perf_counter(); recs, diag = M.retrieve(session, q); xs.append((time.perf_counter() - t) * 1000)
    return {"n": len(xs), "p50_ms": round(pct(xs, 50), 1), "max_ms": round(max(xs), 1), "archive_records": diag["archive_records"]}
res["memory_retrieve_bm25_owner_archive"] = mem(ids[3]); print("memory", res["memory_retrieve_bm25_owner_archive"], flush=True)
t = time.perf_counter(); ctx = M.build_context(ids[3], "what did we discuss about sip"); res["memory_build_context_ms_single"] = round((time.perf_counter() - t) * 1000, 1)
res["memory_context_chars"] = len(ctx["text"]); res["memory_context_tokens_utf8_upper_bound"] = ctx["diagnostics"]["memory_tokens"]
M.store.current_owner.reset(tok)
res["rss_mb_end"] = rss_mb()
(RESULTS / "history_scale.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
