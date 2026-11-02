"""SQLite behaviour under concurrent writers + request-lease / retry semantics. Scratch DB, synthetic data, <= 8 threads, bounded.
Output: results/sqlite_concurrency.json"""
import json, os, sys, time, threading, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority
os.environ["ARIA_WARMUP"] = "0"; os.environ["ARIA_AUTH_MODE"] = "private"; os.environ["ARIA_MEMORY_SEMANTIC"] = "0"
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove(); logger.add(sys.stderr, level="ERROR")  # keep output small
from sqlalchemy import text
from shared import user_store as store, conversation_memory as M, conversation_history as H
assert "user_profiles" not in str(store._engine.url)
res = {}
with store._engine.connect() as c:
    res["journal_mode"] = c.execute(text("PRAGMA journal_mode")).scalar()
res["pool"] = type(store._engine.pool).__name__ + f" size={store._engine.pool.size()}"
RESP = {"domain": "finance", "response": "ok " * 300, "blocks": []}


def cycle(owner, sid, i):
    tok = store.current_owner.set(owner)
    try:
        t = time.perf_counter(); rid = uuid.uuid4().hex
        req = M.begin(sid, f"q {i}", rid)
        tok2 = M.active_request.set(req)
        try:
            M.snapshot(req, RESP); M.complete(sid, f"q {i}", RESP); M.checkpoint(sid, {"x": i})
        finally:
            M.active_request.reset(tok2)
        return (time.perf_counter() - t) * 1000
    finally:
        store.current_owner.reset(tok)


def writers(n_threads, per_thread, same_conv):
    lat, errs = [], {}
    lock = threading.Lock()

    def work(k):
        sid = "shared-conv" if same_conv else f"w{n_threads}-{k}"
        for i in range(per_thread):
            try:
                x = cycle("w-owner", sid, i)
                with lock:
                    lat.append(x)
            except Exception as e:
                key = type(e).__name__ + ":" + str(e)[:70]
                with lock:
                    errs[key] = errs.get(key, 0) + 1
    ts = [threading.Thread(target=work, args=(k,)) for k in range(n_threads)]
    t0 = time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]; wall = time.perf_counter() - t0
    return {"threads": n_threads, "same_conversation": same_conv, "cycles_ok": len(lat), "errors": errs, "wall_s": round(wall, 2),
            "throughput_cycles_per_s": round(len(lat) / wall, 1), "p50_ms": round(pct(lat, 50), 1) if lat else None,
            "p95_ms": round(pct(lat, 95), 1) if lat else None, "p99_ms": round(pct(lat, 99), 1) if lat else None, "max_ms": round(max(lat), 1) if lat else None}


res["writers_separate_conversations"] = [writers(n, 40, False) for n in (1, 2, 4, 8)]
for r in res["writers_separate_conversations"]:
    print(r, flush=True)
res["writers_same_conversation"] = [writers(n, 25, True) for n in (1, 4, 8)]
for r in res["writers_same_conversation"]:
    print(r, flush=True)

# --- leases ---------------------------------------------------------------
L = {}
tok = store.current_owner.set("lease-owner")
# (a) 8 workers race to begin() the SAME request_id (no in-process session lock = like several uvicorn workers)
sid, rid = "lease-a", "rid-1"; M.conversation(sid); out = []; lk = threading.Lock(); bar = threading.Barrier(8)


def race():
    t = store.current_owner.set("lease-owner")
    try:
        bar.wait(); r = M.begin(sid, "same query", rid); x = ("lease" if r.get("lease") else r["status"])
    except M.RequestBusy:
        x = "RequestBusy"
    except Exception as e:
        x = type(e).__name__ + ":" + str(e)[:60]
    finally:
        store.current_owner.reset(t)
    with lk:
        out.append(x)


ts = [threading.Thread(target=race) for _ in range(8)]; [t.start() for t in ts]; [t.join() for t in ts]
L["race_8_workers_same_request_id"] = {k: out.count(k) for k in set(out)}
# (b) crash after begin (no fail()): retry of the same request_id within the lease window
sid, rid = "lease-b", "rid-2"; first = M.begin(sid, "q", rid)
try:
    M.begin(sid, "q", rid); L["retry_after_crash_within_lease"] = "allowed (unexpected)"
except M.RequestBusy:
    L["retry_after_crash_within_lease"] = "RequestBusy -> HTTP 409 for the remaining lease time"
L["lease_seconds_default"] = int(os.getenv("ARIA_REQUEST_LEASE_SECONDS", "1800"))
# (c) lease expiry takeover, and the stale worker's completion
os.environ["ARIA_REQUEST_LEASE_SECONDS"] = "1"
sid, rid = "lease-c", "rid-3"; a = M.begin(sid, "q", rid); time.sleep(1.3); b = M.begin(sid, "q", rid)
L["takeover_after_expiry"] = {"new_lease_differs": a.get("lease") != b.get("lease")}
tk = M.active_request.set(a)
try:
    M.complete(sid, "q", RESP); L["takeover_after_expiry"]["stale_worker_complete"] = "ACCEPTED (unexpected)"
except M.RequestBusy:
    L["takeover_after_expiry"]["stale_worker_complete"] = "rejected RequestBusy (correct)"
finally:
    M.active_request.reset(tk)
tk = M.active_request.set(b); M.complete(sid, "q", RESP); M.active_request.reset(tk)
L["takeover_after_expiry"]["final_status"] = M.begin(sid, "q", rid)["status"]
# (d) explicit failure then retry
os.environ["ARIA_REQUEST_LEASE_SECONDS"] = "1800"
sid, rid = "lease-d", "rid-4"; a = M.begin(sid, "q", rid); M.fail(a); b = M.begin(sid, "q", rid)
L["retry_after_fail"] = "new lease granted" if b.get("lease") else b["status"]
# (e) a reply that starts with "Error:" is stored status=failed -> does a retry with the same id regenerate?
sid, rid = "lease-e", "rid-5"; a = M.begin(sid, "q", rid); tk = M.active_request.set(a)
M.complete(sid, "q", {"domain": "general", "response": "Error: all backends down"}); M.active_request.reset(tk)
b = M.begin(sid, "q", rid); L["retry_after_Error_reply"] = "regenerates (new lease)" if b.get("lease") else f"replays status={b['status']}"
# (f) the DEGRADED text (what the user sees when providers are down) does not start with 'error' -> stored complete?
sid, rid = "lease-f", "rid-6"; a = M.begin(sid, "q", rid); tk = M.active_request.set(a)
from modules.qa import trust
M.complete(sid, "q", {"domain": "general", "response": trust.DEGRADED, "degraded": True}); M.active_request.reset(tk)
b = M.begin(sid, "q", rid); L["retry_after_DEGRADED_reply_same_request_id"] = "regenerates (new lease)" if b.get("lease") else f"replays stored degraded answer, status={b['status']}"
res["leases"] = L; print(json.dumps(L, indent=1), flush=True)
store.current_owner.reset(tok)

# --- readers under writer load ---------------------------------------------
for k in range(30):
    for i in range(10):
        cycle("rd-owner", f"rd-{k}", i)


def read_load(n_readers, n_writers, secs=8):
    stop = time.time() + secs; lat = []; errs = [0]; wcount = [0]; lk = threading.Lock()

    def reader():
        tk = store.current_owner.set("rd-owner")
        while time.time() < stop:
            t = time.perf_counter()
            try:
                H.list_conversations(limit=30); H.messages("rd-3", limit=50)
            except Exception:
                errs[0] += 1; continue
            with lk:
                lat.append((time.perf_counter() - t) * 1000)

    def writer(k):
        while time.time() < stop:
            try:
                cycle("w-owner", f"rw-{k}", wcount[0]); wcount[0] += 1
            except Exception:
                errs[0] += 1
    ts = [threading.Thread(target=reader) for _ in range(n_readers)] + [threading.Thread(target=writer, args=(k,)) for k in range(n_writers)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return {"readers": n_readers, "writers": n_writers, "secs": secs, "read_pairs": len(lat), "write_cycles": wcount[0], "errors": errs[0],
            "read_p50_ms": round(pct(lat, 50), 1), "read_p95_ms": round(pct(lat, 95), 1), "read_p99_ms": round(pct(lat, 99), 1), "read_max_ms": round(max(lat), 1)}


res["read_under_write"] = [read_load(6, 0), read_load(6, 2)]
for r in res["read_under_write"]:
    print(r, flush=True)
(RESULTS / "sqlite_concurrency.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
