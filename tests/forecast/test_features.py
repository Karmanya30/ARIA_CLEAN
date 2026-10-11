"""Feature/target tests on SYNTHETIC prices (no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.forecast.features import build_features, targets


def synth(n=700, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    a = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    px = pd.DataFrame({"adj_close": a, "close": a, "open": a, "high": a, "low": a,
                       "volume": rng.integers(0, 1_000_000, n).astype(float)}, index=idx)
    bench = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0, 0.008, n))), index=idx)
    sector = pd.Series(500 * np.exp(np.cumsum(rng.normal(0, 0.009, n))), index=idx)
    return px, bench, sector


def test_columns_and_basic_values():
    px, b, s = synth()
    f = build_features(px, b, s)
    assert {"ret_lag1", "vol_63", "mom_252", "dist_ma200", "rsi_14", "vol_z63", "zero_volume",
            "bench_ret_21", "bench_vol_21", "beta_63", "rel_strength_63", "sector_rel_63"} <= set(f)
    assert np.allclose(f["ret_lag1"].iloc[1:], np.log(px.adj_close).diff().iloc[1:])
    assert f["rsi_14"].dropna().between(0, 100).all()
    assert "bench_ret_1" not in build_features(px, None, None) and "sector_rel_63" not in build_features(px, b, None)


def test_no_leakage_truncation_and_poison():
    px, b, s = synth()
    full = build_features(px, b, s)
    t = 400
    cut = build_features(px.iloc[:t], b.iloc[:t], s.iloc[:t])
    pd.testing.assert_frame_equal(full.iloc[:t], cut, rtol=1e-8, atol=1e-10)  # every column
    p2, b2, s2 = px.copy(), b.copy(), s.copy()
    for d in (p2, b2, s2):
        d.iloc[t:] = d.iloc[t:] * np.random.default_rng(3).uniform(0.2, 5, (len(d) - t,) + d.shape[1:]) \
            if d.ndim == 2 else d.iloc[t:] * np.random.default_rng(3).uniform(0.2, 5, len(d) - t)
    poisoned = build_features(p2, b2, s2)
    pd.testing.assert_frame_equal(full.iloc[:t], poisoned.iloc[:t], rtol=1e-8, atol=1e-10)


def test_targets_alignment():
    px = pd.DataFrame({"adj_close": [100, 110, 121, 133.1, 146.41]}, index=pd.bdate_range("2024-01-01", periods=5))
    y = targets(px, 2)
    assert np.allclose(y.iloc[:3], np.log(1.21))  # log(adj[t+2]/adj[t])
    assert y.iloc[3:].isna().all() and len(y) == 5
    px2, _, _ = synth()
    y5 = targets(px2, 5)
    assert y5.iloc[10] == pytest.approx(np.log(px2.adj_close.iloc[15] / px2.adj_close.iloc[10]))
