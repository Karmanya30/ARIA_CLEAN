"""Historical scenario backtest over the whole NSE + BSE universe.

    python -X utf8 scripts/scenario_backtest_universe.py [--limit N] [--exchange NSE|BSE|ALL] [--workers K]
                                                         [--resume|--no-resume] [--symbols-file F] [--timeout 300]
    python -X utf8 scripts/scenario_backtest_universe.py --status        # monitor a running/finished sweep
    python -X utf8 scripts/scenario_backtest_universe.py --report-only   # rebuild summary.parquet + UNIVERSE_SCENARIO_REPORT.md

Resumable: state in data/scenario_backtest/sweep_state.json; per-company files in data/scenario_backtest/results/.
screener.in is hit through scenario_backtest.data's limiter (2 concurrent across all workers, 2-4 s jitter, backoff,
30-day cache), so extra workers add compute, not request rate. BSE-only names with no screener page are recorded as
'no_screener_page'.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import re
import signal
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_universe as vu  # noqa: E402  (Sweep, state helpers, order/select)

STATE_NAME = "sweep_state.json"
RETRY = ("failed", "timeout", "retry", "no_price")  # re-run on every resume ('retry' = network trouble, 'no_price' = Yahoo had no bars)
OUTAGE_AFTER, PAUSE_S, PAUSE_MAX_S = 10, 600, 3600  # consecutive 'retry' results across workers -> pause 10 min, doubling to 1 h
OK_STATUSES = ("ok", "insufficient_history", "model_refused", "no_screener_page")
LIMITS = [
    "Survivorship: only today's listings are swept; delisted and merged companies are absent.",
    "Restated data: screener.in shows restated figures, not as first reported; no publication dates exist (90-day lag assumed).",
    "Short histories: 12 fiscal years at most, so horizons of 9-10 years can never be validated and k=5 has about 4 origins.",
    "Overlapping origins: consecutive origins share most of their outcome window, so effective n is far below the row count.",
    "Sources: statements come from screener.in, or from Yahoo annual statements (4-5 fiscal years, no ratios/quarterly/TTM, EPS split-adjusted from the price file) when screener.in is unreachable or has no page; prices only from Yahoo. Sector labels and FI_* settings are today's.",
    "Short histories (2-3 fiscal years at the origin) run on the minimum valuation.py needs (one year of growth, margins from the years that exist); they are reported in their own slice and never mixed into the headline cells.",
    "Year effects (COVID, rate cycles) dominate the few origin years; results are per line, horizon and case, never one accuracy figure.",
]


def state_file() -> Path:
    from modules.equity_research.scenario_backtest import data

    return data.CACHE_DIR / STATE_NAME


# -- worker (child process) ----------------------------------------------------------------------------------
def _sb_worker(conn, mode: str) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    import warnings

    from loguru import logger

    warnings.filterwarnings("ignore")
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    from modules.equity_research.scenario_backtest import jobs

    while True:
        try:
            sym = conn.recv()
        except EOFError:
            return
        if sym is None:
            return
        t0 = time.perf_counter()
        s = jobs.compute(sym)
        conn.send({"status": s["status"], "reason": s.get("reason"), "n_origins": s.get("n_origins"), "provider": s.get("provider"),
                   "seconds": round(time.perf_counter() - t0, 1)})


def already_done(sym: str, state: dict, mode: str) -> bool:
    """Resume rule: skip anything with a current result file; failed and timed-out symbols are retried."""
    from modules.equity_research.scenario_backtest import jobs

    rec = state["symbols"].get(sym)
    return bool(rec) and rec["status"] not in RETRY and jobs.is_current(sym)


class OutageSweep(vu.Sweep):
    """Sweep that notices a sustained outage: OUTAGE_AFTER consecutive 'retry' results (network errors on both
    screener.in and the fallback) pause the whole sweep with a doubling backoff instead of burning through the list.
    The affected symbols stay 'retry' in the state file and are re-run on resume."""

    def __init__(self, *a, sleep=time.sleep, **kw):
        super().__init__(*a, **kw)
        self.streak, self.pause_s, self.sleep, self.pauses = 0, PAUSE_S, sleep, 0

    def _record(self, e, res, counts, secs):
        super()._record(e, res, counts, secs)
        if res["status"] == "retry":
            self.streak += 1
        elif res["status"] in OK_STATUSES:
            self.streak, self.pause_s = 0, PAUSE_S
        if self.streak >= OUTAGE_AFTER:
            self.outage_pause()

    def outage_pause(self) -> None:
        from modules.equity_research.scenario_backtest import data

        print(f"[{vu._now()}] {self.streak} consecutive network failures: pausing {self.pause_s // 60} min", flush=True)
        self.state["meta"]["pause_reason"] = f"sustained network outage; paused {self.pause_s}s at {vu._now()}"
        vu.save_state(self.state)
        waited = 0
        while waited < self.pause_s and not self.stop:
            self.sleep(5)
            waited += 5
        self.pauses += 1
        self.pause_s, self.streak = min(self.pause_s * 2, PAUSE_MAX_S), 0
        data.reset_breaker()  # let the next symbol probe screener.in again
        now = time.time()
        for w in self.slots:  # the per-symbol timeout must not count the pause
            if w and w["sym"]:
                w["t"] = now


# -- outputs --------------------------------------------------------------------------------------------------
def build_summary(entries: list, state: dict):
    import pandas as pd

    from modules.equity_research.scenario_backtest import jobs

    rows = []
    for e in entries:
        s = jobs._read_summary(e.yahoo_symbol) or {}
        rec = state["symbols"].get(e.yahoo_symbol)
        if not rec and s.get("status"):  # a targeted re-run's state file covers only its own symbols: fall back to the result file
            rec = {"status": s["status"], "reason": s.get("reason")}
        if not rec:
            continue
        row = {"symbol": e.symbol, "yahoo_symbol": e.yahoo_symbol, "exchange": e.exchange, "name": e.name,
               "status": rec["status"], "reason": rec.get("reason"), "provider": s.get("provider") or rec.get("provider"),
               "n_fiscal_years": s.get("n_fiscal_years"), "n_origins_short": s.get("n_origins_short"),
               "why": None if rec["status"] == "ok" else _why(rec, s, e.yahoo_symbol), "n_origins": s.get("n_origins"), "seconds": rec.get("seconds")}
        for k, v in (s.get("metrics") or {}).items():  # flat scalars of company_summary only
            if isinstance(v, (int, float, str, bool)) or v is None:
                row[f"m_{k}"] = v
        from modules.equity_research.scenario_backtest import metrics as _m
        row["m_medabs_e"] = _m.medabs_primary(s.get("metrics"))  # the company report ranks itself on this
        rows.append(row)
    return pd.DataFrame(rows)


SUPP = "n<30"
BENIGN = ("non_fy_column", "structural_break", "share_basis", "restated", "gap", "fy_change", "yfinance_fallback",
          "eps_not_split_adjusted", "sector_unknown")  # data notes / flags: never the reason a company was excluded
HOW_TO_READ = [
    "For each past fiscal year-end (an *origin*) ARIA's bear/base/bull cases were rebuilt using only data available then, then compared with what the company later reported, k years ahead.",
    "**Bias** is the median error of the base case. For revenue, EBITDA, EPS and DPS it is ln(forecast/actual): +0.100 means the base case was about 10% too high, -0.100 about 10% too low. For margin it is in percentage points (forecast minus actual). Growth bias is forecast growth minus realised growth, in percentage points a year. The bracket is a 90% confidence interval (resampling whole companies); if it contains 0 the bias is not distinguishable from noise.",
    "**Median abs err** is the typical size of the miss, ignoring direction. **sMAPE** is the same idea as a symmetric percentage.",
    "**Band** (scenario coverage) shows how often the reported figure fell below, inside or above the bear-to-bull range. The 68% reference is only a yardstick, not a calibration target: the bear and bull cases carry no stated probability and their spread equals ARIA's own Monte Carlo sigma (roughly +-1 sigma).",
    "**Nearest case** shows which of bear, base or bull ended up closest to the reported figure. If the cases were well calibrated the shares would be roughly 25% / 50% / 25%.",
    "**Skill** is 1 - (median miss of ARIA's base case / median miss of a naive baseline). Above 0 means ARIA beat the baseline, 0 equals it, below 0 means the naive guess did better. Baselines: rw = last reported value carried forward, cagr = trailing growth continued, mr = margin reverts to its average.",
    "**n<30** means fewer than 30 companies had a result in that cell, so it is hidden rather than shown as if reliable.",
    "**Price vs value** compares ARIA's fair value with the later share price. Price convergence is not proof of forecast accuracy.",
]
SLICE_HEAD = ["slice", "n_companies", "growth bias, pp/yr [90% CI]", "margin bias, pp [90% CI]", "band inside [90% CI]"]


def _pct(x, d=1):
    return "-" if x is None else f"{x:.{d}%}"


def _num(x, d=3, sign=False):
    return "-" if x is None else f"{x:{'+' if sign else ''}.{d}f}"


def _ci(c, d=3):
    return "-" if not c else f"{c['est']:+.{d}f} [{c['lo']:+.{d}f}, {c['hi']:+.{d}f}]"


def _tbl(head: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows] + [""]


def _line_rows(cells: dict, margin: bool) -> list[list]:
    d = 2 if margin else 3
    names = ("naive_mr", "naive_rw") if margin else ("naive_rw", "naive_cagr")
    rows = []
    for k in sorted(cells):
        c = cells[k]
        if c.get("suppressed"):
            rows.append([k, c.get("n_companies", "?")] + [SUPP] * 6)
            continue
        b, bd, nr, sk = c.get("base") or {}, c.get("band"), c.get("nearest"), c.get("skill") or {}
        rows.append([k, c["n_companies"], _ci(b.get("bias_ci90"), d) if b.get("bias_ci90") else _num(b.get("bias"), d, True),
                     _num(b.get("median_abs_e"), d), "-" if b.get("smape_pct") is None else f"{b['smape_pct']:.1f}%",
                     "-" if not bd else f"{bd['below']:.0%} / {bd['inside']:.0%} / {bd['above']:.0%}",
                     "-" if not nr else f"{nr['bear']:.0%} / {nr['base']:.0%} / {nr['bull']:.0%}",
                     " ; ".join(f"{n[6:]} {_num((sk.get(n) or {}).get('skill'), 2, True)}" for n in names)])
    return rows


def _slice_rows(d: dict) -> list[list]:
    rows = []
    for name, s in d.items():
        if s.get("suppressed"):
            rows.append([name, s.get("n_companies", "?")] + [SUPP] * 3)
            continue
        g, m, b = s.get("growth_bias_pp"), s.get("margin_bias_pp"), s.get("band")
        rows.append([name, s["n_companies"], _ci(g["ci"], 2) if g else "-", _ci(m["ci"], 2) if m else "-",
                     "-" if not b else f"{b['inside']:.0%}" + (f" [{b['ci']['lo']:.0%}, {b['ci']['hi']:.0%}]" if b.get("ci") else "")])
    return rows


def _oy_cell(c, margin: bool) -> str:
    if c is None:
        return "-"
    return SUPP if c.get("suppressed") else f"{c['bias']:+.{2 if margin else 3}f} / {c['median_abs_e']:.{2 if margin else 3}f} (n={c['n_companies']})"


def _results(agg: dict) -> list[str]:
    out = [f"{agg['n_companies_scored']} companies scored ({agg['n_origins']} origins). Intervals: {agg['ci']}. Cells with fewer than "
           f"{agg['min_companies_per_cell']} companies show `{SUPP}`.", "", "Rows left out of the headline cells: " + ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in agg["excluded"].items()) + ".", "",
           "### Accuracy by line and horizon", "",
           "Level lines use log error (3 decimals); margin uses percentage points. Band and nearest-case columns read below / inside / above and bear / base / bull. "
           f"Band reference: {agg['band_reference']}. Expected nearest-case split: 25% / 50% / 25%.", ""]
    head = ["k (years)", "n_companies", "base bias [90% CI]", "median abs err", "sMAPE", "band below/inside/above", "nearest bear/base/bull", "skill vs naive"]
    for line, v in (agg.get("lines") or {}).items():
        out += [f"#### {line}" + (" (indicative only)" if v.get("indicative") else ""), ""] + _tbl(head, _line_rows(v["k"], line == "margin"))
    if not agg.get("lines"):
        out += ["No scored lines yet.", ""]
    g = (agg.get("growth") or {}).get("k") or {}
    if g:
        out += ["### Growth bias by horizon", "", (agg["growth"].get("note") or "").capitalize() + ".", ""]
        out += _tbl(["k (years)", "n", "bias pp/yr [90% CI]", "share at growth cap", "bias when capped", "bias when not capped"],
                    [[k, c["n"], _ci(c["bias_ci90"], 2) if c.get("bias_ci90") else _num(c["bias_pp"], 2, True), _pct(c["growth_cap_share"]),
                      _num(c["bias_pp_when_capped"], 2, True), _num(c["bias_pp_when_not_capped"], 2, True)] for k, c in sorted(g.items())])
    out += ["## Growth and margin bias by segment", "", "Pooled over horizons 1-5, headline lines only. Positive growth bias means ARIA was too optimistic.", ""]
    if agg.get("overall"):
        out += ["### Overall", ""] + _tbl(SLICE_HEAD, _slice_rows({"all companies": agg["overall"]}))
    for key, title in (("by_sector", "By sector"), ("by_size", "By size bucket"), ("by_g1", "By first-year growth (g1)")):
        if agg.get(key):
            out += [f"### {title}", ""] + _tbl(SLICE_HEAD, _slice_rows(agg[key]))
    oy = agg.get("by_origin_year") or {}
    if oy:
        cols = sorted({c for y in oy.values() for c in y})
        out += ["### By origin year", "", "Each cell: median bias / median abs error (n companies). Log for level lines, pp for margin; k = 1 and 3 years only.", ""]
        out += _tbl(["origin FY"] + [c.replace("_k", " k=") for c in cols],
                    [[fy] + [_oy_cell(oy[fy].get(c), c.startswith("margin")) for c in cols] for fy in sorted(oy, key=lambda x: (str(x).split()[-1], str(x)))])
    if agg.get("by_provider"):
        out += ["### By data provider", ""] + _tbl(SLICE_HEAD, _slice_rows(agg["by_provider"]))
    sh = agg.get("short_history") or {}
    out += ["## Short-history slice", "",
            "Origins with only 2-3 fiscal years of statements at the origin (new companies). The model runs on the least it needs: year-1 growth is the latest-year growth rather than a 3y/5y CAGR, margins are medians of the years that exist. Kept apart from every headline cell above.", ""]
    if sh.get("n_origins"):
        out += [f"{sh['n_origins']} short-history origins from {sh.get('n_companies_origins', 0)} companies; {sh.get('n_companies', 0)} companies have scored rows.", ""]
        if sh.get("overall"):
            out += _tbl(SLICE_HEAD, _slice_rows({"short history": sh["overall"]}))
        head = ["k (years)", "n_companies", "base bias [90% CI]", "median abs err", "sMAPE", "band below/inside/above", "nearest bear/base/bull", "skill vs naive"]
        for line, v in (sh.get("lines") or {}).items():
            out += [f"#### {line} (short history)" + (" (indicative only)" if v.get("indicative") else ""), ""] + _tbl(head, _line_rows(v["k"], line == "margin"))
    else:
        out += ["No short-history origin yet.", ""]
    p = agg.get("price") or {}
    out += ["## Price vs value", "", f"**{p.get('caption', agg['caption'])}**", ""]
    if p.get("k"):
        ir = p.get("implied_return_median") or {}
        out += [f"- {p['n_origins']} origins with a fair value and a price. Median valuation gap ln(V_base/P0): {_num(p.get('valuation_gap_median'), 3, True)} "
                f"(median absolute {_num(p.get('valuation_gap_median_abs'))}).",
                "- Median implied return V/P0 - 1 if price fully converged: " + ", ".join(f"{n} {_pct(x)}" for n, x in ir.items()) + f". ({p.get('implied_return_note', '')})", ""]
        rows = []
        for k, c in sorted(p["k"].items()):
            rc = c.get("rank_corr_gap_vs_return")
            rows.append([k, c["n"], _pct(c["price_in_bear_bull"]), _pct(c["converged_toward_base"]), _pct(c["median_total_return"]),
                         SUPP if not rc else f"{rc['mean']:+.3f} over {rc['years']} yrs" + (f", t={rc['t_stat']:.2f}" if rc.get("t_stat") is not None else "")])
        out += _tbl(["k (years)", "n", "price inside bear-bull", "moved toward base value", "median total return", "rank corr (gap vs return)"], rows)
    else:
        out += ["No origin has both a fair value and a later price yet.", ""]
    return out


def _recs(agg: dict) -> list[str]:
    from modules.equity_research.scenario_backtest import metrics

    recs: list[str] = []
    for sec in [None, *(agg.get("by_sector") or {})]:
        recs += [r for r in metrics.recommendations(agg, sec) if r not in recs]
    return recs


def _norm(r: str) -> str:
    """Group reasons that differ only by dates / year spans."""
    return re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", re.sub(r" \([A-Z][a-z]{2} \d{4}\.\.[A-Z][a-z]{2} \d{4}\)", "", r))


def _why(rec: dict, s: dict, sym: str) -> str:
    """Real reason a company was excluded: sweep reason, else refused reasons, else origin refusals, else non-benign data issues."""
    import pandas as pd

    from modules.equity_research.scenario_backtest import jobs

    if rec.get("reason") or s.get("reason"):
        return str(rec.get("reason") or s.get("reason"))[:140]
    parts = list((s.get("metrics") or {}).get("refused_reasons") or s.get("refused_reasons") or [])
    if not parts:
        try:
            o = pd.read_parquet(jobs._p(sym, "origins.parquet"), columns=["refused_reason"])
            parts = sorted(set(o.refused_reason.dropna()) - {""})
        except Exception:
            pass
    if not parts:
        parts = sorted({i.get("reason", "") for i in s.get("issues") or []} - set(BENIGN) - {""})
    return " | ".join(parts)[:140] or "(no reason recorded)"


def write_report(df, path: Path, n_universe: int, note: str = "") -> str:
    import pandas as pd

    from modules.equity_research.scenario_backtest import jobs

    out = ["# Universe scenario backtest", "", note, "",
           "ARIA's bear/base/bull cases rebuilt at past fiscal year-ends from point-in-time data and compared with what was later reported.",
           "Not a price predictor; 9-10 year horizons cannot be validated with 12 years of statements.", "",
           "## How to read this", ""] + [f"- {x}" for x in HOW_TO_READ] + ["",
           "## Coverage", "", f"{len(df)} of {n_universe} companies attempted.", ""]
    if len(df):
        cov = df["status"].value_counts()
        out += _tbl(["status", "companies", "share"], [[k, int(v), f"{v / len(df):.1%}"] for k, v in cov.items()])
        bad = df[df["status"] != "ok"]
        if len(bad):
            col = bad["why"] if "why" in bad else bad["reason"]
            cnt = Counter((st, _norm(r.strip()) or "(no reason recorded)") for st, w in zip(bad["status"], col.fillna("")) for r in str(w).split(" | "))
            out += ["### Exclusions by reason", "", "A company with several reasons is counted under each.", ""]
            out += _tbl(["status", "reason", "companies"], [[a, b, n] for (a, b), n in cnt.most_common(20)])
            ins = bad[bad["status"] == "insufficient_history"]
            if "n_fiscal_years" in ins and ins["n_fiscal_years"].notna().any():
                yrs = ins["n_fiscal_years"].dropna().astype(int).value_counts().sort_index()
                out += ["### Insufficient history by fiscal years available", "",
                        "Full origins need 4 fiscal years; short-history origins need 2 plus 1 later year to score, so fewer than 3 years cannot be scored at all.", ""]
                out += _tbl(["fiscal years available", "companies"], [[int(k), int(v)] for k, v in yrs.items()])
        if "provider" in df and df["provider"].notna().any():
            prov = df.assign(provider=df["provider"].fillna("(none: no statements obtained)")).pivot_table(index="provider", columns="status", values="symbol", aggfunc="count", fill_value=0)
            out += ["### Coverage by data provider", "", "Provider of the statements each company was scored from: screener.in, or the yfinance fallback (4-5 fiscal years, no ratios or quarterly data).", ""]
            out += _tbl(["provider"] + list(prov.columns) + ["total"], [[i] + [int(x) for x in r] + [int(r.sum())] for i, r in prov.iterrows()])
        if "n_origins_short" in df and df["n_origins_short"].fillna(0).gt(0).any():
            sh = df[df["n_origins_short"].fillna(0) > 0]
            out += [f"{len(sh)} companies have short-history origins ({int(sh['n_origins_short'].sum())} origins); their results are in the separate short-history section below.", ""]
    fs, os_ = [], []
    for sym in df.loc[df["status"] == "ok", "yahoo_symbol"] if len(df) else []:
        try:
            fs.append(pd.read_parquet(jobs._p(sym, "forecasts.parquet")))
            os_.append(pd.read_parquet(jobs._p(sym, "origins.parquet")))
        except Exception:
            continue
    out += ["## Results", ""]
    if fs:
        try:
            from modules.equity_research.scenario_backtest import metrics

            agg = metrics.aggregate(pd.concat(fs, ignore_index=True), pd.concat(os_, ignore_index=True))
            out += _results(agg)
            recs = _recs(agg)
            out += ["## Where the assumptions systematically err", ""] + ([f"- {r}" for r in recs] if recs else
                    [f"No finding met the bar: at least {agg['min_companies_per_cell']} companies and a 90% interval that excludes zero."]) + [""]
        except Exception as e:
            out += [f"Aggregation unavailable ({type(e).__name__}: {e}); the per-company results are in `results/`.", ""]
    else:
        out += ["No company has a scored result yet.", ""]
    out += ["## Limits", ""] + [f"- {x}" for x in LIMITS] + [""]
    text = "\n".join(out)
    path.write_text(text, encoding="utf-8")
    return text


def write_outputs(entries: list, n_universe: int, state: dict):
    from modules.equity_research.scenario_backtest import data

    df = build_summary(entries, state)
    data.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(data.CACHE_DIR / "summary.parquet", index=False)
    note = f"Generated {vu._now()} UTC. Rows cover the {len(df)} symbols attempted so far."
    write_report(df, data.CACHE_DIR / "UNIVERSE_SCENARIO_REPORT.md", n_universe, note)
    return df


def status() -> int:
    s = vu.load_state()
    m, syms = s.get("meta", {}), s.get("symbols", {})
    if not syms:
        print("no sweep state yet")
        return 1
    c = Counter(v["status"] for v in syms.values())
    total, todo, run_done = m.get("total", len(syms)), m.get("run_todo", 0), m.get("run_done", 0)
    el = m.get("run_elapsed_s") or 0
    eta = vu.fmt_eta(el / run_done * (todo - run_done)) if run_done and m.get("running") else "-"
    print(f"sweep pid={m.get('pid')} running={m.get('running')} updated={m.get('updated')}")
    print(f"done {len(syms)}/{total}  (this run {run_done}/{todo}, elapsed {vu.fmt_eta(el)}, ETA {eta})")
    print("by status: " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--exchange", choices=["NSE", "BSE", "ALL"], default="ALL")
    ap.add_argument("--workers", type=int, default=min(6, (os.cpu_count() or 2) // 2))
    ap.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--priority", default="nifty500-first", choices=["nifty500-first", "none"])
    ap.add_argument("--symbols-file")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    vu.state_path = state_file  # Sweep.flush and load/save_state use the module-level state_path
    vu.already_done = already_done
    if a.status:
        return status()
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "2")
    from modules.equity_research.forecast import universe
    from modules.equity_research.scenario_backtest import data

    full = universe.discover_universe(refresh=a.refresh_universe)
    print(f"universe: {len(full)} companies", flush=True)
    syms = [s.strip() for s in Path(a.symbols_file).read_text().split() if s.strip()] if a.symbols_file else None
    entries = vu.select(vu.order(full, a.priority), a.exchange, a.limit, syms)
    if not a.report_only:
        state = vu.load_state() if a.resume else {"meta": {}, "symbols": {}}
        todo = [e for e in entries if not (a.resume and already_done(e.yahoo_symbol, state, "sb"))]
        print(f"sweep: {len(entries)} symbols, {len(entries) - len(todo)} already complete, {len(todo)} to run, "
              f"{min(a.workers, max(len(todo), 1))} workers", flush=True)
        state["meta"]["universe_selected"] = [e.yahoo_symbol for e in entries]
        if todo:
            OutageSweep(todo, "sb", a.workers, a.timeout, state, len(entries) - len(todo), worker=_sb_worker).run()
        else:
            vu.save_state(state)
    state = vu.load_state()
    from modules.equity_research.scenario_backtest import jobs
    # a targeted re-run's state file covers only its own symbols: everything with a result file belongs in the summary too
    sel = [e for e in full if e.yahoo_symbol in state["symbols"] or jobs._read_summary(e.yahoo_symbol)] or entries
    df = write_outputs(sel, len(full), state)
    print(f"summary: {len(df)} rows -> {data.CACHE_DIR / 'summary.parquet'}; report -> {data.CACHE_DIR / 'UNIVERSE_SCENARIO_REPORT.md'}")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
