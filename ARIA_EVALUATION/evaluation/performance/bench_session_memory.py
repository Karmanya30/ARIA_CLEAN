"""In-process session cache growth (core/session._SESSIONS never evicts) and per-turn persistence cost vs conversation length.
No model, no network, scratch DB. execute_turn is called with a trivial action (so this is ARIA's own bookkeeping cost only).
Output: results/session_memory.json"""
import gc, json, os, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority, rss_mb
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", ARIA_MEMORY_SEMANTIC="0")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove()
from core import session as S
from shared import user_store as store, conversation_memory as M
assert "user_profiles" not in str(store._engine.url)
tok = store.current_owner.set("sm-owner")
BODY = "Detail sentence about markets and returns. " * 40
res = {"rss_start_mb": rss_mb()}


def turn(sid, i):
    q = f"question {i} {uuid.uuid4().hex[:6]}"
    t = time.perf_counter()
    S.execute_turn(sid, q, lambda: {"domain": "finance", "response": BODY + q, "blocks": [{"type": "text", "content": BODY}]}, uuid.uuid4().hex)
    return (time.perf_counter() - t) * 1000


# A) per-turn cost vs conversation length (one conversation)
rows = []
sid = "long-1"; done = 0
for target in (10, 100, 300):
    while done < target - 5:
        turn(sid, done); done += 1
    xs = [turn(sid, done + k) for k in range(5)]; done += 5
    rows.append({"turns_before": done - 5, "p50_ms": round(pct(xs, 50), 1), "max_ms": round(max(xs), 1)})
    print(rows[-1], flush=True)
    res["per_turn_cost_vs_length"] = rows; (RESULTS / "session_memory.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
res["per_turn_cost_vs_length"] = rows
res["rss_after_long_conversation_mb"] = rss_mb(); res["sessions_cached_after_A"] = len(S._SESSIONS)
# B) many sessions touched once each with 10 turns: RSS vs sessions
S._SESSIONS.clear(); S._LOCKS.clear(); gc.collect(); base = rss_mb(); res["rss_base_before_B_mb"] = base
rows = []
n = 0
for target in (25, 50, 100, 200):
    while n < target:
        sid = f"many-{n}"
        for k in range(10):
            turn(sid, k)
        n += 1
    gc.collect(); rows.append({"sessions": n, "turns_total": n * 10, "rss_mb": rss_mb(), "delta_mb": rss_mb() - base, "cached_sessions": len(S._SESSIONS), "locks": len(S._LOCKS)})
    print(rows[-1], flush=True)
    res["rss_vs_sessions"] = rows; (RESULTS / "session_memory.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
res["rss_vs_sessions"] = rows
store.current_owner.reset(tok)
(RESULTS / "session_memory.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
