"""Token cost per request path (computed from the prompts actually built, with a STUB model: no provider call) and graceful behaviour when the
providers are down. In-process FastAPI TestClient, scratch SQLite DB, network blocked, HF offline.
Modes of the stubbed backends (patched at ai.llm.groq_client._BACKENDS/_call_groq/_call_gemini, so the real fallback chain + retry logic runs):
  ok       canned ~110-word reply
  down503  every backend raises '503 Service Unavailable'   -> exercises the 2-pass retry with sleep (sleeps are RECORDED, not performed)
  down401  every backend raises 'invalid api key'            -> single pass over 4 backends
  quota    every backend raises 'tokens per day'             -> marks backends dead for 30 min
Output: results/cost_failure.json
"""
import json, os, sys, time, types, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority, rss_mb, peak_rss_mb, avail_mb
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove(); logger.add(sys.stderr, level="ERROR")  # keep output small
from fastapi.testclient import TestClient
import ai.llm.groq_client as G
from shared import user_store as store
from api.main import app
assert "user_profiles" not in str(store._engine.url)

MODE = {"m": "ok"}
CALLS = []          # per backend call: (backend, system_chars, prompt_chars, out_chars)
SLEEPS = []
CANNED = ("Here is a clear explanation. " * 20).strip()


def make(name):
    def f(prompt, system_prompt, model=None):
        m = MODE["m"]
        CALLS.append([name, len(system_prompt or ""), len(prompt), 0 if m != "ok" else len(CANNED), m])
        if m == "ok":
            return CANNED
        raise RuntimeError({"down503": "503 Service Unavailable (stub)", "down401": "invalid api key (stub)", "quota": "429 tokens per day limit (stub)"}[m])
    return f


G._BACKENDS = (("groq", make("groq")), ("gemini", make("gemini")))
G._call_groq = make("groq-alt")           # used by the groq-small / groq-qwen entries (looked up through the module global at call time)
G.time = types.SimpleNamespace(sleep=lambda s: SLEEPS.append(s), monotonic=time.monotonic, perf_counter=time.perf_counter, time=time.time)
G._dead.clear()

c = TestClient(app)
OWNER = "cost-owner"
store.save_financial_profile(OWNER, source="chat", monthly_income=120000, age=32, risk_tolerance="Moderate",
                             expenses={"rent": 30000, "food": 15000, "transport": 5000, "entertainment": 8000, "other": 10000},
                             assets={"cash": 200000, "fd": 300000, "mf": 500000}, loans=[])

PATHS = [
    ("smalltalk", "hello"),
    ("general", "recommend a good movie"),
    ("tutor_concept", "what is the sharpe ratio"),
    ("tutor_concept_2", "explain compound interest with an example"),
    ("finance_calc", "how much sip do i need to reach 1 crore in 20 years"),
    ("finance_profile", "what is my savings rate"),
    ("finance_tax", "old vs new tax regime for me"),
    ("market", "how is the nifty doing today"),
    ("equity_research", "tell me about TCS fundamentals"),
    ("lookup", "what is the market cap of Zomato"),
]


def post(q, sid=None, rid=None):
    sid = sid or f"s-{uuid.uuid4().hex[:8]}"
    CALLS.clear(); SLEEPS.clear()
    t = time.perf_counter()
    r = c.post("/api/chat", json={"query": q, "session_id": sid, "owner_id": OWNER, "request_id": rid or uuid.uuid4().hex, "mode": "Normal Mode"})
    ms = (time.perf_counter() - t) * 1000
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    tok = lambda chars: round(chars / 4)  # ESTIMATE: ~4 characters per token for English; no provider tokenizer is used
    return {"status": r.status_code, "ms": round(ms), "route": body.get("domain"), "degraded": bool(body.get("degraded")),
            "llm_calls": len(CALLS), "backends": [x[0] for x in CALLS], "virtual_sleep_s": round(sum(SLEEPS), 1),
            "prompt_chars": sum(x[1] + x[2] for x in CALLS), "est_in_tokens": tok(sum(x[1] + x[2] for x in CALLS)), "est_out_tokens": tok(sum(x[3] for x in CALLS)),
            "resp_head": str(body.get("response", body.get("detail", "")))[:110]}, sid


res = {"env": {"avail_mb_start": avail_mb(), "rss_after_import": rss_mb()}}
# ---- 1. warm-up chat so one-off model loading is excluded from per-path numbers
MODE["m"] = "ok"
t = time.perf_counter(); post("what is a mutual fund"); res["first_chat_cold_s"] = round(time.perf_counter() - t, 1)
res["rss_after_first_chat_mb"] = rss_mb()

# ---- 2. cost + latency per path, stub model replies instantly (latency = ARIA's own overhead)
res["paths_ok"] = {}
for name, q in PATHS:
    runs = [post(q)[0] for _ in range(3)]
    res["paths_ok"][name] = {"query": q, "runs": runs}
    print(name, runs[-1]["status"], runs[-1]["route"], "calls", runs[-1]["llm_calls"], "in_tok~", runs[-1]["est_in_tokens"], "ms", [r["ms"] for r in runs], flush=True)

# ---- 3. prompt growth with conversation history (same tutor question; N prior complete turns in the SAME conversation)
res["history_growth"] = []
sid = f"g-{uuid.uuid4().hex[:6]}"
done = 0
for target in (0, 5, 20, 60):
    while done < target:
        post(f"tell me about sip number {done} for beginners and what returns are typical", sid); done += 1
    r, _ = post("explain compound interest with an example", sid)
    res["history_growth"].append({"prior_turns": done, **{k: r[k] for k in ("ms", "llm_calls", "est_in_tokens", "prompt_chars")}})
    print("growth", res["history_growth"][-1], flush=True)

# ---- 4. providers down
res["down"] = {}
for mode in ("down503", "down401", "quota"):
    G._dead.clear(); MODE["m"] = mode; res["down"][mode] = {}
    for name, q in PATHS[:8]:
        r, sid = post(q); res["down"][mode][name] = r
        print(mode, name, r["status"], r["route"], "degraded", r["degraded"], "calls", r["llm_calls"], "vsleep", r["virtual_sleep_s"], "ms", r["ms"], "|", r["resp_head"][:60], flush=True)
G._dead.clear(); MODE["m"] = "ok"

# ---- 5. same request_id retried after an all-providers-down answer (does the user get the real answer on retry?)
rid = uuid.uuid4().hex; sid = "retry-" + uuid.uuid4().hex[:6]
MODE["m"] = "down401"; r1, _ = post("recommend a good movie", sid, rid)
MODE["m"] = "ok"; G._dead.clear(); r2, _ = post("recommend a good movie", sid, rid)
res["retry_same_request_id"] = {"first_while_down": r1, "retry_when_up": r2}
# a fresh request_id works
r3, _ = post("recommend a good movie", sid); res["retry_same_request_id"]["new_request_id_when_up"] = r3
res["peak_rss_mb"] = peak_rss_mb()
(RESULTS / "cost_failure.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print("peak rss", res["peak_rss_mb"])
