"""Experiment 2: validate the equity-research REPORT (target price, BUY/HOLD/SELL) point-in-time against what happened.

ARIA's own rule, reused unchanged (intelligence/comps.py):
  value_company(snapshot) -> synthesize(methods, price) -> Synthesis(central, upside, tier, rating)
  upside = central/price - 1 (from the nearest edge of the [low, high] range when the point estimate is withheld)
  verdict: BUY if upside >= buy_band, SELL if upside <= -sell_band, else HOLD, bands by confidence tier:
  VERDICT_BANDS = high (0.20, 0.25) | medium (0.30, 0.35) | low (0.40, 0.55) | very_low (0.50, 0.75).
The backtest snapshot has no peers, so only the intrinsic method(s) exist (DCF; DDM + justified P/B for banks) and no
analyst-target ``street`` figure. Target price = Synthesis.central (None -> "withheld": rating still exists, no TP).

Point in time: the signal is computed from engine.as_of_snapshot (statements <= FYE, quarterly <= A-45d, price at
A = FYE+90d, beta from prices <= A). Outcomes are read from prices AFTER A only in compute_outcomes(), never fed back.
Horizons: A + 91 / 182 / 365 calendar days, last trading day on or before (engine._asof rule).

Fixed BEFORE looking at any result (no tuning on outcomes):
  hit: BUY -> excess return > 0; SELL -> excess return < 0; HOLD -> |excess| <= band (3m 5pp, 6m 7.5pp, 12m 10pp).
  excess = stock total return (adj close) - Nifty 50 (^NSEI price index, no dividends) over the same window.
HOLD hits are NOT comparable with BUY/SELL hits (different event); compare each with the same-rule random baseline.
"""
from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from modules.equity_research.forecast import data as fdata
from modules.equity_research.intelligence import valuation as V
from modules.equity_research.intelligence.analysis import analyze
from modules.equity_research.intelligence.comps import VERDICT_BANDS
from modules.equity_research.intelligence.facts import Ledger

from . import data
from .engine import NoOrigin, _asof, _first_on_or_after, as_of_snapshot, avail_date, fye
from .metrics import MIN_COMPANIES, _boot

ROOT = Path(__file__).resolve().parents[3] / "data" / "scenario_backtest"
RESULTS, OUT = ROOT / "results", ROOT / "report_validation"
HORIZON_DAYS = {3: 91, 6: 182, 12: 365}
HOLD_BAND = {3: 0.05, 6: 0.075, 12: 0.10}
SEED = 20260101
RECS = ("BUY", "HOLD", "SELL")

PILOT_GROUPS = {
    "IT": "TCS INFY WIPRO HCLTECH TECHM MPHASIS COFORGE PERSISTENT LTTS OFSS KPITTECH CYIENT".split(),
    "Banks": "HDFCBANK ICICIBANK SBIN AXISBANK KOTAKBANK INDUSINDBK FEDERALBNK BANKBARODA PNB IDFCFIRSTB CANBK UNIONBANK".split(),
    "FMCG": "HINDUNILVR ITC NESTLEIND BRITANNIA DABUR MARICO COLPAL GODREJCP TATACONSUM EMAMILTD".split(),
    "Pharma": "SUNPHARMA DRREDDY CIPLA LUPIN AUROPHARMA TORNTPHARM DIVISLAB ZYDUSLIFE ALKEM GLENMARK IPCALAB".split(),
    "Industrials": "LT SIEMENS ABB BHEL CUMMINSIND THERMAX BEL HAL GRINDWELL AIAENG KEC KALPATPOWR".split(),
}


# ── signal (point in time) ────────────────────────────────────────────────
def signal(symbol: str, tables: dict, meta: dict, px: pd.DataFrame, nifty: pd.Series, fy_col: str) -> dict:
    """ARIA's report call as of FYE+90d. Raises NoOrigin when no price exists then."""
    meta = {**meta, "symbol": symbol}
    snap = as_of_snapshot(tables, meta, px, nifty, fy_col)
    A = avail_date(fy_col)
    an = analyze(snap, Ledger())
    val = V.value_company(snap, an, Ledger())
    s = val.synthesis
    out = dict(symbol=symbol, origin_fy=fy_col, avail_date=A.isoformat(), model="ddm" if snap.is_financial else "dcf",
               p0=snap.price, tp=math.nan, tp_withheld=False, rating="", stance="", tier="", upside=math.nan,
               fair_low=math.nan, fair_high=math.nan, spread=math.nan, n_methods=0, methods="", skipped=json.dumps(val.skipped))
    if s is None:
        return out
    out.update(tp=s.central if s.central is not None else math.nan, tp_withheld=s.withheld, rating=s.rating, stance=s.stance,
               tier=s.tier, upside=s.upside, fair_low=s.low, fair_high=s.high, spread=s.spread if s.spread is not None else math.nan,
               n_methods=len(s.methods), methods=",".join(m.key for m in s.methods))
    return out


# ── outcomes (after the signal date; read-only prices) ────────────────────

def compute_outcomes(sig: dict, px: pd.DataFrame, nifty: pd.Series) -> list[dict]:
    """One row per horizon. P0 = first close on/after A (engine rule); later prices = last trading day <= A + h days."""
    A = pd.Timestamp(sig["avail_date"]).date()
    day, p0, adj0 = _first_on_or_after(px, A)
    n0 = float(nifty.loc[nifty.index >= day].iloc[0])
    tp = sig["tp"]
    rows = []
    for h, days in HORIZON_DAYS.items():
        d = A + timedelta(days=days)
        later = _asof(px, d)
        nts = pd.Timestamp(d)
        if later is None or nts > nifty.index[-1]:
            continue
        ph, adjh = later
        nh = float(nifty.loc[:nts].iloc[-1])
        price_ret, tot_ret, bench = ph / p0 - 1, adjh / adj0 - 1, nh / n0 - 1
        fr = tp / p0 - 1 if tp == tp else math.nan
        rec = sig["rating"]
        excess = tot_ret - bench
        hit = (excess > 0 if rec == "BUY" else excess < 0 if rec == "SELL" else abs(excess) <= HOLD_BAND[h]) if rec else None
        rows.append({**sig, "horizon_m": h, "p0": p0, "p_h": ph, "forecast_return": fr, "price_return": price_ret, "total_return": tot_ret,
                     "bench_return": bench, "excess_return": excess,
                     "tp_err_signed": (tp - ph) / ph if tp == tp else math.nan, "tp_err_abs": abs(tp - ph) / ph if tp == tp else math.nan,
                     "fr_err": fr - price_ret if fr == fr else math.nan, "hit": hit})
    return rows


# ── offline loaders ───────────────────────────────────────────────────────
def load_prices(symbol: str, meta: dict) -> pd.DataFrame:
    """Cache-only (any age): the symbol, then the engine's alternates. No network."""
    for s in [symbol, *data.alt_symbols(symbol, meta)]:
        p = fdata._path(s)
        if p.exists():
            df = pd.read_parquet(p)[["close", "adj_close"]].dropna()
            if not df.empty:
                return df
    raise FileNotFoundError(f"no cached prices for {symbol}")


def load_nifty() -> pd.Series:
    return pd.read_parquet(fdata._path("^NSEI"))["adj_close"]


def group_of(symbol: str, meta: dict) -> str:
    base = symbol.rsplit(".", 1)[0]
    for g, names in PILOT_GROUPS.items():
        if base in names:
            return g
    return meta.get("sector") or "unclassified"


def run_company(symbol: str, nifty: pd.Series) -> tuple[list[dict], list[str]]:
    """(outcome rows, failure notes) for every origin the forecast sweep scored (non-refused). Offline."""
    of = RESULTS / f"{symbol}.origins.parquet"
    notes: list[str] = []
    if not of.exists() or not data.cached(symbol):
        return [], [f"{symbol}: no results/cache"]
    o = pd.read_parquet(of)
    o = o[(o.refused_reason == "") & o.v_base.notna() & o.origin_fy.str[-4:].astype(int).between(2018, 2025)]  # spec: FY2018..FY2025
    if o.empty:
        return [], []
    tables, meta = data.load(symbol)
    clean, _, excl = data.quality(tables, meta)
    if "pl" not in clean:
        return [], [f"{symbol}: no P&L"]
    try:
        px = load_prices(symbol, meta)
    except FileNotFoundError as e:
        return [], [str(e)]
    grp = group_of(symbol, meta)
    rows = []
    for _, orow in o.iterrows():
        try:
            sig = signal(symbol, clean, meta, px, nifty, orow.origin_fy)
        except NoOrigin as e:
            notes.append(f"{symbol} {orow.origin_fy}: {e}")
            continue
        except Exception as e:
            notes.append(f"{symbol} {orow.origin_fy}: {type(e).__name__}: {e}")
            continue
        if not sig["rating"]:
            notes.append(f"{symbol} {orow.origin_fy}: no valuation")
            continue
        sig.update(sector=grp, size_bucket=orow.size_bucket, origin_year=int(orow.origin_fy[-4:]), v_bear=orow.v_bear, v_base=orow.v_base,
                   v_bull=orow.v_bull, v_weighted=orow.v_weighted, g1=orow.g1, margin=orow.margin, wacc_or_coe=orow.wacc_or_coe, tg=orow.tg)
        got = compute_outcomes(sig, px, nifty)
        if not got:
            notes.append(f"{symbol} {orow.origin_fy}: no price at any horizon (history ends before A+91d)")
        rows += got
    return rows, notes


def _work(args):
    sym, nifty = args
    try:
        return run_company(sym, nifty)
    except Exception as e:  # one company must not sink the run
        return [], [f"{sym}: {type(e).__name__}: {e}"]


def run(symbols: list[str], workers: int = 4) -> tuple[pd.DataFrame, list[str]]:
    import multiprocessing as mp
    nifty = load_nifty()
    jobs = [(s, nifty) for s in symbols]
    if workers > 1 and len(jobs) > 8:
        with mp.Pool(workers) as pool:
            res = pool.map(_work, jobs, chunksize=8)
    else:
        res = [_work(j) for j in jobs]
    rows = [r for rr, _ in res for r in rr]
    notes = [n for _, nn in res for n in nn]
    return pd.DataFrame(rows), notes


def all_symbols() -> list[str]:
    return sorted(p.name[: -len(".origins.parquet")] for p in RESULTS.glob("*.origins.parquet"))


def pilot_symbols() -> list[str]:
    have = set(all_symbols())
    return [f"{b}.NS" for names in PILOT_GROUPS.values() for b in names if f"{b}.NS" in have]


# ── statistics ────────────────────────────────────────────────────────────
def _ci(df: pd.DataFrame, col: str, stat: str = "mean"):
    d = df[["symbol", col]].copy()
    d[col] = d[col].astype(float)
    d = d.dropna()
    if d.symbol.nunique() < MIN_COMPANIES:
        return None
    r = _boot([g[col].to_numpy() for _, g in d.groupby("symbol")], stat)
    return None if r is None else {"est": r[0], "lo": r[1], "hi": r[2]}


def _cell(df: pd.DataFrame) -> dict:
    """Metrics for one slice; suppressed (n_companies only) below MIN_COMPANIES companies."""
    n_c, n = int(df.symbol.nunique()), len(df)
    if n_c < MIN_COMPANIES:
        return {"n_companies": n_c, "n_obs": n, "suppressed": True}
    d = df.assign(hit_f=df.hit.astype(float))
    tp = d.dropna(subset=["tp_err_abs"])
    return {"n_companies": n_c, "n_obs": n, "hit_rate": _ci(d, "hit_f"), "mean_excess": _ci(d, "excess_return"),
            "median_excess": _ci(d, "excess_return", "median"), "mean_total_return": float(d.total_return.mean()),
            "mean_bench_return": float(d.bench_return.mean()), "n_tp": len(tp),
            "tp_abs_err_median": float(tp.tp_err_abs.median()) if len(tp) else None,
            "tp_signed_err_median": float(tp.tp_err_signed.median()) if len(tp) else None,
            "fr_err_median": float(tp.fr_err.median()) if len(tp) else None}


def _spearman(a: pd.Series, b: pd.Series) -> float | None:
    d = pd.concat([a, b], axis=1).dropna()
    return float(d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank())) if len(d) > 30 else None


def baselines(df: pd.DataFrame) -> dict:
    """Same rows, same hit rules: always-BUY, always-HOLD, always-SELL, random (fixed seed, uniform), plus buy-and-hold / Nifty."""
    rng = np.random.default_rng(SEED)
    out = {}
    h = df.horizon_m.to_numpy()
    band = np.array([HOLD_BAND[x] for x in h])
    ex = df.excess_return.to_numpy()
    hits = {"BUY": ex > 0, "SELL": ex < 0, "HOLD": np.abs(ex) <= band}
    rnd = rng.choice(RECS, len(df))
    for name, rec in {"always_BUY": np.full(len(df), "BUY"), "always_HOLD": np.full(len(df), "HOLD"), "always_SELL": np.full(len(df), "SELL"),
                      "random_uniform": rnd}.items():
        hh = np.select([rec == r for r in RECS], [hits[r] for r in RECS])
        out[name] = {"hit_rate": float(hh.mean())}
    # random with ARIA's own recommendation mix (matches base rates of the event)
    mix = df.rating.value_counts(normalize=True).reindex(RECS).fillna(0).to_numpy()
    rm = rng.choice(RECS, len(df), p=mix)
    out["random_same_mix"] = {"hit_rate": float(np.select([rm == r for r in RECS], [hits[r] for r in RECS]).mean())}
    out["aria"] = {"hit_rate": float(df.hit.astype(float).mean())}
    out["buy_and_hold_all_stocks"] = {"mean_total_return": float(df.total_return.mean()), "mean_excess_vs_nifty": float(df.excess_return.mean())}
    out["equal_weight_nifty"] = {"mean_return": float(df.bench_return.mean()), "mean_excess": 0.0}
    return out


def summarize(rows: pd.DataFrame) -> dict:
    s: dict = {"n_rows": len(rows), "n_companies": int(rows.symbol.nunique()), "n_origins": int(rows.drop_duplicates(["symbol", "origin_fy"]).shape[0])}
    sig = rows.drop_duplicates(["symbol", "origin_fy"])
    s["rec_distribution"] = sig.rating.value_counts(normalize=True).reindex(RECS).fillna(0).to_dict()
    s["tier_distribution"] = sig.tier.value_counts(normalize=True).to_dict()
    s["withheld_share"] = float(sig.tp_withheld.mean())
    s["median_ln_V_over_P0"] = float(np.log(sig.v_weighted / sig.p0).median()) if sig.v_weighted.notna().any() else None
    s["rec_by_origin_year"] = {int(y): g.rating.value_counts(normalize=True).reindex(RECS).fillna(0).round(3).to_dict() for y, g in sig.groupby("origin_year")}
    s["rec_by_model"] = {m: g.rating.value_counts(normalize=True).reindex(RECS).fillna(0).round(3).to_dict() for m, g in sig.groupby("model")}
    s["verdict_bands"] = {k: list(v) for k, v in VERDICT_BANDS.items()}
    s["hold_bands"] = HOLD_BAND
    s["horizons"] = {}
    for h, g in rows.groupby("horizon_m"):
        s["horizons"][int(h)] = {
            "overall": _cell(g),
            "by_rating": {r: _cell(g[g.rating == r]) for r in RECS},
            "by_sector": {k: _cell(x) for k, x in g.groupby("sector")},
            "by_size": {k: _cell(x) for k, x in g.groupby("size_bucket") if k},
            "by_origin_year": {int(k): _cell(x) for k, x in g.groupby("origin_year")},
            "by_model": {k: _cell(x) for k, x in g.groupby("model")},
            "baselines": baselines(g),
            "tp": {"abs_err_quantiles": g.tp_err_abs.dropna().quantile([.1, .25, .5, .75, .9]).round(4).tolist(),
                   "signed_err_median": float(g.tp_err_signed.median()), "n_tp": int(g.tp_err_abs.notna().sum()),
                   "forecast_return_median": float(g.forecast_return.median()), "actual_price_return_median": float(g.price_return.median()),
                   "naive_tp_equals_p0_abs_err_median": float((g.p_h / g.p0 - 1).abs().median())},
        }
        up = g.dropna(subset=["upside", "excess_return"])
        cal = {"spearman_upside_vs_excess": _spearman(up.upside, up.excess_return),
               "spearman_forecast_return_vs_actual_price_return": _spearman(g.forecast_return, g.price_return), "deciles": []}
        if len(up) >= 100:
            up = up.assign(dec=pd.qcut(up.upside.rank(method="first"), 10, labels=False) + 1)
            cal["deciles"] = [{"decile": int(d), "mean_upside": float(x.upside.mean()), "mean_excess": float(x.excess_return.mean()),
                               "n": len(x)} for d, x in up.groupby("dec")]
        # company-level cluster bootstrap of the rank correlation would need resampling; report the point estimate only
        s["horizons"][int(h)]["calibration"] = cal
        br = {r: g[g.rating == r].excess_return for r in ("BUY", "SELL")}
        s["horizons"][int(h)]["buy_minus_sell_excess"] = (float(br["BUY"].mean() - br["SELL"].mean()) if len(br["BUY"]) and len(br["SELL"]) else None)
    return s


# ── brokers ───────────────────────────────────────────────────────────────
BROKER_MAP = {"BUY": "BUY", "ADD": "BUY", "ACCUMULATE": "BUY", "OUTPERFORM": "BUY", "OVERWEIGHT": "BUY", "STRONG BUY": "BUY",
              "HOLD": "HOLD", "NEUTRAL": "HOLD", "MARKET PERFORM": "HOLD", "EQUAL-WEIGHT": "HOLD", "REDUCE": "SELL", "SELL": "SELL",
              "UNDERPERFORM": "SELL", "UNDERWEIGHT": "SELL", "STRONG SELL": "SELL"}


def broker_rows(csv: str | Path, nifty: pd.Series) -> tuple[pd.DataFrame, list[str]]:
    """CSV schema: symbol,date,broker,rating,target,horizon (horizon in months, optional; evaluated at 3/6/12m regardless).
    ``date`` is the publication date: P0 = first close on/after it, same outcome rules as ARIA. Unmapped ratings are dropped
    and counted."""
    b = pd.read_csv(csv)
    miss = {"symbol", "date", "broker", "rating", "target"} - set(b.columns)
    if miss:
        raise ValueError(f"broker CSV is missing columns: {sorted(miss)}")
    rows, notes, cache = [], [], {}
    for r in b.itertuples():
        sym = str(r.symbol).strip().upper()
        sym = sym if "." in sym else sym + ".NS"
        rec = BROKER_MAP.get(str(r.rating).strip().upper())
        if rec is None:
            notes.append(f"{sym} {r.date}: unmapped rating {r.rating!r}")
            continue
        try:
            if sym not in cache:
                meta = json.loads(data._path(sym, "meta.json").read_text()) if data.cached(sym) else {}
                cache[sym] = load_prices(sym, meta)
            px = cache[sym]
            A = pd.Timestamp(r.date).date()
            if _first_on_or_after(px, A) is None:
                raise FileNotFoundError("no price after publication date")
            sig = dict(symbol=sym, origin_fy=str(r.broker), avail_date=A.isoformat(), model=str(r.broker), p0=math.nan,
                       tp=float(r.target) if pd.notna(r.target) else math.nan, tp_withheld=False, rating=rec, upside=math.nan)
            got = compute_outcomes(sig, px, nifty)
            for g in got:
                g.update(sector="broker", size_bucket="", origin_year=A.year, upside=g["forecast_return"])
            rows += got
        except Exception as e:
            notes.append(f"{sym} {r.date}: {type(e).__name__}: {e}")
    return pd.DataFrame(rows), notes


# ── markdown ──────────────────────────────────────────────────────────────
def _p(x, d=1) -> str:
    return "n/a" if x is None or x != x else f"{100 * x:.{d}f}%"


def _ciS(c, pp=True) -> str:
    return "n/a" if not c else f"{_p(c['est'])} [{_p(c['lo'])}, {_p(c['hi'])}]"


def _cell_row(name: str, c: dict) -> str:
    if c.get("suppressed"):
        return f"| {name} | {c['n_companies']} | {c['n_obs']} | suppressed (< {MIN_COMPANIES} companies) | | | |"
    return (f"| {name} | {c['n_companies']} | {c['n_obs']} | {_ciS(c['hit_rate'])} | {_ciS(c['mean_excess'])} | "
            f"{_ciS(c['median_excess'])} | {_p(c['tp_abs_err_median'])} |")


HDR = "| slice | companies | obs | hit rate [90% CI] | mean excess [90% CI] | median excess [90% CI] | median |TP error| |\n|---|---|---|---|---|---|---|"


def write_markdown(s: dict, notes: list[str], label: str, path: Path, brokers: dict | None = None) -> None:
    L = [f"# Report validation (Experiment 2): {label}", "",
         "Validates ARIA's equity-research call (target price, BUY/HOLD/SELL) point-in-time against realised prices. "
         "Rule used is ARIA's own (`comps.verdict`, `VERDICT_BANDS`), unchanged; thresholds and the HOLD rule were fixed before any outcome was read. "
         "No parameter was tuned on outcomes. This run is "
         + ("a methodology demonstration on a hand-picked pilot (not representative)." if "pilot" in label.lower() else "the full-universe run.") , "",
         f"Rows {s['n_rows']:,} (company x origin x horizon) | companies {s['n_companies']:,} | origins {s['n_origins']:,}.", "",
         "## ARIA's rule", "",
         "`upside = central/price - 1` (nearest range edge when the point estimate is withheld); BUY if `upside >= buy_band`, SELL if "
         "`upside <= -sell_band`, else HOLD. Bands (buy, sell) by confidence tier: " + "; ".join(f"{k} {v[0]:.0%}/{v[1]:.0%}" for k, v in s["verdict_bands"].items()) +
         ". In the backtest there are no peers and no street target, so only intrinsic methods exist (DCF; banks DDM + justified P/B). "
         "Target price = the synthesis central value; when withheld (> 4x from price, or methods diverge) there is a rating but no target.", "",
         f"HOLD hit rule: |excess| <= {', '.join(f'{k}m {v:.1%}' for k, v in s['hold_bands'].items())}. BUY hit: excess > 0. SELL hit: excess < 0. "
         "Excess = stock total return (adjusted close) minus Nifty 50 price return (^NSEI, no dividends, so slightly flatters the stock).", "",
         "## Distribution of recommendations (a finding)", "",
         "| BUY | HOLD | SELL | target withheld | median ln(V/P0) |\n|---|---|---|---|---|",
         f"| {_p(s['rec_distribution']['BUY'])} | {_p(s['rec_distribution']['HOLD'])} | {_p(s['rec_distribution']['SELL'])} | {_p(s['withheld_share'])} | "
         f"{'n/a' if s['median_ln_V_over_P0'] is None else format(s['median_ln_V_over_P0'], '.2f')} |", "",
         "By origin year (BUY/HOLD/SELL): " + "; ".join(f"{y}: {_p(v['BUY'],0)}/{_p(v['HOLD'],0)}/{_p(v['SELL'],0)}" for y, v in s["rec_by_origin_year"].items()), "",
         "By model: " + "; ".join(f"{m}: {_p(v['BUY'],0)}/{_p(v['HOLD'],0)}/{_p(v['SELL'],0)}" for m, v in s["rec_by_model"].items()), ""]
    for h, hs in s["horizons"].items():
        L += [f"## Horizon {h} months", "", "### Recommendation performance", "", HDR, _cell_row("all", hs["overall"])]
        L += [_cell_row(r, hs["by_rating"][r]) for r in RECS]
        L += ["", f"BUY minus SELL mean excess: {_p(hs['buy_minus_sell_excess'])}.", "", "### Baselines (same rows, same hit rules)", "",
              "| strategy | hit rate | note |\n|---|---|---|"]
        b = hs["baselines"]
        for k in ("aria", "always_BUY", "always_HOLD", "always_SELL", "random_uniform", "random_same_mix"):
            L.append(f"| {k} | {_p(b[k]['hit_rate'])} | |")
        L += [f"| buy-and-hold all stocks | mean total return {_p(b['buy_and_hold_all_stocks']['mean_total_return'])} | excess vs Nifty {_p(b['buy_and_hold_all_stocks']['mean_excess_vs_nifty'])} |",
              f"| equal-weight Nifty | mean return {_p(b['equal_weight_nifty']['mean_return'])} | excess 0 by construction |", "",
              "### Target-price error", ""]
        t = hs["tp"]
        L += [f"Rows with a target: {t['n_tp']:,}. |TP-P_h|/P_h quantiles (10/25/50/75/90%): " + ", ".join(_p(x) for x in t["abs_err_quantiles"]) +
              f". Median signed (TP-P_h)/P_h {_p(t['signed_err_median'])} (positive = target above the realised price). "
              f"Median forecast return {_p(t['forecast_return_median'])} vs median actual price return {_p(t['actual_price_return_median'])}. "
              f"Reference: a 'no change' target (TP=P0) has median |error| {_p(t['naive_tp_equals_p0_abs_err_median'])}.", "",
              "### Calibration", "",
              f"Spearman(upside, excess return) = {t_fmt(hs['calibration']['spearman_upside_vs_excess'])}; Spearman(forecast return, actual price return) = "
              f"{t_fmt(hs['calibration']['spearman_forecast_return_vs_actual_price_return'])} (observations overlap; no CI).", ""]
        if hs["calibration"]["deciles"]:
            L += ["| decile of upside | n | mean upside | mean excess |\n|---|---|---|---|"]
            L += [f"| {d['decile']} | {d['n']} | {_p(d['mean_upside'])} | {_p(d['mean_excess'])} |" for d in hs["calibration"]["deciles"]]
            L.append("")
        for key, title in (("by_sector", "Sector"), ("by_size", "Size"), ("by_origin_year", "Origin year"), ("by_model", "Model")):
            L += [f"### By {title}", "", HDR] + [_cell_row(str(k), c) for k, c in hs[key].items()] + [""]
    if brokers:
        L += ["## Brokers vs ARIA (supplied CSV)", "", "| source | horizon | obs | hit rate | mean excess | median |TP error| |\n|---|---|---|---|---|---|"]
        for h, d in brokers.items():
            for k, c in d.items():
                L.append(f"| {k} | {h}m | {c['n']} | {_p(c['hit'])} | {_p(c['excess'])} | {_p(c['tp'])} |")
        L.append("")
    L += ["## Coverage and failure cases", "", f"{len(notes):,} origins/companies could not be scored here. First reasons:", ""]
    L += [f"- {n}" for n in notes[:15]]
    L += ["", "## Limitations", "",
          "- Survivorship: only today's listings; delisted/merged companies are absent, which flatters every strategy.",
          "- Statements are screener.in restated figures with an assumed 90-day publication lag; sector labels and FI_* inputs (risk-free, ERP) are today's.",
          "- Backtest signal has no peer-multiple method and no analyst-target input, so it is ARIA's intrinsic-value call only, not the full live report (LLM debate/judge excluded).",
          "- Overlapping origins and horizons share price paths and market-wide moves: effective n is far below the row count; CIs resample whole companies "
          "but not calendar time, so common market shocks are not captured. Calendar-year slices show the regime dependence.",
          "- One target price is used for all horizons; a 12-month target is only fully due at 12m, so 3m/6m error is not a fair test of the target.",
          "- Benchmark is the Nifty 50 price index (no dividends); the stock side includes dividends. Excess return is not beta-adjusted.",
          "- Hit rates for BUY/SELL (a sign) and HOLD (a band) are different events; compare with the matching random baseline.",
          "- Pilot symbols are hand-picked large, well-known names (survivors by construction)."]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def t_fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"
