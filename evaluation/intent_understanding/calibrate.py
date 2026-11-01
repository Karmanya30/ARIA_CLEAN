"""Chooses decision thresholds on the DEV split only (coordinate search over the structured-decision thresholds, LLM calls replayed from cache).

objective = lenient accuracy - 0.5 * share of questions that were clarified although a route was expected.
Writes thresholds.json; the TEST split is never read here. Raw similarity and model-stated confidence are ranking signals, not
probabilities: the thresholds are simply the dev-optimal cut-offs, and BENCHMARK_RESULTS.md reports how they transfer to test.

usage: python -X utf8 evaluation/intent_understanding/calibrate.py --arch E
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402

GRID = {"llm_intent": [0.6, 0.75, 0.85, 0.95], "llm_context": [0.5, 0.7, 0.85], "sr_veto": [0.45, 0.55, 0.7, 2.0],
        "sr_score": [0.25, 0.3, 0.4], "sr_margin": [0.03, 0.05, 0.1]}
START = {"sr_score": 0.30, "sr_margin": 0.05, "llm_intent": 0.75, "llm_context": 0.70, "sr_veto": 0.45}


def run(arch: str, th: dict, tag: str) -> float:
    # thresholds come from the environment, never from a thresholds file, during the search
    env = {**os.environ, **{f"ARIA_INTENT_{k.upper()}": str(v) for k, v in th.items()}}
    out = HERE / "results" / f"cal_{tag}.json"
    subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run_benchmark.py"), "--arch", arch, "--split", "dev", "--llm", "replay", "--out", str(out)],
                   env=env, check=True, capture_output=True)
    rows = metrics.load(out)
    s = metrics.summarize(rows)
    over = sum(1 for r in rows if r["got"] == "clarify" and r["expected"] != "clarify" and "clarify" not in r["acceptable"]) / len(rows)
    return s["lenient"] - 0.5 * over


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="E", choices=["B", "D", "E"])
    a = ap.parse_args()
    best = dict(START)
    best_score = run(a.arch, best, "start")
    log = [{"th": dict(best), "score": round(best_score, 4)}]
    names = ["sr_score", "sr_margin"] if a.arch == "B" else list(GRID)
    for name in names:
        values = GRID[name]
        for v in values:
            if v == best[name]:
                continue
            trial = {**best, name: v}
            sc = run(a.arch, trial, f"{name}_{v}")
            log.append({"th": trial, "score": round(sc, 4)})
            if sc > best_score + 1e-9:
                best, best_score = trial, sc
    (HERE / f"thresholds_{a.arch}.json").write_text(json.dumps(best, indent=1), encoding="utf-8")
    (HERE / "results" / f"calibration_{a.arch}.json").write_text(json.dumps({"best": best, "score": best_score, "log": log}, indent=1), encoding="utf-8")
    print("best", best, round(best_score, 4), "after", len(log), "runs")
