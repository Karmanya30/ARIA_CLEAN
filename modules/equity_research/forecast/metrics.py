"""Owner: WP3. Metrics. `rows` DataFrames have PredictionRow columns. Undefined metrics return None.

Conventions: y/p are forward log returns unless stated. "Up" = strictly positive; a zero actual or a
zero prediction counts as NOT up. Percent metrics (mape, smape) are in percent.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config.paths import DATA_DIR

from .contracts import (BaselineComparison, HorizonModelResult, HorizonResult, MetricBlock,
                        RunResult, TradeSim)


def _a(x) -> np.ndarray:
    return np.asarray(x, dtype=float).ravel()


def _f(x) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


def mae(y, p) -> float | None:
    y, p = _a(y), _a(p)
    return _f(np.mean(np.abs(y - p))) if len(y) else None


def rmse(y, p) -> float | None:
    y, p = _a(y), _a(p)
    return _f(np.sqrt(np.mean((y - p) ** 2))) if len(y) else None


def mape(y, p) -> tuple[float | None, int]:
    """(value in %, n_excluded): actuals with |y| < 1e-8 are excluded."""
    y, p = _a(y), _a(p)
    keep = np.abs(y) >= 1e-8
    if not keep.any():
        return None, int((~keep).sum())
    return _f(100 * np.mean(np.abs((y[keep] - p[keep]) / y[keep]))), int((~keep).sum())


def smape(y, p) -> float | None:
    """100 * mean(2|y-p| / (|y|+|p|)); points with both zero are skipped."""
    y, p = _a(y), _a(p)
    den = np.abs(y) + np.abs(p)
    k = den > 0
    return _f(100 * np.mean(2 * np.abs(y[k] - p[k]) / den[k])) if k.any() else None


def r2(y, p) -> float | None:
    """1 - SSres/SStot around the mean of y; None when y has zero variance."""
    y, p = _a(y), _a(p)
    sst = np.sum((y - y.mean()) ** 2) if len(y) else 0.0
    return None if sst <= 0 else _f(1 - np.sum((y - p) ** 2) / sst)


def confusion(y, p) -> dict[str, int]:
    """Keys tp, fp, tn, fn (up = positive; a zero prediction or zero actual counts as negative)."""
    u, q = _a(y) > 0, _a(p) > 0
    return {"tp": int((u & q).sum()), "fp": int((~u & q).sum()), "tn": int((~u & ~q).sum()), "fn": int((u & ~q).sum())}


def directional(y, p) -> float | None:
    c = confusion(y, p)
    n = sum(c.values())
    return (c["tp"] + c["tn"]) / n if n else None


def balanced_acc(y, p) -> float | None:
    """(recall_up + recall_down)/2; None when either class is absent from y."""
    c = confusion(y, p)
    if c["tp"] + c["fn"] == 0 or c["tn"] + c["fp"] == 0:
        return None
    return (c["tp"] / (c["tp"] + c["fn"]) + c["tn"] / (c["tn"] + c["fp"])) / 2


def prf1(y, p) -> tuple[float | None, float | None, float | None]:
    """(precision, recall, f1) for the up class; undefined parts are None."""
    c = confusion(y, p)
    pr = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
    rc = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
    if pr is None or rc is None:
        return pr, rc, None
    return pr, rc, 0.0 if pr + rc == 0 else 2 * pr * rc / (pr + rc)


def brier(y_up, p_up) -> float | None:
    y, p = _a(y_up), _a(p_up)
    return _f(np.mean((p - y) ** 2)) if len(y) else None


def reliability(y_up, p_up, bins: int = 10) -> tuple[pd.DataFrame, float | None]:
    """(table[bin, n, mean_p, freq], ECE = sum(n_b/N * |freq_b - mean_p_b|)) over equal-width bins on [0,1]."""
    y, p = _a(y_up), _a(p_up)
    if not len(y):
        return pd.DataFrame(columns=["bin", "n", "mean_p", "freq"]), None
    b = np.minimum((p * bins).astype(int), bins - 1)
    rows = [(i, int((b == i).sum()), p[b == i].mean(), y[b == i].mean()) for i in range(bins) if (b == i).any()]
    t = pd.DataFrame(rows, columns=["bin", "n", "mean_p", "freq"])
    return t, _f((t.n / len(y) * (t.freq - t.mean_p).abs()).sum())


def coverage(y, lo, hi) -> float | None:
    y, lo, hi = _a(y), _a(lo), _a(hi)
    return _f(np.mean((y >= lo) & (y <= hi))) if len(y) else None


def width(lo, hi) -> float | None:
    lo, hi = _a(lo), _a(hi)
    return _f(np.mean(hi - lo)) if len(lo) else None


def pinball(y, qpred: dict[float, np.ndarray]) -> float | None:
    """Mean over quantile levels tau of mean(max(tau*(y-q), (tau-1)*(y-q)))."""
    y = _a(y)
    if not qpred or not len(y):
        return None
    losses = []
    for tau, q in qpred.items():
        d = y - _a(q)
        losses.append(np.mean(np.maximum(tau * d, (tau - 1) * d)))
    return _f(np.mean(losses))


def crps_q(y, qpred: dict[float, np.ndarray]) -> float | None:
    """APPROXIMATE CRPS = 2 * mean pinball over the (non-uniform, truncated) quantile grid."""
    v = pinball(y, qpred)
    return None if v is None else 2 * v


def block_bootstrap_ci(err_model, err_base, block: int, n_boot: int = 1000, seed: int = 0,
                       alpha: float = 0.05) -> BaselineComparison:
    """CI of mean|err_model| - mean|err_base| via circular block bootstrap of the paired loss difference.

    Negative = model better. significant = the CI lies entirely below 0 (model significantly better).
    mae_improvement_pct is positive when the model is better.
    """
    em, eb = np.abs(_a(err_model)), np.abs(_a(err_base))
    n = len(em)
    if n == 0 or n != len(eb):
        return BaselineComparison()
    d = em - eb
    block = max(1, min(int(block), n))
    rng = np.random.default_rng(seed)
    nb = -(-n // block)
    starts = rng.integers(0, n, size=(n_boot, nb))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    means = d[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    base = eb.mean()
    return BaselineComparison(mae_improvement_pct=_f(-d.mean() / base * 100) if base > 0 else None,
                              ci_low=float(lo), ci_high=float(hi), significant=bool(hi < 0))


def dm_test(err_model, err_base, h: int) -> tuple[float, float]:
    """One-sided Diebold-Mariano test, H1: the model's absolute error is smaller than the baseline's.

    d_t = |e_model| - |e_base|; stat = mean(d) / sqrt(V / n) with V the Newey-West long-run variance of d
    (Bartlett weights 1 - k/h, lags 1..h-1, because h-step targets overlap). The Harvey-Leybourne-Newbold
    small-sample factor sqrt((n + 1 - 2h + h(h-1)/n) / n) is applied and the stat is referred to Student t
    with n-1 df. Returns (stat, p): stat < 0 means the model is better; p = P(T <= stat). Degenerate input -> (0, 1).
    """
    em, eb = np.abs(_a(err_model)), np.abs(_a(err_base))
    n = len(em)
    h = max(1, int(h))
    if n < 3 or n != len(eb) or n + 1 - 2 * h + h * (h - 1) / n <= 0:
        return 0.0, 1.0
    d = em - eb
    dc = d - d.mean()
    v = float(dc @ dc) / n
    for k in range(1, min(h, n)):
        v += 2 * (1 - k / h) * float(dc[k:] @ dc[:-k]) / n
    if not np.isfinite(v) or v <= 1e-18:
        return 0.0, 1.0
    from scipy import stats

    stat = float(d.mean() / np.sqrt(v / n) * np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n))
    return stat, float(stats.t.cdf(stat, n - 1))


def fdr_bh(pvalues, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg: boolean array, True where the hypothesis is rejected at FDR q.
    NaN p-values are never rejected and do not count towards m."""
    p = np.asarray(pvalues, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    pv = p[ok]
    m = len(pv)
    if m == 0:
        return out
    order = np.argsort(pv)
    passed = pv[order] <= q * np.arange(1, m + 1) / m
    k = np.nonzero(passed)[0]
    rej = np.zeros(m, bool)
    if len(k):
        rej[order[: k.max() + 1]] = True
    out[ok] = rej
    return out


_QCOLS = {0.05: "q05", 0.1: "q10", 0.25: "q25", 0.5: "q50", 0.75: "q75", 0.9: "q90", 0.95: "q95"}


def _qpred(rows: pd.DataFrame) -> dict[float, np.ndarray]:
    return {t: rows[c].to_numpy(float) for t, c in _QCOLS.items() if c in rows and rows[c].notna().all()}


def _p_up(rows: pd.DataFrame, qp: dict[float, np.ndarray]) -> np.ndarray | None:
    """P(return > 0) from the quantile CDF by linear interpolation (flat beyond q05/q95): approximate."""
    if len(qp) < 3:
        return None
    taus = np.array(sorted(qp))
    Q = np.sort(np.column_stack([qp[t] for t in taus]), axis=1)  # sorting repairs quantile crossing
    return np.array([1 - np.interp(0.0, q, taus) for q in Q])


def metric_block(rows: pd.DataFrame, horizon: int | None = None) -> MetricBlock:
    """All metrics from a DataFrame with PredictionRow columns.

    dir/confusion/r2/brier/coverage/pinball are on log returns; mae/rmse/mape/smape are on prices
    price_origin*exp(r). effective_n = n // horizon (overlapping h-bar targets). Brier/ECE use P(up)
    interpolated from the quantiles (None when quantiles are absent).
    """
    n = len(rows)
    if n == 0:
        return MetricBlock()
    h = int(horizon or (rows["horizon"].iloc[0] if "horizon" in rows else 1) or 1)
    y, p = rows["y_true"].to_numpy(float), rows["y_pred"].to_numpy(float)
    po = rows["price_origin"].to_numpy(float)
    py, pp = po * np.exp(y), po * np.exp(p)
    mp, excl = mape(py, pp)
    pr, rc, f1 = prf1(y, p)
    qp = _qpred(rows)
    pu = _p_up(rows, qp)
    ece = reliability(y > 0, pu)[1] if pu is not None else None
    full = {0.05, 0.95} <= set(qp)
    return MetricBlock(
        n=n, effective_n=float(n // h), mae=mae(py, pp), rmse=rmse(py, pp), mae_ret=mae(y, p), rmse_ret=rmse(y, p), mape=mp, smape=smape(py, pp),
        r2=r2(y, p), mape_excluded=excl, dir_acc=directional(y, p), balanced_acc=balanced_acc(y, p),
        precision=pr, recall=rc, f1=f1, confusion=confusion(y, p),
        brier=brier(y > 0, pu) if pu is not None else None, ece=ece,
        coverage_90=coverage(y, qp[0.05], qp[0.95]) if full else None,
        mean_width_90=width(qp[0.05], qp[0.95]) if full else None,
        pinball=pinball(y, qp), crps_approx=crps_q(y, qp))


def trade_sim(rows: pd.DataFrame, open_px: pd.Series, horizon: int = 5, cost_bps: float = 10.0) -> TradeSim:
    """Hypothetical long/flat sim from the predicted sign; always hypothetical=True.

    Forecast made at the close of origin bar t: if y_pred > 0, ENTER at the OPEN of bar t+1 (never the
    origin close), EXIT at the open `horizon` bars later; non-overlapping trades (an origin inside an
    open trade is skipped). cost_bps is charged per side on the entry and exit bars. Daily series
    spans first entry to last exit (flat days = 0). turnover = sides traded per year. Buy-and-hold
    uses the same span, open to open.
    """
    op = open_px.dropna().astype(float)
    pos = {d: i for i, d in enumerate(op.index)}
    o = op.to_numpy()
    c = cost_bps / 1e4
    r = rows.drop_duplicates("origin_date").sort_values("origin_date")
    trades, busy = [], -1
    for d, yp in zip(pd.to_datetime(r["origin_date"]), r["y_pred"]):
        i = pos.get(d)
        if i is None or yp <= 0 or i + 1 <= busy or i + 1 + horizon > len(o) - 1:
            continue
        trades.append((i + 1, i + 1 + horizon))
        busy = i + 1 + horizon
    if not trades:
        return TradeSim(cost_bps=cost_bps, n_trades=0)
    s0, s1 = trades[0][0], trades[-1][1]
    daily = np.zeros(s1 - s0)
    for e, x in trades:
        daily[e - s0:x - s0] = o[e + 1:x + 1] / o[e:x] - 1
        daily[e - s0] -= c
        daily[x - 1 - s0] -= c
    eq = np.cumprod(1 + daily)
    cum = float(eq[-1] - 1)
    nb = len(daily)
    sd = daily.std(ddof=1) if nb > 1 else 0.0
    dd = np.sqrt(np.mean(np.minimum(daily, 0) ** 2))
    return TradeSim(
        cumulative_return=cum, annual_return=_f((1 + cum) ** (252 / nb) - 1), annual_vol=_f(sd * np.sqrt(252)),
        sharpe=_f(daily.mean() / sd * np.sqrt(252)) if sd > 0 else None,
        sortino=_f(daily.mean() / dd * np.sqrt(252)) if dd > 0 else None,
        max_drawdown=float((eq / np.maximum.accumulate(np.maximum(eq, 1)) - 1).min()),
        turnover=2 * len(trades) * 252 / nb, cost_bps=cost_bps,
        benchmark_cumulative_return=float(o[s1] / o[s0] - 1), n_trades=len(trades))


def _stored_run(run_id: str) -> RunResult | None:
    try:
        from . import store
        return store.get_run(run_id)
    except Exception:
        return None


def recompute(run_id: str) -> RunResult:
    """Recompute every metric of a stored run from data/forecast_runs/{run_id}/predictions.parquet.

    Rebuilds validation/test MetricBlocks and vs_baseline (test segment, paired with model 'rw') for every
    horizon/model in the parquet. Regimes and trade_sim need prices (not in the parquet) and are carried
    over from the stored run when it is available; family/status/notes likewise.
    """
    df = pd.read_parquet(Path(DATA_DIR) / "forecast_runs" / run_id / "predictions.parquet")
    run = _stored_run(run_id) or RunResult(run_id=run_id, symbol="")
    old = {(h.horizon, r.model): (h, r) for h in run.horizons for r in h.results + h.baseline_results}
    horizons = []
    for h, dh in df.groupby("horizon"):
        h = int(h)
        res, base = [], []
        rw = dh[(dh.model == "rw") & (dh.segment == "test")].set_index("origin_date")
        for m, dm in dh.groupby("model"):
            prev = old.get((h, m), (None, None))[1]
            r = HorizonModelResult(
                horizon=h, model=m, family=prev.family if prev else ("baseline" if m == "rw" else "unknown"),
                validation=metric_block(dm[dm.segment == "validation"], h),
                test=metric_block(dm[dm.segment == "test"], h),
                regimes=prev.regimes if prev else {}, regime_warnings=prev.regime_warnings if prev else [],
                trade_sim=prev.trade_sim if prev else None)
            t = dm[dm.segment == "test"].drop_duplicates("origin_date").set_index("origin_date")
            common = t.index.intersection(rw.index)
            if m != "rw" and len(common):
                e_m = (t.loc[common, "y_true"] - t.loc[common, "y_pred"]).to_numpy()
                e_b = (rw.loc[common, "y_true"] - rw.loc[common, "y_pred"]).to_numpy()
                r.vs_baseline = block_bootstrap_ci(e_m, e_b, block=h)
            (base if r.family == "baseline" else res).append(r)
        ph = next((x for x in run.horizons if x.horizon == h), None)
        horizons.append(HorizonResult(horizon=h, status=ph.status if ph else "not_run",
                                      selected_model=ph.selected_model if ph else None,
                                      results=res, baseline_results=base, notes=ph.notes if ph else []))
    return run.model_copy(update={"horizons": horizons})
