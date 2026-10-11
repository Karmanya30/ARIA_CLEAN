"""Owner: WP1. Regime labels."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import MetricBlock


def _slope_t(logp: pd.Series, w: int = 63) -> pd.Series:
    """t-stat of the OLS slope of log price on time over the trailing w bars (closed form, vectorised)."""
    x = np.arange(w) - (w - 1) / 2
    sxx = (x ** 2).sum()
    y = logp.rolling(w)
    slope = logp.rolling(w).apply(lambda v: (x * v).sum() / sxx, raw=True)
    resid_var = (y.var() * (w - 1) - slope ** 2 * sxx) / (w - 2)
    return slope / np.sqrt(resid_var.clip(lower=1e-18) / sxx)


def label_regimes(px: pd.DataFrame, bench: pd.Series | None) -> pd.DataFrame:
    """Columns bull_bear, vol, trend: one string label per date, computed from past data only.

    bull_bear: reference (bench, else stock) above/below its 200-bar MA; vol: 63-bar realised vol vs
    its expanding median; trend: |t-stat| of the 63-bar log-price slope > 2. Undefined warm-up rows are NaN.
    """
    a = px["adj_close"]
    ref = a if bench is None else bench.reindex(px.index).ffill()
    ma = ref.rolling(200).mean()
    bb = pd.Series(np.where(ref > ma, "bull", "bear"), index=px.index).where(ma.notna())
    rv = np.log(a).diff().rolling(63).std()
    vol = pd.Series(np.where(rv > rv.expanding().median(), "high", "low"), index=px.index).where(rv.notna())
    t = _slope_t(np.log(a))
    trend = pd.Series(np.where(t.abs() > 2, "trending", "sideways"), index=px.index).where(t.notna())
    return pd.DataFrame({"bull_bear": bb, "vol": vol, "trend": trend})


def regime_metrics(rows: pd.DataFrame, labels: pd.DataFrame, horizon: int,
                   min_eff_n: int = 30) -> tuple[dict[str, MetricBlock], list[str]]:
    """MetricBlock per '<dimension>:<label>' keyed by each row's origin_date; plus warnings when effective_n < 30."""
    from .metrics import metric_block

    out: dict[str, MetricBlock] = {}
    warns: list[str] = []
    lab = labels.copy()
    lab.index = pd.to_datetime(lab.index)
    origin = pd.to_datetime(rows["origin_date"])
    for dim in labels.columns:
        tag = pd.Series(lab[dim].reindex(origin).to_numpy(), index=rows.index)
        for val in sorted(tag.dropna().unique()):
            sub = rows[tag == val]
            mb = metric_block(sub, horizon)
            out[f"{dim}:{val}"] = mb
            if mb.effective_n < min_eff_n:
                warns.append(f"{dim}:{val} effective_n={mb.effective_n:.0f} < {min_eff_n}: metrics unreliable")
    return out, warns
