"""Component test of the evidence-aware verification stage (modules/qa/trust.py): can it tell a figure that comes from the fetched data
from an invented one? No model, no network, deterministic (seed 7).

Method: take evidence tables like the ones ARIA's pipelines produce (the figure asked about plus about 21 other figures of every kind, so a fabricated value can match one by accident), write answer sentences that
quote figures from them ("clean"), and the same sentences with ONE figure replaced by a fabricated value ("invented", changed by a factor
of 1.3 to 5 so it is not a rounding of the original). Report detection rate on invented and false-alarm rate on clean sentences, by figure type.
This measures NUMERIC fabrication only; it does not measure invented names, dates or qualitative claims.

usage: python -X utf8 evaluation/intent_understanding/answer_eval.py
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.qa import trust  # noqa: E402

random.seed(7)
TEMPLATES = [
    ("price", "{n} latest price is ₹{v:,.2f}.", lambda r: r.uniform(20, 9000)),
    ("revenue", "{n} revenue for the year was ₹{v:,.0f} Cr.", lambda r: r.uniform(500, 400000)),
    ("profit", "{n} net profit came to ₹{v:,.0f} Cr, up on the year.", lambda r: r.uniform(50, 80000)),
    ("pe", "{n} trades at a trailing P/E of {v:.1f}.", lambda r: r.uniform(5, 120)),
    ("nav", "The latest NAV of {n} is ₹{v:,.2f}.", lambda r: r.uniform(10, 900)),
    ("mcap", "{n} has a market capitalisation of ₹{v:,.0f} Cr.", lambda r: r.uniform(1000, 1500000)),
    ("yield", "{n} has a dividend yield of {v:.2f}%.", lambda r: r.uniform(0.1, 9)),
]
NAMES = ["Reliance", "Infosys", "Tata Elxsi", "Kaynes Technology", "Suzlon Energy", "Coal India", "HDFC Bank", "Dixon Technologies", "Parag Parikh Flexi Cap", "Ola Electric"]


def build(n_per_type=30):
    rows = []
    for kind, tpl, gen in TEMPLATES:
        for i in range(n_per_type):
            name = random.choice(NAMES)
            true = round(gen(random), 2)
            fake = round(true * random.choice([1.3, 1.5, 2, 3, 5, 0.4, 0.6]), 2)
            table = {f"{k2}_{j}": round(g2(random), 2) for k2, _, g2 in TEMPLATES for j in range(3)}  # ~21 other real-looking figures of every kind
            ev = json.dumps({"name": name, "kind": kind, "value": true, "as_of": "2026-10-26", "other_figures": table})
            rows.append((kind, tpl.format(n=name, v=true), tpl.format(n=name, v=fake), ev))
    return rows


def main():
    rows = build()
    stats = {}
    for kind, clean, bad, ev in rows:
        s = stats.setdefault(kind, dict(n=0, fp=0, tp=0))
        s["n"] += 1
        s["fp"] += bool(trust.ungrounded(clean, ev, lenient=True))  # clean sentence wrongly flagged
        s["tp"] += bool(trust.ungrounded(bad, ev, lenient=True))  # invented figure caught
    n = sum(s["n"] for s in stats.values())
    tp = sum(s["tp"] for s in stats.values())
    fp = sum(s["fp"] for s in stats.values())
    print("| Figure type | n pairs | Invented figure caught | Clean sentence wrongly flagged |")
    print("|---|---|---|---|")
    for k, s in stats.items():
        print(f"| {k} | {s['n']} | {s['tp']}/{s['n']} ({s['tp'] / s['n']:.0%}) | {s['fp']}/{s['n']} |")
    print(f"| **all** | {n} | **{tp}/{n} ({tp / n:.1%})** | **{fp}/{n}** |")
    # redaction behaviour on a multi-sentence answer
    ev = json.dumps({"name": "Infosys", "revenue_cr": 178650, "net_profit_cr": 26750})
    text = "Infosys revenue was ₹178,650 Cr. Net profit was ₹26,750 Cr. The company employs 3,40,000 people and expects ₹250,000 Cr next year."
    fixed, removed = trust._redact(text, ev, True)
    print("\nredaction demo ->", fixed.replace("\n", " | "), "| removed:", removed)


if __name__ == "__main__":
    main()
