"""Polite local HTTP load against ONE test server on port 8016 (serve_stub.py: real app, stub model, scratch DB). <= 8 client threads, bounded duration.
Measures: startup time to /api/health, cheap-endpoint throughput + latency at 1/4/8 threads, chat throughput with a 300 ms stub model at 1/2/4/8 threads
(error rate, 429/503 counts), rate-limit boundary. Output: results/http_load.json.  Run through run_scratch.sh (sets the scratch DB)."""
import http.client, json, os, subprocess, sys, time, threading, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, ROOT, pct, avail_mb
assert "aria_perf_" in os.environ.get("DB_URL", "")
PORT = 8016


def req(method, path, body=None, timeout=60):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    t = time.perf_counter()
    try:
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse(); data = r.read()
        return r.status, (time.perf_counter() - t) * 1000, data
    except Exception as e:
        return type(e).__name__, (time.perf_counter() - t) * 1000, b""
    finally:
        c.close()


res = {}


def start(extra_env):
    env = dict(os.environ, **extra_env)
    t0 = time.perf_counter()
    p = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-X", "utf8", str(Path(__file__).parent / "serve_stub.py")], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x00004000)
    while time.perf_counter() - t0 < 180:
        s, _, _ = req("GET", "/api/health", timeout=2)
        if s == 200:
            return p, time.perf_counter() - t0
        time.sleep(0.25)
    p.kill()
    raise SystemExit("server did not start")


def load(n_threads, secs, fn):
    stop = time.time() + secs; lat = []; codes = {}; lk = threading.Lock()

    def w(k):
        i = 0
        while time.time() < stop:
            s, ms, _ = fn(k, i); i += 1
            with lk:
                lat.append(ms); codes[str(s)] = codes.get(str(s), 0) + 1
    ts = [threading.Thread(target=w, args=(k,)) for k in range(n_threads)]
    t0 = time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]; wall = time.perf_counter() - t0
    ok = codes.get("200", 0)
    return {"threads": n_threads, "secs": round(wall, 1), "requests": len(lat), "codes": codes, "error_rate": round(1 - ok / max(1, len(lat)), 4),
            "throughput_rps": round(len(lat) / wall, 1), "p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1), "p99_ms": round(pct(lat, 99), 1), "max_ms": round(max(lat), 1)}


p, boot = start({"STUB_LLM_MS": "300"})
try:
    res["boot_to_health_s"] = round(boot, 1); res["avail_mb_after_boot"] = avail_mb()
    OWNER = "http-owner"
    for i in range(12):   # seed a few conversations through the real chat endpoint
        req("POST", "/api/chat", {"query": f"what is a sip number {i}", "session_id": f"seed-{i}", "owner_id": OWNER, "request_id": uuid.uuid4().hex})
    s, ms, _ = req("POST", "/api/chat", {"query": "what is the sharpe ratio", "session_id": "cold", "owner_id": OWNER, "request_id": uuid.uuid4().hex})
    res["tutor_chat_after_seed_ms"] = round(ms)
    res["health"] = [load(n, 6, lambda k, i: req("GET", "/api/health")) for n in (1, 4, 8)]
    for r in res["health"]:
        print("health", r, flush=True)
    res["conversations_list"] = [load(n, 6, lambda k, i: req("GET", f"/api/conversations?owner_id={OWNER}")) for n in (1, 4, 8)]
    for r in res["conversations_list"]:
        print("list", r, flush=True)
    res["chat_notes"] = "rate limiter is 120 POST/min per client IP; chat load is fixed at 24 requests per level (+12 seed +1) so the limiter is not what is measured"
    res["chat_stub300ms"] = []
    for n in (1, 2, 4, 8):
        lat = []; codes = {}; lk = threading.Lock(); N = 24; idx = [0]

        def w():
            while True:
                with lk:
                    if idx[0] >= N:
                        return
                    idx[0] += 1
                s, ms, _ = req("POST", "/api/chat", {"query": "what is the sharpe ratio", "session_id": f"load-{uuid.uuid4().hex[:6]}", "owner_id": OWNER, "request_id": uuid.uuid4().hex})
                with lk:
                    lat.append(ms); codes[str(s)] = codes.get(str(s), 0) + 1
        ts = [threading.Thread(target=w) for _ in range(n)]; t0 = time.perf_counter(); [t.start() for t in ts]; [t.join() for t in ts]; wall = time.perf_counter() - t0
        row = {"threads": n, "requests": N, "codes": codes, "wall_s": round(wall, 1), "throughput_rps": round(N / wall, 2),
               "p50_ms": round(pct(lat, 50)), "p95_ms": round(pct(lat, 95)), "max_ms": round(max(lat))}
        res["chat_stub300ms"].append(row); print("chat", row, flush=True)
        time.sleep(1)
    s, _, d = req("GET", "/__stats"); res["stub_llm_calls_total"] = json.loads(d) if s == 200 else None
    time.sleep(61)   # let the 60 s rate-limit window of the earlier POSTs expire
    codes = []; t0 = time.perf_counter()
    for i in range(130):
        s, ms, d = req("POST", "/api/chat/clear", {"session_id": f"rl-{i}", "owner_id": OWNER}); codes.append(s)
    res["rate_limit"] = {"posts_sent": 130, "first_429_at_request": (codes.index(429) + 1) if 429 in codes else None, "n_200": codes.count(200),
                         "n_429": codes.count(429), "window_s": round(time.perf_counter() - t0, 1)}
    print("rate", res["rate_limit"], flush=True)
finally:
    p.terminate()
    try:
        p.wait(15)
    except Exception:
        p.kill()
(RESULTS / "http_load.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
