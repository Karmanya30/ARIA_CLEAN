"""Experiment 2: validate ARIA's report (target price, BUY/HOLD/SELL) against realised returns. Offline, read-only on results/.

    python -X utf8 scripts/scenario_report_validation.py --pilot 40      # stratified IT/banks/FMCG/pharma/industrials
    python -X utf8 scripts/scenario_report_validation.py --all [--limit N] [--workers 4]
    python -X utf8 scripts/scenario_report_validation.py --brokers broker.csv   # side by side with ARIA (needs a previous run)
    python -X utf8 scripts/scenario_report_validation.py --robustness   # CIs, paired baselines, costs, split, calibrated interval (offline)
Writes only under data/scenario_backtest/report_validation/ (a pilot writes to pilot/ so --all is never overwritten).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from modules.equity_research.scenario_backtest import report_validation as rv  # noqa: E402


def _stats(d: pd.DataFrame) -> dict:
    return {"n": len(d), "hit": float(d.hit.astype(float).mean()), "excess": float(d.excess_return.mean()),
            "tp": float(d.tp_err_abs.median()) if d.tp_err_abs.notna().any() else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, metavar="N")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--brokers", metavar="CSV")
    ap.add_argument("--robustness", action="store_true", help="statistical-robustness analysis of the saved rows.parquet (offline; writes ROBUSTNESS.md + robustness.json)")
    ap.add_argument("--rebuild-cache", action="store_true", help="with --robustness: recompute the beta/liquidity and scenario-case caches")
    a = ap.parse_args()
    if a.robustness:
        from modules.equity_research.scenario_backtest import robustness as rb
        rows = pd.read_parquet(rv.OUT / "rows.parquet")
        extras = rb.build_extras(rows, a.rebuild_cache, a.workers)
        cases = rb.build_cases(a.rebuild_cache, a.workers)
        res = rb.run_all(rows, extras, cases)
        (rv.OUT / "robustness.json").write_text(json.dumps(res, indent=1, default=lambda o: None if o != o else str(o)), encoding="utf-8")
        rb.write_markdown(res, rv.OUT / "ROBUSTNESS.md")
        print(f"robustness: {res['n_rows']} rows, {res['n_companies']} companies -> {rv.OUT / 'ROBUSTNESS.md'}")
        return
    if a.brokers:
        nifty = rv.load_nifty()
        b, notes = rv.broker_rows(a.brokers, nifty)
        if b.empty:
            sys.exit("no broker rows could be scored:\n" + "\n".join(notes[:10]))
        base = next((p for p in (rv.OUT / "rows.parquet", rv.OUT / "pilot" / "rows.parquet") if p.exists()), None)
        aria = pd.read_parquet(base) if base is not None else pd.DataFrame()
        syms = set(b.symbol)
        res = {}
        for h, g in b.groupby("horizon_m"):
            res[int(h)] = {f"broker:{k}": _stats(x) for k, x in g.groupby("model")}
            res[int(h)]["broker:ALL"] = _stats(g)
            if len(aria):
                ag = aria[(aria.horizon_m == h) & aria.symbol.isin(syms)]
                if len(ag):
                    res[int(h)]["ARIA (same symbols)"] = _stats(ag)
        rv.OUT.mkdir(parents=True, exist_ok=True)
        out = rv.OUT / "brokers_comparison.json"
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")
        for h, d in res.items():
            for k, c in d.items():
                print(f"{h}m {k}: n={c['n']} hit={c['hit']:.1%} mean excess={c['excess']:.1%} median|TP err|={c['tp']}")
        print(f"unscored: {len(notes)}; wrote {out}; ARIA rows from {base}")
        return
    syms = rv.all_symbols() if a.all else rv.pilot_symbols()
    if a.pilot:
        per = max(1, a.pilot // len(rv.PILOT_GROUPS))
        syms = [s for names in rv.PILOT_GROUPS.values() for s in [f"{b}.NS" for b in names] if s in set(syms)]
        syms = [s for g in rv.PILOT_GROUPS.values() for s in [x for x in (f"{b}.NS" for b in g) if x in syms][:per]]
    elif not a.all and not a.limit:
        sys.exit("choose --pilot N, --all or --limit N")
    if a.limit:
        syms = syms[: a.limit]
    out_dir = rv.OUT if a.all and not a.limit else rv.OUT / "pilot"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, notes = rv.run(syms, a.workers)
    rows.to_parquet(out_dir / "rows.parquet")
    s = rv.summarize(rows)
    s["symbols_requested"] = len(syms)
    s["failures"] = len(notes)
    (out_dir / "summary.json").write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    label = "ALL companies" if out_dir == rv.OUT else f"pilot ({len(syms)} symbols)"
    rv.write_markdown(s, notes, label, out_dir / "REPORT_VALIDATION.md")
    print(f"{label}: rows={len(rows)} companies={s['n_companies']} failures={len(notes)} -> {out_dir}")
    print("recommendations:", {k: round(v, 3) for k, v in s["rec_distribution"].items()}, "withheld", round(s["withheld_share"], 3))


if __name__ == "__main__":
    main()
