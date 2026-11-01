"""Metrics over run_benchmark.py results. Every number is computed from the stored per-query rows; nothing is estimated.

strict   : first-choice label == expected_primary
lenient  : label == expected_primary or in acceptable (the benchmark records which alternatives a reasonable user would also accept)
wrong    : routed to a module that is neither expected nor acceptable AND did not ask for clarification (the harmful case)
over-clarify: asked a question although a route was expected and available
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = ["finance", "tutor", "market", "equity_research", "company_intelligence", "data_lookup", "general", "smalltalk", "clarify"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def is_strict(r) -> bool:
    return r["got"] == r["expected"]


def is_lenient(r) -> bool:
    return bool(r["got"] == r["expected"] or r["got"] in r["acceptable"] or (r["got_parts"] and r["expected"] in r["got_parts"]))


def is_wrong(r) -> bool:
    return not is_lenient(r) and r["got"] not in ("clarify", "EXC")


def prf(rows, labels=LABELS):
    """Macro precision / recall / F1 on strict first-choice labels (labels with no support are skipped)."""
    tp, fp, fn = Counter(), Counter(), Counter()
    for r in rows:
        e, g = r["expected"], r["got"]
        if e == g:
            tp[e] += 1
        else:
            fn[e] += 1
            fp[g] += 1
    ps, rs, fs = [], [], []
    for lab in labels:
        if tp[lab] + fn[lab] == 0:
            continue
        p = tp[lab] / (tp[lab] + fp[lab]) if tp[lab] + fp[lab] else 0.0
        r_ = tp[lab] / (tp[lab] + fn[lab])
        ps.append(p)
        rs.append(r_)
        fs.append(2 * p * r_ / (p + r_) if p + r_ else 0.0)
    n = max(1, len(fs))
    return sum(ps) / n, sum(rs) / n, sum(fs) / n


def clarification(rows):
    tp = sum(1 for r in rows if r["expected"] == "clarify" and r["got"] == "clarify")
    fp = sum(1 for r in rows if r["expected"] != "clarify" and r["got"] == "clarify" and "clarify" not in r["acceptable"])
    fn = sum(1 for r in rows if r["expected"] == "clarify" and r["got"] != "clarify")
    p = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return p, rec, fp


def multi_intent(rows):
    """Coverage = share of the expected modules actually run; precision = share of the modules run that were expected."""
    sel = [r for r in rows if r["category"] == "multi_intent"]
    if not sel:
        return None
    cov, prec = [], []
    for r in sel:
        exp = {r["expected"], *r["secondary"]}
        got = set(r["got_parts"]) if r["got_parts"] else {r["got"]}
        cov.append(len(exp & got) / len(exp))
        prec.append(len(exp & got) / max(1, len(got)))
    return sum(cov) / len(cov), sum(prec) / len(prec), len(sel)


def entities(rows):
    """Entity extraction (only variants that extract: D, E). Match is case-insensitive substring in either direction."""
    sel = [r for r in rows if r["category"] == "entity_heavy"]
    if not sel or not any((r["route"] or {}).get("entities") is not None for r in sel):
        return None
    tp = fp = fn = 0
    for r in sel:
        exp = [e.lower() for e in r["entities_expected"]]
        got = [str(x).lower() for x in ((r["route"] or {}).get("entities") or [])]
        hit = {e for e in exp if any(e in g or g in e for g in got)}
        tp += len(hit)
        fn += len(exp) - len(hit)
        fp += sum(1 for g in got if not any(e in g or g in e for e in exp))
    p = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    return p, r_, 2 * p * r_ / (p + r_) if p + r_ else 0.0


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else 0.0


def summarize(rows) -> dict:
    n = len(rows)
    k = sum(is_lenient(r) for r in rows)
    ks = sum(is_strict(r) for r in rows)
    lo, hi = wilson(k, n)
    mp, mr, mf = prf(rows)
    cp, cr, over = clarification(rows)
    lat = [r["latency_ms"] for r in rows]
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    out = {
        "n": n, "strict": ks / n, "lenient": k / n, "lenient_ci": [lo, hi], "wrong_route": sum(is_wrong(r) for r in rows) / n,
        "macro_p": mp, "macro_r": mr, "macro_f1": mf, "clarify_p": cp, "clarify_r": cr, "over_clarify": over,
        "followup_acc": (lambda s: sum(is_lenient(r) for r in s) / len(s) if s else None)([r for r in rows if r["category"] == "followup" and r["turn"] >= 2]),
        "multi": multi_intent(rows), "entity": entities(rows),
        "lat_mean": sum(lat) / n, "lat_p50": pct(lat, .5), "lat_p95": pct(lat, .95),
        "llm_calls_per_q": sum(r["llm_calls"] for r in rows) / n, "tokens_per_q": sum(r["llm_tokens"] for r in rows) / n,
        "llm_ms_per_q": sum(r["llm_ms"] for r in rows) / n, "llm_miss": sum(r["llm_miss"] for r in rows), "errors": sum(1 for r in rows if r["error"]),
        "by_category": {c: (len(v), sum(is_lenient(r) for r in v) / len(v)) for c, v in sorted(by_cat.items())},
    }
    return out


def mcnemar(rows_a, rows_b):
    """Exact two-sided McNemar test on paired lenient correctness (same items, same order). Returns (b_only_correct, a_only_correct, p)."""
    ia = {r["id"]: is_lenient(r) for r in rows_a}
    b = a = 0
    for r in rows_b:
        x, y = ia.get(r["id"]), is_lenient(r)
        if x is None:
            continue
        if y and not x:
            b += 1
        if x and not y:
            a += 1
    n = a + b
    if n == 0:
        return b, a, 1.0
    k = min(a, b)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n)
    return b, a, p


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        s = summarize(load(Path(path)))
        print(path, json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items() if k != "by_category"}, default=str))
