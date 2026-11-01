"""Builds the result tables (markdown) from results/*.json. Nothing is typed by hand: every number comes from the stored per-query rows.

usage: python -X utf8 evaluation/intent_understanding/report.py [--split test] > tables_test.md
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics as m  # noqa: E402

R = HERE / "results"
NAMES = {"A": "A baseline", "B": "B +Semantic Router", "C": "C +LangGraph", "D": "D structured+SR+LG", "E": "E hybrid",
         "B_override": "B-ablation: router may override rules", "E_nollm": "E-ablation: no LLM", "E_nograph": "E-ablation: no graph",
         "E_norouter": "E-ablation: no router"}


def f(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--vars", default="A,B,C,D,E")
    ap.add_argument("--common-only", action="store_true", help="only items where every model-based variant has its recorded model output (no cache miss)")
    a = ap.parse_args()
    keys = [k for k in a.vars.split(",") if (R / f"{k}_{a.split}.json").exists()]
    rows = {k: m.load(R / f"{k}_{a.split}.json") for k in keys}
    if a.common_only:
        ok = None
        for k, r in rows.items():
            good = {x["id"] for x in r if x["llm_miss"] == 0}
            ok = good if ok is None else ok & good
        rows = {k: [x for x in r if x["id"] in ok] for k, r in rows.items()}
        print(f"_Restricted to the {len(ok)} items for which every variant has its recorded model output (preliminary: the remaining test items are waiting for the provider's daily token budget)._\n")
    summ = {k: m.summarize(r) for k, r in rows.items()}
    n = summ[keys[0]]["n"]
    print(f"### Routing and understanding ({a.split} split, n={n})\n")
    print("| Variant | Lenient acc. [95% CI] | Strict acc. | Wrong-route rate | Macro F1 | Clarify P / R | Needless clarifications | Follow-up acc. | Multi-intent coverage / precision | Entity P / R / F1 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k in keys:
        s = summ[k]
        mi = s["multi"]
        en = s["entity"]
        print(f"| {NAMES.get(k, k)} | {s['lenient']:.1%} [{s['lenient_ci'][0]:.1%}, {s['lenient_ci'][1]:.1%}] | {s['strict']:.1%} | {s['wrong_route']:.1%} | {s['macro_f1']:.3f} | "
              f"{s['clarify_p']:.2f} / {s['clarify_r']:.2f} | {s['over_clarify']} | {f(s['followup_acc'])} | "
              f"{f(mi[0]) + ' / ' + f(mi[1]) if mi else 'n/a'} | {'%.2f / %.2f / %.2f' % en if en else 'n/a (no extractor)'} |")
    print(f"\n### Cost and latency ({a.split} split)\n")
    print("| Variant | Local routing p50 / p95 (ms) | Model calls per query | Tokens per query | Model time per query (ms, recorded) | Tokens per 1,000 queries | Errors / cache misses |")
    print("|---|---|---|---|---|---|---|")
    for k in keys:
        s = summ[k]
        print(f"| {NAMES.get(k, k)} | {s['lat_p50']:.0f} / {s['lat_p95']:.0f} | {s['llm_calls_per_q']:.2f} | {s['tokens_per_q']:.0f} | {s['llm_ms_per_q']:.0f} | {s['tokens_per_q'] * 1000:,.0f} | {s['errors']} / {s['llm_miss']} |")
    print("\nLocal routing time is the measured wall time of the routing step with all pipelines stubbed (model-load excluded); model time is the latency recorded when the real call was made, so end-to-end routing time = local + model time. Tokens are prompt + completion as reported by the provider.\n")
    print(f"### Lenient accuracy by category ({a.split} split)\n")
    cats = sorted({c for s in summ.values() for c in s["by_category"]})
    print("| Category (n) | " + " | ".join(NAMES.get(k, k).split(" ")[0] for k in keys) + " |")
    print("|---|" + "---|" * len(keys))
    for c in cats:
        cnt = max(summ[k]["by_category"].get(c, (0, 0))[0] for k in keys)
        print(f"| {c} ({cnt}) | " + " | ".join(f"{summ[k]['by_category'][c][1]:.0%}" if c in summ[k]["by_category"] else "-" for k in keys) + " |")
    if "A" in rows:
        print(f"\n### Paired comparison with baseline A ({a.split} split, exact McNemar on lenient correctness)\n")
        print("| Variant | Fixed vs A | Broken vs A | p-value |")
        print("|---|---|---|---|")
        for k in keys:
            if k == "A":
                continue
            b, a_only, p = m.mcnemar(rows["A"], rows[k])
            print(f"| {NAMES.get(k, k)} | {b} | {a_only} | {p:.3f} |")
        print("\n### Items where a variant changed A's outcome\n")
        base = {r["id"]: r for r in rows["A"]}
        for k in keys:
            if k == "A":
                continue
            lines = []
            for r in rows[k]:
                x = base[r["id"]]
                if m.is_lenient(r) != m.is_lenient(x):
                    lines.append(f"- {'FIXED' if m.is_lenient(r) else 'BROKE'} `{r['query'][:70]}` expected {r['expected']}, A={x['got']}, {k}={r['got']}")
            print(f"**{NAMES.get(k, k)}** ({len(lines)}):")
            print("\n".join(lines) if lines else "- none")
            print()


if __name__ == "__main__":
    main()
