"""Owner: WP1. Leak-free features and targets.

Every feature at row t is a trailing-window function of data up to and including t.
No fundamentals: Yahoo only serves current/revised statements, not point-in-time, so using them
would leak the future into history. NaNs (warm-up windows, missing bench/sector days) are left for
the model pipelines to handle; there is no global imputation (which would leak across the split).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import FeatureConfig


def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def build_features(px: pd.DataFrame, bench: pd.Series | None, sector: pd.Series | None,
                   cfg: FeatureConfig | None = None) -> pd.DataFrame:
    """index=dates; row t uses data up to and including t only."""
    cfg = cfg or FeatureConfig()
    a = px["adj_close"]
    r = np.log(a).diff()
    f: dict[str, pd.Series] = {}
    for k in cfg.lags:
        f[f"ret_lag{k}"] = np.log(a / a.shift(k))  # k-bar log return ending at t
    for w in cfg.vol_windows:
        f[f"vol_{w}"] = r.rolling(w).std()
    for w in cfg.momentum_windows:
        f[f"mom_{w}"] = np.log(a / a.shift(w))
    for w in cfg.ma_windows:
        f[f"dist_ma{w}"] = a / a.rolling(w).mean() - 1
    f["ma_gap_21"] = np.log(a / a.rolling(21).mean())  # the mean-reversion baseline in models.py reads this column
    f[f"rsi_{cfg.rsi}"] = _rsi(a, cfg.rsi)
    v = px["volume"].astype(float)
    f["vol_z63"] = (v - v.rolling(63).mean()) / v.rolling(63).std().replace(0, np.nan)
    f["zero_volume"] = (v <= 0).astype(float)
    if cfg.use_benchmark and bench is not None:
        b = bench.reindex(px.index).ffill()  # forward fill = past values only
        br = np.log(b).diff()
        for k in (1, 5, 21):
            f[f"bench_ret_{k}"] = np.log(b / b.shift(k))
        f["bench_vol_21"] = br.rolling(21).std()
        f["beta_63"] = r.rolling(63).cov(br) / br.rolling(63).var()
        f["rel_strength_63"] = np.log(a / a.shift(63)) - np.log(b / b.shift(63))
    if cfg.use_sector and sector is not None:
        s = sector.reindex(px.index).ffill()
        f["sector_rel_63"] = np.log(a / a.shift(63)) - np.log(s / s.shift(63))
    return pd.DataFrame(f, index=px.index).replace([np.inf, -np.inf], np.nan)


def targets(px: pd.DataFrame, h: int) -> pd.Series:
    """Forward log return of adj_close over h bars: log(adj[t+h]/adj[t]); NaN at the last h rows."""
    la = np.log(px["adj_close"])
    return (la.shift(-h) - la).rename(f"y_{h}")
