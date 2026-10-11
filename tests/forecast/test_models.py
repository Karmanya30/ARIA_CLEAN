"""WP2 model-zoo tests. All data is SYNTHETIC (simulated returns), never real prices."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.forecast import models
from modules.equity_research.forecast.contracts import MIN_BARS_DL


def synth_returns(n, seed=7, phi=0.0, sigma=0.01):
    """SYNTHETIC AR(phi) daily log returns on business days."""
    rng = np.random.default_rng(seed)
    e, r = rng.normal(0, sigma, n), np.zeros(n)
    for t in range(1, n):
        r[t] = phi * r[t - 1] + e[t]
    return pd.Series(r, index=pd.bdate_range("2005-01-03", periods=n))


def synth_features(r: pd.Series, h: int = 1):
    """SYNTHETIC features from a return series (causal: row t uses r up to t). Returns X, y, px."""
    px = np.exp(r.cumsum()) * 100
    lp = np.log(px)
    X = pd.DataFrame({f"lag_{k}": r.shift(k - 1) for k in range(1, 11)})
    for w in (5, 21, 63):
        X[f"vol_{w}"] = r.rolling(w).std()
        X[f"mom_{w}"] = r.rolling(w).sum()
    X["ma_gap_21"] = lp - np.log(px.rolling(21).mean())
    y = lp.shift(-h) - lp
    ok = X.notna().all(axis=1)
    return X[ok], y[ok], px[ok]


@pytest.fixture(scope="module")
def data():
    return synth_features(synth_returns(1500))


def test_zoo_contents_and_ranks():
    z = models.ZOO
    assert {"rw", "hist_mean", "drift", "ma", "ar", "garch", "ridge", "rf", "xgb", "lgbm", "lstm", "gru"} <= set(z) | set(models.SKIPPED)
    assert {z[k].complexity_rank for k in ("rw", "hist_mean", "drift", "ma")} == {0}
    assert z["ar"].complexity_rank < z["ridge"].complexity_rank < z["rf"].complexity_rank < z["xgb"].complexity_rank < z["lstm"].complexity_rank
    assert "lstm" not in models.available(2000) and "lstm" in models.available(MIN_BARS_DL)
    assert "rw" in models.available(2000)


@pytest.mark.parametrize("name", [k for k in models.ZOO if k not in ("lstm", "gru")])
def test_fit_predict_shape_finite(name, data):
    X, y, _ = data
    f = models.fit(name, X.iloc[:800], y.iloc[:800], 1, None, {"n_estimators": 30} if name in ("rf", "xgb", "lgbm") else None)
    p = models.predict(f, X.iloc[800:900])
    assert p.shape == (100,) and np.isfinite(p).all()


def test_rw_is_zero_and_baselines(data):
    X, y, _ = data
    assert not models.predict(models.fit("rw", X, y, 0, None), X).any()
    assert models.predict(models.fit("hist_mean", X, y, 0, None), X)[0] == pytest.approx(y.mean())
    assert models.predict(models.fit("drift", X, y, 0, None), X)[0] == pytest.approx(y.iloc[-252:].mean())
    assert np.allclose(models.predict(models.fit("ma", X, y, 0, None), X), -X["ma_gap_21"])


@pytest.mark.parametrize("name", ["ridge", "rf"])
def test_scaler_fitted_on_training_rows_only(name, data):
    X, y, _ = data
    Xtr = X.iloc[:700]
    f = models.fit(name, Xtr, y.iloc[:700], 0, None, {"n_estimators": 20})
    sc = f.state.named_steps["scaler"]
    assert np.allclose(sc.mean_, Xtr.mean().to_numpy())
    models.predict(f, X.iloc[700:])  # predicting never refits
    assert np.allclose(sc.mean_, Xtr.mean().to_numpy())
    assert f.state.named_steps["topk"].keep_.size == min(20, 700 // 50, X.shape[1])


def test_garch_recovers_parameters():
    rng = np.random.default_rng(3)
    w, a, b, n = 2e-6, 0.08, 0.90, 8000  # SYNTHETIC GARCH(1,1)
    r, s2 = np.zeros(n), w / (1 - a - b)
    for t in range(n):
        r[t] = np.sqrt(s2) * rng.standard_normal()
        s2 = w + a * r[t] ** 2 + b * s2
    g = models.garch_fit(r)
    assert abs(g["alpha"] - a) < 0.04 and abs(g["beta"] - b) < 0.05
    assert abs(g["alpha"] + g["beta"] - (a + b)) < 0.03
    assert abs(g["omega"] / (1 - g["alpha"] - g["beta"]) / (w / (1 - a - b)) - 1) < 0.35
    X = pd.DataFrame({"lag_1": r})
    v = models.garch_vol_forecast(models.fit("garch", X, pd.Series(r), 0, None), 21)
    assert 0.5 * 0.01 * np.sqrt(21) < v < 2 * 0.01 * np.sqrt(21)


def test_ar_selects_order_on_ar1():
    X, y, _ = synth_features(synth_returns(3000, phi=0.3))
    st = models.fit("ar", X, y, 0, None).state
    assert st["order"] >= 1 and st["b"][1] == pytest.approx(0.3, abs=0.07)


def test_same_seed_identical_and_lgbm_guard(data):
    X, y, _ = data
    for name in [k for k in ("ridge", "rf", "xgb", "lgbm") if k in models.ZOO]:
        a = models.predict(models.fit(name, X.iloc[:800], y.iloc[:800], 5, None, {"n_estimators": 30}), X.iloc[800:])
        b = models.predict(models.fit(name, X.iloc[:800], y.iloc[:800], 5, None, {"n_estimators": 30}), X.iloc[800:])
        assert np.allclose(a, b, rtol=0, atol=1e-12)  # rf parallel summation order differs at ~1e-18
    assert "lgbm" in models.ZOO or "lgbm" in models.SKIPPED


@pytest.mark.slow
@pytest.mark.parametrize("name", ["lstm", "gru"])
def test_dl_fit_time_and_determinism(name):
    import time
    X, y, _ = synth_features(synth_returns(2600))
    t = time.time()
    p = {"epochs": 3}
    a = models.predict(models.fit(name, X.iloc[:1800], y.iloc[:1800], 2, None, p), X.iloc[1800:1900])
    assert time.time() - t < 120 and a.shape == (100,) and np.isfinite(a).all()
    b = models.predict(models.fit(name, X.iloc[:1800], y.iloc[:1800], 2, None, p), X.iloc[1800:1900])
    assert np.allclose(a, b, atol=1e-6)


def test_zoo_for_modes():
    light, full, dl = models.zoo_for("light"), models.zoo_for("full"), models.zoo_for("full_dl")
    assert set(light) <= set(models.LIGHT_ZOO) and "rw" in light and "lstm" not in full and {"lstm", "gru"} <= set(dl)
    assert set(light) < set(full) < set(dl)
    with pytest.raises(ValueError):
        models.zoo_for("x")
