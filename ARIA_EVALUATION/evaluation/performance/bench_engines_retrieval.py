"""Deterministic engines + retrieval micro-benchmarks. No provider calls, no network (socket-level block + keys blanked).
Run with the env from common.safe_env (scratch DB). Output: results/engines_retrieval.json"""
import json, os, sys, time, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, pct, block_network, lower_priority
lower_priority(); block_network()
from loguru import logger; logger.remove()
from common import rss_mb as rss
out = {"env": {"OMP": os.environ.get("OMP_NUM_THREADS"), "cpu_logical": os.cpu_count()}}


def timeit(fn, n):
    xs = []
    for _ in range(n):
        t = time.perf_counter(); fn(); xs.append((time.perf_counter() - t) * 1000)
    return {"n": n, "p50_ms": round(pct(xs, 50), 4), "p95_ms": round(pct(xs, 95), 4), "p99_ms": round(pct(xs, 99), 4), "max_ms": round(max(xs), 3)}


# ---- deterministic engines -------------------------------------------------
from modules.finance import engine, tax, sip_emi_calc
P = {"age": 32, "dependents": 1, "monthly_income": 120000, "income_stability": "stable", "risk_tolerance": "Moderate", "city_tier": 1,
     "marital_status": "married", "term_cover": 10000000, "health_cover": 1000000, "used_80c": 100000, "tax_regime": "new",
     "expenses": {"rent": 30000, "food": 15000, "transport": 5000, "entertainment": 8000, "other": 10000},
     "assets": {"cash": 200000, "fd": 300000, "mf": 500000, "stocks": 200000, "gold": 100000, "epf": 400000, "ppf": 100000},
     "loans": [{"emi": 15000, "months_left": 120, "rate_pct": 9.0}, {"emi": 5000, "months_left": 24, "rate_pct": 13}],
     "goals": [{"name": "house", "target": 5000000, "years": 10}, {"name": "education", "target": 3000000, "years": 15}]}
eng = {}
for name, fn in {"sip_future_value": lambda: sip_emi_calc.sip_future_value(10000, 20, 12), "sip_required": lambda: sip_emi_calc.sip_required(10_000_000, 20, 12),
                 "emi": lambda: sip_emi_calc.emi(5_000_000, 8.5, 20), "tax_new": lambda: tax.tax_new(1_800_000), "tax_old": lambda: tax.tax_old(1_800_000, 150000, 25000),
                 "snapshot": lambda: engine.snapshot(P), "goals": lambda: engine.goals(P), "retirement": lambda: engine.retirement(P),
                 "health_score": lambda: engine.health_score(P), "afford_purchase": lambda: engine.afford_purchase(P, 8_000_000, "home"),
                 "afford_sip": lambda: engine.afford_sip(P, 20000), "what_if": lambda: engine.what_if(P, {"monthly_income": 20000}),
                 "tax_compare": lambda: engine.tax_compare(P)}.items():
    try:
        eng[name] = timeit(fn, 2000)
    except Exception as e:
        eng[name] = {"error": f"{type(e).__name__}: {e}"[:120]}
out["engines"] = eng

# ---- text understanding (regex / spell) -------------------------------------
from shared.understand import normalize
from modules.finance.pipeline import finance_intent
from core.router import route_query
Q = ["what is my savings rate", "should i buy a 80 lakh flat", "how much sip to reach 1 crore in 20 years", "wat is compund intrest", "kya sip karna chahiye",
     "old vs new tax regime for me", "tell me about reliance industries fundamentals", "sensex today", "i want to retire at 55", "hello"]
normalize(Q[0]); t = {}
t["normalize"] = timeit(lambda: [normalize(q) for q in Q], 200); t["normalize"]["per_query_note"] = "each sample = 10 queries"
t["finance_intent"] = timeit(lambda: [finance_intent(q.lower()) for q in Q], 500); t["finance_intent"]["per_query_note"] = "each sample = 10 queries"
out["text"] = t

# ---- trust / grounding (deterministic post-processor), long reply ------------
from modules.qa import trust
src = " ".join(f"metric{i} {i*13.7:.2f} crore" for i in range(300))
resp = {"domain": "equity_research", "response": "Revenue was 1234.5 crore, profit 99.9. " * 60 + src[:2000], "context": {"data": src}}
try:
    out["trust_enforce"] = timeit(lambda: trust.enforce(dict(resp)), 200)
except Exception as e:
    out["trust_enforce"] = {"error": f"{type(e).__name__}: {e}"[:160]}

# ---- retrieval: concept KB + finance knowledge (SBERT+FAISS) -----------------
rss0 = rss()
from modules.tutor import retriever
from shared import finance_knowledge, vector_store
t0 = time.perf_counter(); retriever.retrieve("warm up"); out["sbert_first_call_s"] = round(time.perf_counter() - t0, 2)
out["rss_mb_after_sbert_load"] = rss(); out["rss_mb_before_sbert"] = rss0
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ret = json.loads((Path(__file__).resolve().parents[1] / "ai_tutor_retrieval_results.json").read_text(encoding="utf-8"))
qs = [r["q"] for r in ret["in_kb"]] + [r["q"] for r in ret.get("ood", [])]
qs = qs * 4  # 4 passes over 70 queries -> n = 280 (the encoder has no query cache; repeats are real recomputation)
random.Random(1).shuffle(qs)
out["concept_kb"] = {"queries_distinct": len(set(qs)), **timeit(lambda f=iter(qs): retriever.retrieve(next(f), k=5), len(qs))}
qs2 = [q for q in qs][:140]
out["concept_best_gate"] = {"queries_distinct": len(set(qs2)), **timeit(lambda f=iter(qs2): retriever.best(next(f)), len(qs2))}
out["finance_knowledge"] = {"queries_distinct": len(set(qs2)), **timeit(lambda f=iter(qs2): finance_knowledge.retrieve_passages(next(f)), len(qs2))}
# split cost: query encode vs per-call disk read of FAISS + meta.json (vector_store.search re-reads both on every call)
import faiss
nsd = vector_store._namespace_dir("concepts")
out["faiss_read_index_ms"] = timeit(lambda: (faiss.read_index(str(nsd / "index.faiss")), json.loads((nsd / "meta.json").read_text(encoding="utf-8"))), 300)
enc = vector_store._get_encoder()
out["sbert_encode_one_ms"] = timeit(lambda: enc.encode(["what is the sharpe ratio"], normalize_embeddings=True, convert_to_numpy=True), 100)
out["rss_mb_end"] = rss()
(RESULTS / "engines_retrieval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps({k: (v if not isinstance(v, dict) or "p50_ms" in v else "...") for k, v in out.items()}, indent=1)[:3000])
