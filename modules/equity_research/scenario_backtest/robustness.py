"""Statistical-robustness layer for Experiment 2 (report validation) and the scenario-coverage claim. Offline, read-only.

Everything here is computed from files already on disk (report_validation/rows.parquet, forecast_cache prices, results/*.origins|forecasts.parquet).
Nothing is tuned on outcomes except one thing, declared up front: the calibrated-interval scale factor, fitted on FY2018-2021 origins only and
then scored on FY2022-2025 origins.

Inference: every interval is a 95% company-clustered bootstrap (resample whole companies with replacement, 2000 draws, seed 0). Differences against
baselines are PAIRED (same rows). p-values: clustered-bootstrap two-sided p, plus a permutation p that shuffles the calls among companies inside
each origin year (the null "the call carries no information beyond the year's mix of calls").

Return definitions (the stock side is always the same company-row):
  headline : stock total return (adj. close) minus Nifty 50 PRICE return        (as in report_validation; slightly flatters the stock)
  pr_vs_pr : stock PRICE return minus Nifty price return                        (apples to apples, no dividends either side)
  tr_vs_tri: stock total return minus Nifty TRI proxy = price return plus a constant dividend yield (TRI_YIELD)
  alpha    : stock total return minus [rf + beta * (TRI proxy - rf)], beta = OLS on the 260 weekly returns before the origin date
Outcome class (common definition): outperform if excess > +X, underperform if excess < -X, else in line, X = HOLD_BAND of the horizon (fixed in
advance, 5 / 7.5 / 10 pp at 3 / 6 / 12 months).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .report_validation import HOLD_BAND, HORIZON_DAYS, OUT, RECS, RESULTS, load_nifty

N_BOOT, SEED, N_PERM, N_RAND = 2000, 0, 2000, 1000
TRI_YIELD = 0.013        # assumed Nifty 50 dividend yield, per year (proxy for the TRI-price gap; typical range 1.1-1.5%)
RF = 0.065               # assumed constant risk-free rate for alpha (today's-style input, see "not controlled")
BETA_WEEKS, BETA_MIN = 260, 104
ADV_FLOOR_CR, MCAP_FLOOR_CR = 1.0, 1000.0   # liquidity filters: 60-day median traded value >= INR 1 cr/day; market cap >= INR 1,000 cr
COSTS_BPS = (0, 25, 50, 100)
SPLIT_YEAR = 2021        # early = FY2018-2021, late = FY2022-2025
TARGET_COVERAGE = 0.68
IDX = {"BUY": 0, "HOLD": 1, "SELL": 2}
DEFS = {"headline": "total return minus Nifty price return (as in the main run)",
        "pr_vs_pr": "price return minus Nifty price return (apples to apples)",
        "tr_vs_tri": f"total return minus Nifty TRI proxy (price + {TRI_YIELD:.1%}/yr dividends)",
        "winsor": "headline excess clipped at the 1st/99th percentile of each horizon (tames small-cap multi-baggers; only mean-based numbers move)",
        "alpha": f"beta-adjusted alpha vs TRI proxy (rf {RF:.1%}, beta from 260 weeks before origin)"}
EXTRAS = OUT / "robustness_extras.parquet"
CASES = OUT / "robustness_cases.parquet"
TRI_NOTE = ("No free Nifty 50 Total Return Index series could be obtained: niftyindices.com's historical-data endpoint returned its HTML front page "
            "instead of data (request 1), and Yahoo Finance has no '^NSEITRI' symbol (404, request 2). A proxy is used instead: Nifty 50 price return "
            f"plus a constant {TRI_YIELD:.1%}/yr dividend yield. This is an assumption; the true TRI-price gap varied by year.")


# ── cluster bootstrap ─────────────────────────────────────────────────────
_W: dict = {}


def _weights(G: int, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    k = (G, n_boot, seed)
    if k not in _W:
        _W.clear()
        _W[k] = np.random.default_rng(seed).multinomial(G, np.full(G, 1 / G), size=n_boot).astype(float)
    return _W[k]


def cluster_boot(symbols, comps: list, f, n_boot: int = N_BOOT, seed: int = SEED) -> dict | None:
    """Statistic f(*sums) of per-row components, summed per company; companies resampled with replacement.
    Returns est, 95% percentile CI, two-sided bootstrap p (H0: statistic = 0), n_companies."""
    codes, _ = pd.factorize(np.asarray(symbols))
    G = int(codes.max()) + 1 if len(codes) else 0
    if G < 2:
        return None
    A = np.column_stack([np.bincount(codes, weights=np.asarray(c, float), minlength=G) for c in comps])
    with np.errstate(all="ignore"):
        est = float(f(*A.sum(0)))
        dr = np.asarray(f(*(_weights(G, n_boot, seed) @ A).T), float)
    dr = dr[np.isfinite(dr)]
    if not len(dr) or not math.isfinite(est):
        return None
    p = min(1.0, 2 * min((1 + (dr <= 0).sum()) / (len(dr) + 1), (1 + (dr >= 0).sum()) / (len(dr) + 1)))
    return {"est": est, "lo": float(np.quantile(dr, .025)), "hi": float(np.quantile(dr, .975)), "p": float(p), "n_companies": G}


def boot_mean(symbols, x) -> dict | None:
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    return cluster_boot(np.asarray(symbols)[ok], [x[ok], np.ones(ok.sum())], lambda s, n: s / n)


def boot_median(symbols, x, n_boot: int = N_BOOT, seed: int = SEED) -> dict | None:
    """Company-clustered bootstrap of the pooled median (95% CI)."""
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    codes, _ = pd.factorize(np.asarray(symbols)[ok])
    v = x[ok]
    if len(v) == 0 or codes.max() < 1:
        return None
    G = int(codes.max()) + 1
    order = np.argsort(v, kind="stable")
    v, gid = v[order], codes[order]
    W, out = _weights(G, n_boot, seed), np.empty(n_boot)
    for s in range(0, n_boot, 100):
        w = W[s:s + 100][:, gid]
        out[s:s + 100] = v[(np.cumsum(w, 1) >= w.sum(1)[:, None] / 2).argmax(1)]
    return {"est": float(np.median(v)), "lo": float(np.quantile(out, .025)), "hi": float(np.quantile(out, .975)), "n_companies": G}


def paired_mean(symbols, a, b) -> dict | None:
    """Mean of (a - b) over matched rows with a clustered CI: ARIA minus baseline."""
    return boot_mean(symbols, np.asarray(a, float) - np.asarray(b, float))


def perm_p(r: np.ndarray, years: np.ndarray, stat, n_perm: int = N_PERM, seed: int = SEED) -> dict:
    """Permutation test: shuffle the calls r among rows inside each origin year; stat(r) -> float. Two-sided p around the null mean."""
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(years == y) for y in np.unique(years)]
    obs, null = stat(r), np.empty(n_perm)
    for i in range(n_perm):
        rp = r.copy()
        for g in groups:
            rp[g] = r[rng.permutation(g)]
        null[i] = stat(rp)
    m = null.mean()
    return {"obs": float(obs), "null_mean": float(m), "p": float((1 + (np.abs(null - m) >= abs(obs - m)).sum()) / (n_perm + 1))}


# ── returns under the four definitions ────────────────────────────────────
def add_returns(rows: pd.DataFrame, extras: pd.DataFrame | None = None) -> pd.DataFrame:
    d = rows.copy()
    yrs = d.horizon_m.map(HORIZON_DAYS).to_numpy(float) / 365
    d["bench_tri"] = (1 + d.bench_return) * (1 + TRI_YIELD) ** yrs - 1
    d["headline"] = d.excess_return
    d["pr_vs_pr"] = d.price_return - d.bench_return
    d["tr_vs_tri"] = d.total_return - d.bench_tri
    lo, hi = d.groupby("horizon_m").headline.transform(lambda x: x.quantile(.01)), d.groupby("horizon_m").headline.transform(lambda x: x.quantile(.99))
    d["winsor"] = d.headline.clip(lo, hi)
    if extras is not None:
        d = d.merge(extras, on=["symbol", "origin_fy"], how="left")
        rf = (1 + RF) ** yrs - 1
        d["alpha"] = d.total_return - (rf + d.beta * (d.bench_tri - rf))
    else:
        d["alpha"] = np.nan
    return d


def _hits(ex: np.ndarray, h: int) -> np.ndarray:
    """n x 3 success matrix (BUY: excess > 0; HOLD: |excess| <= X; SELL: excess < 0)."""
    return np.column_stack([ex > 0, np.abs(ex) <= HOLD_BAND[h], ex < 0])


# ── the core comparison for one slice ─────────────────────────────────────
def core(df: pd.DataFrame, ex_col: str, h: int, n_perm: int = N_PERM) -> dict:
    """ARIA vs baselines on one slice (single horizon): hit rate, signed excess, per-rating, spread, 3-class accuracy. Paired, clustered."""
    d = df.dropna(subset=[ex_col])
    n = len(d)
    if n < 100 or d.symbol.nunique() < 30:
        return {"n_obs": n, "n_companies": int(d.symbol.nunique()), "suppressed": True}
    sym, ex = d.symbol.to_numpy(), d[ex_col].to_numpy(float)
    r, yrs = d.rating.map(IDX).to_numpy(), d.origin_year.to_numpy()
    H, ar, X = _hits(ex, h), np.arange(n), HOLD_BAND[h]
    mix = np.bincount(r, minlength=3) / n
    cvec = np.array([1.0, 0.0, -1.0])
    rng = np.random.default_rng(SEED)
    rand_hit, rand_sig = np.zeros(n), np.zeros(n)
    for _ in range(N_RAND // 100):                       # N_RAND seeded random draws of calls with ARIA's own mix
        dr = rng.choice(3, size=(100, n), p=mix)
        rand_hit += H[ar, dr].mean(0)
        rand_sig += (cvec[dr] * ex).mean(0)
    rand_hit, rand_sig = rand_hit / (N_RAND // 100), rand_sig / (N_RAND // 100)
    hit = H[ar, r].astype(float)
    sig = cvec[r] * ex
    out: dict = {"n_obs": n, "n_companies": int(d.symbol.nunique()), "mix": {k: float(mix[i]) for k, i in IDX.items()}, "X": X}
    out["hit"] = {"aria": boot_mean(sym, hit)}
    out["signed_excess"] = {"aria": boot_mean(sym, sig)}
    base_h = {"random_same_mix": rand_hit, "always_BUY": H[:, 0].astype(float), "always_SELL": H[:, 2].astype(float), "always_HOLD": H[:, 1].astype(float)}
    base_s = {"random_same_mix": rand_sig, "always_BUY (= buy-and-hold)": ex, "always_SELL": -ex, "always_HOLD (cash at benchmark)": np.zeros(n)}
    out["hit"]["baseline"] = {k: float(v.mean()) for k, v in base_h.items()}
    out["hit"]["paired_vs"] = {k: paired_mean(sym, hit, v) for k, v in base_h.items()}
    out["signed_excess"]["baseline"] = {k: float(v.mean()) for k, v in base_s.items()}
    out["signed_excess"]["paired_vs"] = {k: paired_mean(sym, sig, v) for k, v in base_s.items()}
    out["hit"]["perm_year"] = perm_p(r, yrs, lambda rr: H[ar, rr].mean(), n_perm)
    out["signed_excess"]["perm_year"] = perm_p(r, yrs, lambda rr: (cvec[rr] * ex).mean(), n_perm)
    per = {}
    for k, i in IDX.items():
        m = r == i
        nc = len(np.unique(sym[m]))
        if m.sum() < 30 or nc < 30:
            per[k] = {"n_obs": int(m.sum()), "n_companies": nc, "suppressed": True}
            continue
        mi = m.astype(float)
        per[k] = {"n_obs": int(m.sum()), "n_companies": nc, "hit": boot_mean(sym[m], hit[m]),
                  "hit_base_rate_all_stocks": float(H[:, i].mean()),
                  "hit_minus_base_rate": cluster_boot(sym, [hit * mi, mi, H[:, i].astype(float), np.ones(n)], lambda a, b, c, e: a / b - c / e),
                  "mean_excess": boot_mean(sym[m], ex[m]), "median_excess": boot_median(sym[m], ex[m]),
                  "mean_minus_all_stocks": cluster_boot(sym, [ex * mi, mi, ex, np.ones(n)], lambda a, b, c, e: a / b - c / e)}
    out["per_rating"] = per
    b, s = (r == 0).astype(float), (r == 2).astype(float)
    out["buy_minus_sell"] = cluster_boot(sym, [ex * b, b, ex * s, s], lambda a, bb, c, e: a / bb - c / e) if b.sum() and s.sum() else None
    out["all_stocks_mean_excess"] = float(ex.mean())
    out["all_stocks_median_excess"] = float(np.median(ex))
    y = np.where(ex > X, 0, np.where(ex < -X, 2, 1))     # common outcome definition: 0 outperform, 1 in line, 2 underperform
    conf = np.zeros((3, 3), int)
    np.add.at(conf, (r, y), 1)
    maj = int(np.bincount(y, minlength=3).argmax())
    corr, majc = (r == y).astype(float), (y == maj).astype(float)
    share = np.bincount(y, minlength=3) / n
    out["classes"] = {"labels": ["outperform", "in-line", "underperform"], "rows": "ARIA call (BUY, HOLD, SELL)", "confusion": conf.tolist(),
                      "outcome_share": share.tolist(), "accuracy": boot_mean(sym, corr),
                      "majority_class": ["outperform", "in-line", "underperform"][maj], "majority_accuracy": float(majc.mean()),
                      "random_same_mix_accuracy": float((mix * share).sum()),
                      "accuracy_minus_majority": paired_mean(sym, corr, majc),
                      "recall": [float(conf[i, i] / conf[:, i].sum()) if conf[:, i].sum() else None for i in range(3)],
                      "precision": [float(conf[i, i] / conf[i].sum()) if conf[i].sum() else None for i in range(3)],
                      "perm_year": perm_p(r, yrs, lambda rr: (rr == y).mean(), n_perm)}
    return out


def why_always_sell(d: pd.DataFrame) -> dict:
    """Numbers behind 'always SELL hits 53-56%': the typical stock trails the cap-weighted index."""
    g = d.dropna(subset=["headline"])

    def one(x):
        return {"n": len(x), "share_underperform": float((x.headline < 0).mean()), "median_excess": float(x.headline.median()),
                "mean_excess": float(x.headline.mean()), "median_stock_total_return": float(x.total_return.median()),
                "median_nifty_return": float(x.bench_return.median()), "mean_stock_total_return": float(x.total_return.mean()),
                "skew_gap_mean_minus_median": float(x.headline.mean() - x.headline.median()),
                "share_underperform_tri_proxy": float((x.tr_vs_tri < 0).mean())}
    out = {"all": one(g), "by_size": {k: one(x) for k, x in g.groupby("size_bucket") if k and len(x) > 100},
           "by_year": {int(k): one(x) for k, x in g.groupby("origin_year")}}
    out["sell_hit_ci"] = boot_mean(g.symbol, (g.headline < 0).astype(float))
    return out


# ── portfolio-style evaluation (12-month horizon, annual rebalance at each origin) ─
def _weights_by_year(d: pd.DataFrame, rating: str) -> dict:
    return {int(y): pd.Series(1 / x.symbol.nunique(), index=x.symbol.unique()) for y, x in d[d.rating == rating].groupby("origin_year") if len(x)}


def turnover(w: dict, years: list) -> dict:
    """One-way turnover as a fraction of the book replaced, 0.5 * sum|dw|; the first year builds the book (counted as 1.0).
    ponytail: weights are not drifted between rebalances (a 12-month drift changes turnover by a few points at most)."""
    out, prev = {}, None
    for y in years:
        cur = w.get(int(y))
        if cur is None:
            out[int(y)] = math.nan
            prev = None
            continue
        out[int(y)] = 1.0 if prev is None else float(0.5 * cur.sub(prev, fill_value=0).abs().sum())
        prev = cur
    return out


def portfolio(d12: pd.DataFrame, ex_col: str = "headline") -> dict:
    """Equal-weight long BUY / short SELL, annual. Excess legs are vs the Nifty, which cancels in the long-short.
    Costs: bps round-trip per unit of book replaced. The short side is hypothetical (borrow is unavailable for most Indian cash stocks)."""
    d = d12.dropna(subset=[ex_col])
    years = sorted(int(y) for y in d.origin_year.unique())
    TL, TS = turnover(_weights_by_year(d, "BUY"), years), turnover(_weights_by_year(d, "SELL"), years)
    tab = []
    for y in years:
        x = d[d.origin_year == y]
        b, s = x[x.rating == "BUY"][ex_col], x[x.rating == "SELL"][ex_col]
        if len(b) and len(s):
            tab.append({"year": y, "n_buy": len(b), "n_sell": len(s), "long_excess": float(b.mean()), "short_excess": float(s.mean()),
                        "long_short": float(b.mean() - s.mean()), "turnover_long": TL[y], "turnover_short": TS[y]})
    out: dict = {"years": tab}
    if not tab:
        return out
    ys = [t["year"] for t in tab]
    sym, ex, yr, rt = d.symbol.to_numpy(), d[ex_col].to_numpy(float), d.origin_year.to_numpy(), d.rating.to_numpy()

    def stat_for(sel: list, kind: str, c_bps: float):
        comps, cost = [], []
        for y in sel:
            m = yr == y
            bm, sm = (m & (rt == "BUY")).astype(float), (m & (rt == "SELL")).astype(float)
            comps += [ex * bm, bm, ex * sm, sm]
            t = next(t for t in tab if t["year"] == y)
            cost.append(c_bps / 1e4 * (t["turnover_long"] + (t["turnover_short"] if kind == "ls" else 0)))
        c = float(np.mean(cost))

        def f(*S):
            res = []
            for i in range(len(sel)):
                lb, ln, sb, sn = S[4 * i:4 * i + 4]
                res.append(lb / ln - (sb / sn if kind == "ls" else 0))
            return np.mean(res, axis=0) - c
        return cluster_boot(sym, comps, f)

    sets = {"all years": ys, f"FY2018-{SPLIT_YEAR}": [y for y in ys if y <= SPLIT_YEAR], f"FY{SPLIT_YEAR + 1}-2025": [y for y in ys if y > SPLIT_YEAR]}
    out["strategies"] = {}
    for kind, name in (("ls", "long BUY / short SELL"), ("lo", "long BUY only, excess vs Nifty")):
        out["strategies"][name] = {}
        for sn, sel in sets.items():
            if not sel:
                continue
            sub = [t for t in tab if t["year"] in sel]
            per_y = [t["long_short"] if kind == "ls" else t["long_excess"] for t in sub]
            row = {"years": sel, "gross_by_year_mean": float(np.mean(per_y)), "sd_by_year": float(np.std(per_y, ddof=1)) if len(per_y) > 1 else None,
                   "positive_years": int(sum(v > 0 for v in per_y)),
                   "turnover_avg": float(np.mean([t["turnover_long"] + (t["turnover_short"] if kind == "ls" else 0) for t in sub])), "cost_bps": {}}
            for c in COSTS_BPS:
                row["cost_bps"][c] = stat_for(sel, kind, c)
            out["strategies"][name][sn] = row
    return out


# ── offline extras: beta, traded value, market cap, flags ─────────────────
_NIFTY_W = None


def _init(nifty):
    global _NIFTY_W
    _NIFTY_W = nifty.resample("W-FRI").last().dropna()


def _extras_one(args):
    sym, origs = args
    nan_rows = [{"symbol": sym, "origin_fy": fy, "beta": math.nan, "adv_cr": math.nan, "mcap_cr": math.nan, "short_history": False} for fy, _ in origs]
    try:
        from modules.equity_research.forecast import data as fdata
        mp_ = data._path(sym, "meta.json")
        meta = json.loads(mp_.read_text()) if mp_.exists() else {}
        px = None
        for s in [sym, *data.alt_symbols(sym, meta)]:
            p = fdata._path(s)
            if p.exists():
                df = pd.read_parquet(p)
                if "adj_close" in df and not df.dropna(subset=["close", "adj_close"]).empty:
                    px = df
                    break
        o = pd.read_parquet(RESULTS / f"{sym}.origins.parquet").drop_duplicates("origin_fy").set_index("origin_fy")
        w = px["adj_close"].dropna().resample("W-FRI").last().dropna().pct_change() if px is not None else None
        nw = _NIFTY_W.pct_change()
        tv = (px["close"] * px["volume"]) if px is not None and "volume" in px else None
        rows = []
        for fy, A in origs:
            A = pd.Timestamp(A)
            beta = adv = math.nan
            if w is not None:
                j = pd.concat([w[w.index <= A], nw[nw.index <= A]], axis=1, keys=["s", "m"]).dropna().tail(BETA_WEEKS)
                if len(j) >= BETA_MIN and j.m.var() > 0:
                    beta = float(j.s.cov(j.m) / j.m.var())
            if tv is not None:
                t = tv[tv.index <= A].tail(60)
                if len(t) >= 20:
                    adv = float(t.median() / 1e7)
            fl = str(o.loc[fy, "flags"]) if fy in o.index and o.loc[fy, "flags"] is not None else ""
            mc = pd.to_numeric(o.loc[fy, "mcap_cr"], errors="coerce") if fy in o.index else math.nan
            rows.append({"symbol": sym, "origin_fy": fy, "beta": beta, "adv_cr": adv, "mcap_cr": float(mc) if mc == mc else math.nan,
                         "short_history": "short_history" in fl})
        return rows
    except Exception:  # one company must not sink the run
        return nan_rows


def build_extras(rows: pd.DataFrame, rebuild: bool = False, workers: int = 4) -> pd.DataFrame:
    sig = rows.drop_duplicates(["symbol", "origin_fy"])[["symbol", "origin_fy", "avail_date"]]
    if EXTRAS.exists() and not rebuild:
        e = pd.read_parquet(EXTRAS)
        if len(sig.merge(e, on=["symbol", "origin_fy"])) == len(sig):
            return e
    import multiprocessing as mp
    jobs = [(s, list(zip(g.origin_fy, g.avail_date))) for s, g in sig.groupby("symbol")]
    with mp.Pool(workers, initializer=_init, initargs=(load_nifty(),)) as pool:
        res = pool.map(_extras_one, jobs, chunksize=16)
    e = pd.DataFrame([r for rr in res for r in rr])
    e.to_parquet(EXTRAS)
    return e


# ── scenario coverage and the empirically calibrated interval ─────────────
LEVEL_LINES, CAL_LINES, CAL_K = ("revenue", "ebitda", "eps"), ("revenue", "ebitda", "margin", "eps"), (1, 2, 3, 4, 5)


def _cases_one(sym):
    try:
        from .metrics import scored
        f, o = pd.read_parquet(RESULTS / f"{sym}.forecasts.parquet"), pd.read_parquet(RESULTS / f"{sym}.origins.parquet")
        w, _ = scored(f, o)
        if w.empty:
            return None
        w = w[w.line.isin(CAL_LINES) & w.k.isin(CAL_K)]
        return w[["symbol", "origin_fy", "line", "k", "actual", "bear", "base", "bull", "structural_break", "short_history"]]
    except Exception:
        return None


def build_cases(rebuild: bool = False, workers: int = 4) -> pd.DataFrame:
    if CASES.exists() and not rebuild:
        return pd.read_parquet(CASES)
    import multiprocessing as mp
    syms = sorted(p.name[: -len(".forecasts.parquet")] for p in RESULTS.glob("*.forecasts.parquet"))
    with mp.Pool(workers) as pool:
        res = pool.map(_cases_one, syms, chunksize=32)
    c = pd.concat([r for r in res if r is not None], ignore_index=True)
    c["origin_year"] = c.origin_fy.str[-4:].astype(int)
    c.to_parquet(CASES)
    return c


def required_scale(c: pd.DataFrame) -> pd.Series:
    """Smallest s such that [base*(bear/base)^s, base*(bull/base)^s] (log-width scaled; margin: additive) contains the actual.
    NaN when the case order is degenerate (need bear < base < bull, and positive levels for log lines)."""
    lvl = c.line.isin(LEVEL_LINES).to_numpy()
    with np.errstate(all="ignore"):
        pos = ((c.bear > 0) & (c.base > 0) & (c.bull > 0) & (c.actual > 0)).to_numpy()
        u = np.where(lvl, np.log(c.actual / c.base), c.actual - c.base)
        a = np.where(lvl, np.log(c.bull / c.base), c.bull - c.base)
        b = np.where(lvl, np.log(c.bear / c.base), c.bear - c.base)
        s = np.where(u >= 0, u / a, u / b)
    good = (a > 0) & (b < 0) & np.where(lvl, pos, True)
    return pd.Series(np.where(good, s, np.nan), index=c.index)


def interval_calibration(c: pd.DataFrame, target: float = TARGET_COVERAGE) -> dict:
    """Scale factor fitted on origins <= SPLIT_YEAR (per line and k, and pooled per line), scored on origins > SPLIT_YEAR."""
    c = c[~c.structural_break & ~c.short_history].copy()
    c["s_req"] = required_scale(c)
    n_all = len(c)
    c = c.dropna(subset=["s_req"])
    early, late = c[c.origin_year <= SPLIT_YEAR], c[c.origin_year > SPLIT_YEAR]
    out = {"target": target, "split": f"fit on FY2018-{SPLIT_YEAR}, scored on FY{SPLIT_YEAR + 1}-2025", "n_dropped_degenerate_cases": n_all - len(c),
           "rule": "interval = [base*(bear/base)^s, base*(bull/base)^s] (margin: base + s*(case - base)); s = the 68th percentile of the minimum scale each early "
                   "observation needed to contain its actual, so coverage on the fitting data is 68% by construction", "cells": {}, "pooled": {}}
    for line in CAL_LINES:
        pe = early[early.line == line]
        s_pool = float(pe.s_req.quantile(target)) if len(pe) >= 100 else None
        out["cells"][line] = {}
        for k in CAL_K:
            e, l = pe[pe.k == k], late[(late.line == line) & (late.k == k)]
            cell = {"n_fit": len(e), "n_fit_companies": int(e.symbol.nunique()), "n_test": len(l), "n_test_companies": int(l.symbol.nunique())}
            if len(e) >= 100 and e.symbol.nunique() >= 30:
                s = float(e.s_req.quantile(target))
                cell["scale"] = s
                cell["fit_coverage_check"] = float((e.s_req <= s).mean())
                if len(l) >= 100 and l.symbol.nunique() >= 30:
                    cell["test_uncalibrated"] = boot_mean(l.symbol, (l.s_req <= 1).astype(float))
                    cell["test_calibrated"] = boot_mean(l.symbol, (l.s_req <= s).astype(float))
                    if s_pool:
                        cell["test_pooled_scale"] = boot_mean(l.symbol, (l.s_req <= s_pool).astype(float))
                else:
                    cell["note"] = "test sample below 100 rows / 30 companies: suppressed"
            else:
                cell["note"] = "fit sample below 100 rows / 30 companies: not calibrated"
            out["cells"][line][k] = cell
        out["pooled"][line] = {"scale": s_pool, "n_fit": len(pe)}
    return out


# ── controls ──────────────────────────────────────────────────────────────
def data_controls(d: pd.DataFrame, cases: pd.DataFrame | None, h: int = 12) -> dict:
    sig = d.drop_duplicates(["symbol", "origin_fy"])
    sb = set()
    if cases is not None and len(cases):
        sbo = cases[cases.structural_break & cases.line.isin(("revenue", "eps"))]
        sb = set(zip(sbo.symbol, sbo.origin_fy))
    x = d[d.horizon_m == h].copy()
    x["struct_break"] = [k in sb for k in zip(x.symbol, x.origin_fy)]
    x["short_hist"] = x["short_history"].fillna(False).astype(bool)
    out = {"share_origins_unclassified_sector": float((sig.sector == "unclassified").mean()),
           "share_companies_unclassified_sector": float((sig.drop_duplicates("symbol").sector == "unclassified").mean()),
           "share_origins_structural_break": float(x.struct_break.mean()), "share_origins_short_history": float(x.short_hist.mean()),
           "share_target_withheld": float(sig.tp_withheld.mean()), "n_origins": len(sig), "n_companies": int(sig.symbol.nunique()),
           "size_mix": sig.size_bucket.value_counts(normalize=True).to_dict()}
    out["sensitivity"] = {"all rows": core(x, "headline", h, 500),
                          "excluding structural-break and short-history origins": core(x[~x.struct_break & ~x.short_hist], "headline", h, 500),
                          "classified sector only": core(x[x.sector != "unclassified"], "headline", h, 500)}
    out["by_size"] = {k: core(g, "headline", h, 500) for k, g in x.groupby("size_bucket") if k}
    return out


# ── run everything ────────────────────────────────────────────────────────
def liquidity_masks(d: pd.DataFrame) -> dict:
    return {"all": np.ones(len(d), bool), f"traded value >= INR {ADV_FLOOR_CR:g} cr/day": (d.adv_cr >= ADV_FLOOR_CR).to_numpy(),
            f"market cap >= INR {MCAP_FLOOR_CR:,.0f} cr": (d.mcap_cr >= MCAP_FLOOR_CR).to_numpy()}


def run_all(rows: pd.DataFrame, extras: pd.DataFrame, cases: pd.DataFrame | None) -> dict:
    d = add_returns(rows[rows.horizon_m.isin([3, 6, 12])], extras)
    res: dict = {"tri": TRI_NOTE, "definitions": DEFS,
                 "constants": {"tri_yield": TRI_YIELD, "rf": RF, "n_boot": N_BOOT, "n_perm": N_PERM, "n_random_draws": N_RAND,
                               "ci": "95% company-clustered percentile bootstrap, seed 0", "x_fixed": HOLD_BAND, "split_year": SPLIT_YEAR},
                 "n_rows": len(d), "n_companies": int(d.symbol.nunique()), "by_definition": {}, "why_always_sell": {}, "oos": {}, "liquidity": {}}
    for ex_col in DEFS:
        res["by_definition"][ex_col] = {h: core(d[d.horizon_m == h], ex_col, h) for h in (3, 6, 12)}
    for h in (3, 6, 12):
        res["why_always_sell"][h] = why_always_sell(d[d.horizon_m == h])
        res["oos"][h] = {"early": core(d[(d.horizon_m == h) & (d.origin_year <= SPLIT_YEAR)], "headline", h),
                         "late": core(d[(d.horizon_m == h) & (d.origin_year > SPLIT_YEAR)], "headline", h)}
    d12 = d[d.horizon_m == 12]
    res["portfolio"] = {k: portfolio(d12, k) for k in ("headline", "winsor", "tr_vs_tri")}
    for name, m in liquidity_masks(d12).items():
        res["liquidity"][name] = {"core_12m": core(d12[m], "headline", 12, 500), "portfolio": portfolio(d12[m], "headline"), "portfolio_w": portfolio(d12[m], "winsor")}
    res["controls"] = data_controls(d, cases)
    res["beta_coverage"] = float(d12.beta.notna().mean())
    res["interval"] = interval_calibration(cases) if cases is not None and len(cases) else None
    res["not_controlled"] = NOT_CONTROLLED
    return res


NOT_CONTROLLED = [
    "Delisted, merged and bankrupt companies are absent (survivorship): only today's listings can be replayed, which flatters every strategy and the long side most.",
    "Statements are screener.in's restated figures, not as first reported, with an assumed 90-day publication lag.",
    "Sector labels are today's (a share of rows is unclassified, quantified below); risk-free rate, equity risk premium and terminal growth are today's inputs applied to the past.",
    "The Nifty TRI is a proxy (price + constant dividend yield); beta is a raw 5-year weekly OLS and the risk-free rate in alpha is a constant.",
    "Overlapping origins and horizons share price paths and market shocks: bootstrapping companies does not capture common calendar-time shocks, so intervals are, if anything, too narrow. The year-level portfolio table shows the regime dependence directly.",
    "The backtest has no peer-multiple method, no analyst targets and no LLM debate: it tests ARIA's intrinsic-value call only.",
    "No short-selling constraints, borrow costs, impact or tax are modelled; the cost sweep is a flat round-trip assumption."]


# ── markdown ──────────────────────────────────────────────────────────────
def _p(x, d=1) -> str:
    return "n/a" if x is None or x != x else f"{100 * x:.{d}f}%"


def _pp(c, d=1) -> str:
    return "n/a" if not c else f"{_p(c['est'], d)} [{_p(c['lo'], d)}, {_p(c['hi'], d)}]"


def _pv(c) -> str:
    return "" if not c or "p" not in c else ("<0.001" if c["p"] < .001 else f"{c['p']:.3f}")


def write_markdown(res: dict, path: Path) -> None:
    L = ["# Statistical robustness of the equity-research validation", "",
         f"{res['n_rows']:,} company-origin-horizon rows, {res['n_companies']:,} companies. All intervals are {res['constants']['ci']}, "
         f"{res['constants']['n_boot']} draws. Differences against baselines are paired (same rows). `p` is the clustered-bootstrap two-sided p-value; "
         f"`p(perm)` shuffles the calls among companies within each origin year ({res['constants']['n_perm']} permutations). Baselines: random calls with ARIA's own mix "
         f"({res['constants']['n_random_draws']} seeded draws), always-BUY (= buy-and-hold every stock), always-SELL, always-HOLD.", "",
         "## Benchmark and return methodology", "", res["tri"], "", "Four excess-return definitions are reported side by side:", ""]
    L += [f"- `{k}`: {v}" for k, v in res["definitions"].items()]
    L += ["", "A stock is credited with a dividend-inclusive return in `headline`, `tr_vs_tri` and `alpha`; `pr_vs_pr` strips dividends from both sides. "
          f"Beta is available for {_p(res['beta_coverage'], 0)} of 12-month rows (needs >= {BETA_MIN} weekly returns); alpha rows without a beta are dropped.", ""]
    for h in (12, 6, 3):
        L += [f"## Horizon {h} months: ARIA minus baselines (paired, 95% clustered CI)", "",
              f"Success rules (fixed in advance): BUY succeeds if excess > 0; SELL if excess < 0; **HOLD succeeds if the stock stays within +-{HOLD_BAND[h]:.1%} of the benchmark** "
              "(a HOLD is a claim 'no material over- or under-performance'). The overall hit rate mixes a sign test (BUY, SELL) with a band test (HOLD), so see also the common 3-class scoring below.", ""]
        for dk in DEFS:
            c = res["by_definition"][dk][h]
            if c.get("suppressed"):
                continue
            L += [f"### {dk}: {DEFS[dk]}", "", f"n = {c['n_obs']:,} rows, {c['n_companies']:,} companies. ARIA hit rate {_pp(c['hit']['aria'])}; p(perm, within year) = {c['hit']['perm_year']['p']:.3f}.", "",
                  "| baseline | baseline hit rate | ARIA minus baseline (hit rate) | p | ARIA minus baseline (signed excess return) | p |\n|---|---|---|---|---|---|"]
            for (k, v), (k2, v2) in zip(c["hit"]["paired_vs"].items(), c["signed_excess"]["paired_vs"].items()):
                L.append(f"| {k} | {_p(c['hit']['baseline'][k])} | {_pp(v)} | {_pv(v)} | {k2}: {_pp(v2)} | {_pv(v2)} |")
            L += ["", f"Signed excess return = +excess for a BUY, -excess for a SELL, 0 for a HOLD; ARIA's mean is {_pp(c['signed_excess']['aria'])}, p(perm) {c['signed_excess']['perm_year']['p']:.3f}.", "",
                  "| call | rows | hit rate [95% CI] | hit rate of the same event for ALL stocks | hit minus base [95% CI] | mean excess [95% CI] | median excess [95% CI] | mean excess minus all-stock mean [95% CI] |\n|---|---|---|---|---|---|---|---|"]
            for k in RECS:
                v = c["per_rating"][k]
                if v.get("suppressed"):
                    L.append(f"| {k} | {v['n_obs']} | suppressed | | | | | |")
                else:
                    L.append(f"| {k} | {v['n_obs']:,} | {_pp(v['hit'])} | {_p(v['hit_base_rate_all_stocks'])} | {_pp(v['hit_minus_base_rate'])} | {_pp(v['mean_excess'])} | {_pp(v['median_excess'])} | {_pp(v['mean_minus_all_stocks'])} |")
            bs = c["buy_minus_sell"]
            L += ["", f"**BUY minus SELL mean excess: {_pp(bs)}, p = {_pv(bs)}.**", ""]
        c = res["by_definition"]["headline"][h]
        if not c.get("suppressed"):
            cl = c["classes"]
            L += ["### Common outcome definition: 3-class confusion (headline excess)", "",
                  f"Realised class: outperform if excess > +{HOLD_BAND[h]:.1%}, underperform if < -{HOLD_BAND[h]:.1%}, else in line. "
                  f"Class shares: {', '.join(f'{n} {_p(s)}' for n, s in zip(cl['labels'], cl['outcome_share']))}.", "",
                  "| ARIA call \\ realised | outperform | in-line | underperform | precision |\n|---|---|---|---|---|"]
            for i, k in enumerate(RECS):
                L.append(f"| {k} | " + " | ".join(f"{v:,}" for v in cl["confusion"][i]) + f" | {_p(cl['precision'][i])} |")
            L += ["| recall | " + " | ".join(_p(x) for x in cl["recall"]) + " | |", "",
                  f"Accuracy {_pp(cl['accuracy'])}; majority-class baseline (always '{cl['majority_class']}') {_p(cl['majority_accuracy'])}; random with ARIA's mix {_p(cl['random_same_mix_accuracy'])}. "
                  f"**Accuracy minus majority baseline: {_pp(cl['accuracy_minus_majority'])}, p = {_pv(cl['accuracy_minus_majority'])}**; p(perm) {cl['perm_year']['p']:.3f}.", ""]
        w = res["why_always_sell"][h]["all"]
        L += ["### Why 'always SELL' scores above 50%", "",
              f"{_p(w['share_underperform'])} of all stock-origins trail the Nifty over {h} months (95% CI {_pp(res['why_always_sell'][h]['sell_hit_ci'])}), because the typical stock does worse than the cap-weighted index: "
              f"median stock total return {_p(w['median_stock_total_return'])} vs median Nifty price return {_p(w['median_nifty_return'])}; median excess {_p(w['median_excess'])} but mean excess "
              f"{_p(w['mean_excess'])} (skew: a few large winners lift the mean, {_p(w['skew_gap_mean_minus_median'])} above the median). The universe is "
              f"{_p(res['controls']['size_mix'].get('small', 0), 0)} small-cap. Share trailing the Nifty by size: "
              + "; ".join(f"{k} {_p(v['share_underperform'])} (n={v['n']:,})" for k, v in res["why_always_sell"][h]["by_size"].items())
              + f". With the TRI proxy (dividends added to the Nifty) the share trailing is {_p(w['share_underperform_tri_proxy'])}. Survivorship works the other way (it lifts stocks), so the true base rate is, if anything, higher.", ""]
    L += ["## Portfolio-style evaluation (12-month horizon, equal weight, rebalanced each origin year)", "",
          "Long every BUY, short every SELL (hypothetical: borrow is unavailable for most Indian cash stocks). Excess legs are versus the Nifty, which cancels in the long-short. "
          "Cost: round-trip bps per unit of book replaced (one-way turnover 0.5 sum|dw|; year 1 counts as a full build). Net CI = gross bootstrap CI shifted by the average cost.", ""]
    for pk, title in (("headline", "headline excess"), ("winsor", "winsorised headline excess"), ("tr_vs_tri", "TRI-proxy excess")):
        pf = res["portfolio"][pk]
        L += [f"### Yearly legs ({title})", "", "| origin FY | BUY n | SELL n | long excess | short leg excess | long-short | turnover long | turnover short |\n|---|---|---|---|---|---|---|---|"]
        L += [f"| {t['year']} | {t['n_buy']} | {t['n_sell']} | {_p(t['long_excess'])} | {_p(t['short_excess'])} | {_p(t['long_short'])} | {_p(t['turnover_long'], 0)} | {_p(t['turnover_short'], 0)} |" for t in pf["years"]]
        L.append("")
        for name, sets in pf.get("strategies", {}).items():
            L += [f"**{name}** ({title}), mean annual return after cost, 95% CI:", "",
                  "| period | gross mean by year | sd | years > 0 | avg turnover | " + " | ".join(f"{c} bps" for c in COSTS_BPS) + " |\n|---|---|---|---|---|" + "---|" * len(COSTS_BPS)]
            for sn, r in sets.items():
                L.append(f"| {sn} | {_p(r['gross_by_year_mean'])} | {_p(r['sd_by_year'])} | {r['positive_years']}/{len(r['years'])} | {_p(r['turnover_avg'], 0)} | " + " | ".join(_pp(r["cost_bps"][c]) for c in COSTS_BPS) + " |")
            L.append("")
    L += ["### Liquidity filters (12 months)", "", "| universe | rows | hit rate | hit minus random [95% CI] | BUY minus SELL [95% CI] | long-short, 0 bps | long-short, 50 bps | winsorised long-short, 0 bps | winsorised, 50 bps |\n|---|---|---|---|---|---|---|---|---|"]
    for name, v in res["liquidity"].items():
        c = v["core_12m"]
        if c.get("suppressed"):
            L.append(f"| {name} | {c['n_obs']} | suppressed | | | | | | |")
            continue
        g = lambda k: v[k].get("strategies", {}).get("long BUY / short SELL", {}).get("all years", {}).get("cost_bps", {})
        L.append(f"| {name} | {c['n_obs']:,} | {_pp(c['hit']['aria'])} | {_pp(c['hit']['paired_vs']['random_same_mix'])} | {_pp(c['buy_minus_sell'])} | {_pp(g('portfolio').get(0))} | {_pp(g('portfolio').get(50))} | {_pp(g('portfolio_w').get(0))} | {_pp(g('portfolio_w').get(50))} |")
    L += ["", f"## Chronological split (FY2018-{SPLIT_YEAR} vs FY{SPLIT_YEAR + 1}-2025)", "",
          "Nothing was calibrated on either half (the rules and bands were fixed beforehand), so this is a stability check across time.", "",
          "| horizon | period | rows | hit rate | hit minus random [95% CI] | p | BUY minus SELL [95% CI] | class accuracy minus majority [95% CI] |\n|---|---|---|---|---|---|---|---|"]
    for h in (3, 6, 12):
        for nm in ("early", "late"):
            c = res["oos"][h][nm]
            if c.get("suppressed"):
                L.append(f"| {h}m | {nm} | {c['n_obs']} | suppressed | | | | |")
                continue
            L.append(f"| {h}m | {nm} | {c['n_obs']:,} | {_pp(c['hit']['aria'])} | {_pp(c['hit']['paired_vs']['random_same_mix'])} | {_pv(c['hit']['paired_vs']['random_same_mix'])} | "
                     f"{_pp(c['buy_minus_sell'])} | {_pp(c['classes']['accuracy_minus_majority'])} |")
    ct = res["controls"]
    L += ["", "## Data controls", "", "**Not controlled:**", ""] + [f"- {x}" for x in res["not_controlled"]]
    L += ["", "**Quantified:**", "",
          f"- Unclassified sector: {_p(ct['share_origins_unclassified_sector'])} of origins ({_p(ct['share_companies_unclassified_sector'])} of companies).",
          f"- Origins flagged structural break: {_p(ct['share_origins_structural_break'])}; short history: {_p(ct['share_origins_short_history'])}; target price withheld: {_p(ct['share_target_withheld'])}.", "",
          "| 12m sensitivity | rows | hit rate | hit minus random [95% CI] | BUY minus SELL [95% CI] |\n|---|---|---|---|---|"]
    for k, c in ct["sensitivity"].items():
        L.append(f"| {k} | {c['n_obs']:,} | {_pp(c['hit']['aria'])} | {_pp(c['hit']['paired_vs']['random_same_mix'])} | {_pp(c['buy_minus_sell'])} |")
    L += ["", "| size bucket (12m) | rows | companies | hit rate | hit minus random [95% CI] | BUY minus SELL [95% CI] |\n|---|---|---|---|---|---|"]
    for k, c in ct["by_size"].items():
        if c.get("suppressed"):
            L.append(f"| {k} | {c['n_obs']} | {c['n_companies']} | suppressed | | |")
        else:
            L.append(f"| {k} | {c['n_obs']:,} | {c['n_companies']:,} | {_pp(c['hit']['aria'])} | {_pp(c['hit']['paired_vs']['random_same_mix'])} | {_pp(c['buy_minus_sell'])} |")
    iv = res.get("interval")
    if iv:
        L += ["", "## Scenario coverage and an empirically calibrated interval", "",
              "The bear and bull cases were not designed as a stated-probability interval; their spread equals ARIA's own Monte Carlo sigma, so they behave like roughly a +-1 sigma "
              "scenario range. 'Scenario coverage' below describes how often the reported figure landed between the cases; it is not a failed 68% calibration. "
              f"To give a usable interval, the log-width of [bear, bull] around base is scaled by a factor s fitted on the early origins to reach {iv['target']:.0%} coverage; coverage is then scored on the later origins.", "",
              iv["rule"] + ". " + iv["split"] + f". {iv['n_dropped_degenerate_cases']:,} observations dropped (bear < base < bull not satisfied).", "",
              "| line | k (yrs) | fit rows | scale s | test rows | scenario coverage as shipped (s=1) [95% CI] | calibrated coverage [95% CI] | single s per line [95% CI] |\n|---|---|---|---|---|---|---|---|"]
        for line, ks in iv["cells"].items():
            for k, c in ks.items():
                sc = f"{c['scale']:.2f}" if "scale" in c else "n/a"
                if "test_calibrated" not in c:
                    L.append(f"| {line} | {k} | {c['n_fit']:,} | {sc} | {c['n_test']:,} | {c.get('note', 'not scored')} | | |")
                else:
                    L.append(f"| {line} | {k} | {c['n_fit']:,} | {sc} | {c['n_test']:,} | {_pp(c['test_uncalibrated'], 0)} | {_pp(c['test_calibrated'], 0)} | {_pp(c.get('test_pooled_scale'), 0)} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
