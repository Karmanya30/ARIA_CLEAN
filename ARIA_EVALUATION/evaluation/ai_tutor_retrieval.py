"""Tutor concept retrieval (SBERT + FAISS over 50 concepts): top-1 / hit@5 / threshold gate (best()) / latency. No LLM."""
import json, os, sys, time, statistics
sys.path.insert(0, r"E:\ARIA")
from modules.tutor import retriever

# (query, gold concept id) - paraphrases written by the evaluator, not copied from aliases
IN_KB = [
    ("what is simple interest", "simple_interest"), ("how does interest on interest work over the years", "compound_interest"),
    ("explain CAGR", "cagr"), ("what is the XIRR of irregular cash flows", "xirr"), ("what will my money be worth in future", "future_value"),
    ("what is the present value of money", "present_value"), ("explain net present value", "npv"), ("what is a mutual fund", "mutual_fund"),
    ("what is a systematic investment plan", "sip"), ("explain ELSS tax saving funds", "elss"), ("what is an ETF", "etf"),
    ("what is an index fund", "index_fund"), ("what is a fixed deposit", "fd"), ("tell me about PPF", "ppf"),
    ("what is national pension system", "nps"), ("what is direct equity investing", "direct_equity"),
    ("what is standard deviation of returns", "standard_deviation"), ("what is volatility in markets", "volatility"),
    ("explain beta of a stock", "beta"), ("what is the sharpe ratio", "sharpe_ratio"), ("what is maximum drawdown", "drawdown"),
    ("why diversify my portfolio", "diversification"), ("what is a stock exchange", "stock_exchange"),
    ("what is T+1 settlement", "settlement_cycle"), ("what is bid ask spread", "bid_ask_spread"), ("what is market capitalisation", "market_cap"),
    ("explain price to earnings ratio", "pe_ratio"), ("what is dividend yield", "dividend_yield"), ("what is section 80C", "section_80c"),
    ("what is section 80D health insurance deduction", "section_80d"), ("long term capital gains tax", "ltcg"),
    ("short term capital gains tax", "stcg"), ("old versus new tax regime", "tax_regime_comparison"), ("what is HRA exemption", "hra"),
    ("what is the standard deduction", "standard_deduction"), ("how big should my emergency fund be", "emergency_fund"),
    ("what is a debt trap", "debt_trap"), ("how is credit score calculated", "credit_score"), ("what is net worth", "net_worth"),
    ("what is inflation", "inflation"), ("what is real return after inflation", "real_return"), ("what is EMI", "emi"),
    ("fixed vs floating interest rate on loans", "fixed_vs_floating_rate"), ("what is loan amortization", "amortization"),
    ("should I prepay my home loan", "prepayment"), ("what is a CIBIL score", "cibil_score"), ("how much corpus do I need to retire", "retirement_corpus"),
    ("how inflation changes what I need after retirement", "inflation_adjusted_need"), ("what is an annuity", "annuity"),
    ("what is a safe withdrawal rate", "withdrawal_rate"),
]
# should NOT be matched to a concept (best() must return None)
OOD = ["write a python function to sort a list", "what is the capital of France", "who is the CEO of Infosys", "tell me a joke",
       "how do I bake a cake", "what is the weather today", "explain quantum computing", "how do I read a balance sheet",
       "what is a credit default swap", "explain options greeks delta gamma", "what is a futures contract", "explain the black scholes model",
       "what is a bond duration", "what is expense ratio", "how does a REIT work", "what is a SWP systematic withdrawal plan",
       "what is cryptocurrency staking", "what is GST", "explain a P2P lending platform", "what is Sukanya Samriddhi"]

t0 = time.perf_counter(); retriever.retrieve("warm up"); warm = time.perf_counter() - t0
lat, res = [], []
top1 = hit5 = accepted = accepted_right = 0
for q, gold in IN_KB:
    t = time.perf_counter(); hits = retriever.retrieve(q, k=5); lat.append((time.perf_counter() - t) * 1000)
    ids = [h["id"] for h in hits]; best = retriever.best(q)
    top1 += ids[0] == gold; hit5 += gold in ids
    accepted += best is not None; accepted_right += bool(best and best["id"] == gold)
    res.append({"q": q, "gold": gold, "top": ids[:3], "score": round(hits[0]["score"], 3), "accepted": best["id"] if best else None})
ood_res, false_acc = [], 0
for q in OOD:
    hits = retriever.retrieve(q, k=1); best = retriever.best(q)
    false_acc += best is not None
    ood_res.append({"q": q, "top": hits[0]["id"], "score": round(hits[0]["score"], 3), "accepted": best["id"] if best else None})
n = len(IN_KB)
summary = {"in_kb_n": n, "top1": top1 / n, "hit_at_5": hit5 / n, "best_accept_rate": accepted / n, "best_accept_correct": accepted_right / n,
           "ood_n": len(OOD), "ood_false_accept": false_acc, "ood_false_accept_rate": false_acc / len(OOD),
           "warm_load_s": round(warm, 2), "latency_ms_p50": round(statistics.median(lat), 1), "latency_ms_p95": round(sorted(lat)[int(.95 * len(lat)) - 1], 1)}
print(json.dumps(summary, indent=1))
for r in res:
    if r["top"][0] != r["gold"] or r["accepted"] != r["gold"]:
        print("IN-KB MISS", r)
for r in ood_res:
    print("OOD", r)
json.dump({"summary": summary, "in_kb": res, "ood": ood_res}, open(r"E:\ARIA\ARIA_EVALUATION\evaluation\ai_tutor_retrieval_results.json", "w", encoding="utf-8"), indent=1)
