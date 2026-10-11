"""Regime tests on SYNTHETIC prices."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.equity_research.forecast.regimes import label_regimes, regime_metrics
from tests.forecast.test_features import synth


def _px(logp):
    idx = pd.bdate_range("2018-01-01", periods=len(logp))
    return pd.DataFrame({"adj_close": np.exp(logp)}, index=idx)


def test_label_sets_and_warmup():
    px, b, _ = synth()
    lab = label_regimes(px, b)
    assert set(lab.bull_bear.dropna()) <= {"bull", "bear"} and set(lab.vol.dropna()) <= {"high", "low"}
    assert set(lab.trend.dropna()) <= {"trending", "sideways"}
    assert lab.bull_bear.iloc[:199].isna().all() and lab.bull_bear.iloc[199:].notna().all()
    assert label_regimes(px, None).bull_bear.notna().sum() > 0  # stock used when no bench


def test_trend_detection():
    t = np.arange(400)
    noise = np.random.default_rng(0).normal(0, 1e-4, 400)
    assert (label_regimes(_px(0.002 * t + noise), None).trend.dropna() == "trending").all()
    flat = label_regimes(_px(0.01 * (-1.0) ** t + noise), None).trend.dropna()
    assert (flat == "sideways").all()  # oscillating around a constant: no slope


def test_bull_bear():
    up = label_regimes(_px(0.001 * np.arange(300)), None)
    down = label_regimes(_px(-0.001 * np.arange(300)), None)
    assert (up.bull_bear.dropna() == "bull").all() and (down.bull_bear.dropna() == "bear").all()


def test_only_past_data_poison():
    px, b, _ = synth()
    full = label_regimes(px, b)
    t = 450
    p2, b2 = px.copy(), b.copy()
    p2.iloc[t:] *= 7.0
    b2.iloc[t:] *= 0.1
    pd.testing.assert_frame_equal(full.iloc[:t], label_regimes(p2, b2).iloc[:t])
    pd.testing.assert_frame_equal(full.iloc[:t], label_regimes(px.iloc[:t], b.iloc[:t]))


def test_regime_metrics_keys_and_small_n_warning():
    px, b, _ = synth()
    lab = label_regimes(px, b)
    ds = px.index[300:340]
    rows = pd.DataFrame({"origin_date": ds.strftime("%Y-%m-%d"), "horizon": 5, "y_true": 0.01,
                         "y_pred": 0.005, "price_origin": 100.0})
    out, warns = regime_metrics(rows, lab, 5)
    assert all(":" in k for k in out) and any(k.startswith("bull_bear:") for k in out)
    assert sum(v.n for k, v in out.items() if k.startswith("trend:")) == 40
    assert warns and all("effective_n" in w for w in warns)  # 40 rows // 5 = 8 < 30
