"""Summarise results/routing_<arch>_<rep>.json -> results/routing_summary.json (+ printed table)."""
import glob, json, re, sys, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import RESULTS, pct
out = {}
for arch in "ABCDEH":
    files = sorted(glob.glob(str(RESULTS / f"routing_{arch}_*.json")))
    if not files:
        continue
    rows_by_rep = [json.load(open(f))["rows"] for f in files]
    allrows = [r for rows in rows_by_rep for r in rows]
    lat = [r["latency_ms"] for r in allrows]
    clean = [r["latency_ms"] for r in allrows if r["latency_ms"] < 60000]   # drops only the offline SBERT-load artefact (>60 s)
    def stats(xs):
        return {"n": len(xs), "p50": round(pct(xs, 50), 1), "p95": round(pct(xs, 95), 1), "p99": round(pct(xs, 99), 1), "max": round(max(xs)), "mean": round(statistics.mean(xs), 1),
                "over_1s": sum(x > 1000 for x in xs), "over_5s": sum(x > 5000 for x in xs)}
    n = len(allrows)
    acc = sum(r["got"] == r["expected"] or r["got"] in r["acceptable"] for r in allrows) / n
    out[arch] = {"reps": len(files), "queries_per_rep": len(rows_by_rep[0]), "all": stats(lat), "excluding_over_60s": stats(clean), "outliers_over_60s_ms": [round(x) for x in lat if x >= 60000],
                 "model_calls_per_query": round(sum(r["llm_calls"] for r in allrows) / n, 3), "tokens_per_query": round(sum(r["llm_tokens"] for r in allrows) / n, 1),
                 "recorded_model_ms_per_query": round(sum(r["llm_ms"] for r in allrows) / n, 1), "cache_misses": sum(r["llm_miss"] for r in allrows), "errors": sum(bool(r["error"]) for r in allrows),
                 "lenient_accuracy_all259": round(acc, 3), "rep_p50_p95": [[round(pct([r['latency_ms'] for r in rows], 50), 1), round(pct([r['latency_ms'] for r in rows if r['latency_ms'] < 60000], 95), 1)] for rows in rows_by_rep],
                 "slowest_5": [[round(r["latency_ms"]), r["query"][:40], r["got"]] for r in sorted(allrows, key=lambda r: -r["latency_ms"])[:5]],
                 "p50_by_route": {g: round(statistics.median([r["latency_ms"] for r in allrows if r["got"] == g]), 1) for g in sorted({r["got"] for r in allrows}) if sum(1 for r in allrows if r["got"] == g) >= 5}}
(RESULTS / "routing_summary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
for a, v in out.items():
    e = v["excluding_over_60s"]
    print(a, "reps", v["reps"], "all p50/p95/p99/max", v["all"]["p50"], v["all"]["p95"], v["all"]["p99"], v["all"]["max"], "| excl>60s p50/p95/p99/max", e["p50"], e["p95"], e["p99"], e["max"], "mean", e["mean"], ">1s", e["over_1s"], "/", e["n"],
          "| calls/q", v["model_calls_per_query"], "tok/q", v["tokens_per_query"], "modelms/q", v["recorded_model_ms_per_query"], "miss", v["cache_misses"], "err", v["errors"], "acc", v["lenient_accuracy_all259"])
