"""Leakage / honesty tests for every model in the zoo, on SYNTHETIC series only."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.forecast import models
from modules.equity_research.forecast.backtest import walk_forward
from modules.equity_research.forecast.contracts import EMBARGO
from modules.equity_research.forecast.selection import select, validation_result

from .test_models import synth_features, synth_returns

SEG = (252, 252)
ALL = list(models.ZOO)
FAST = {"n_estimators": 30}
PARAMS = {"rf": FAST, "xgb": FAST, "lgbm": FAST, "lstm": {"epochs": 2}, "gru": {"epochs": 2}}


def n_for(name):
    return 2600 if models.ZOO[name].family == "dl" else 1500


@lru_cache(maxsize=None)
def series(name, poison_from=None):
    r = synth_returns(n_for(name), seed=11)
    if poison_from is not None:  # replace every return (hence every price) after this raw position by garbage
        r = r.copy()
        r.iloc[poison_from + 1:] = np.random.default_rng(99).normal(0, 0.5, len(r) - poison_from - 1)
    return synth_features(r, h=5)


@lru_cache(maxsize=None)
def run(name, poison_from=None):
    X, y, px = series(name, poison_from)
    meta = {}
    return walk_forward(X, y, 5, name, None, segments=SEG, px=px, params=PARAMS.get(name), meta=meta), meta


@pytest.mark.parametrize("name", ALL)
def test_poisoning_future_prices_does_not_change_past_predictions(name):
    X, _, _ = series(name)
    t = len(X) - 252 + 100  # a position inside the test segment
    cut = X.index[t].strftime("%Y-%m-%d")
    clean, _ = run(name)
    pois, _ = run(name, synth_returns(n_for(name)).index.get_loc(X.index[t]))
    a = {r.origin_date: r.y_pred for r in clean if r.origin_date <= cut}
    b = {r.origin_date: r.y_pred for r in pois if r.origin_date <= cut}
    assert len(a) > 50 and a.keys() == b.keys()
    assert np.allclose([a[k] for k in a], [b[k] for k in a], rtol=0, atol=1e-10)


@pytest.mark.parametrize("name", ALL)
def test_training_targets_end_before_forecast_period(name):
    rows, meta = run(name)
    assert rows and meta["folds"]
    for f in meta["folds"]:
        assert f["train_last_target_pos"] <= f["test_start_pos"] - 1 - EMBARGO
        assert f["train_last_target_date"] <= f["test_start"]


@pytest.mark.parametrize("name", [k for k in ("ridge", "rf", "xgb", "lgbm") if k in models.ZOO])
def test_fitted_scaler_equals_training_rows_mean(name):
    X, y, _ = series(name)
    _, meta = run(name)
    for f in meta["folds"]:
        pos = np.arange(f["train_first_pos"], f["train_last_pos"] + 1)
        pos = pos[np.isfinite(y.to_numpy()[pos])]
        assert len(pos) == f["train_n"]
        assert np.allclose(f["scaler_mean"], X.iloc[pos].mean().to_numpy())


def test_random_walk_nothing_beats_rw():
    X, y, _ = synth_features(synth_returns(2600, seed=7), h=1)  # SYNTHETIC zero-drift random walk
    base = walk_forward(X, y, 1, "rw", None, segments=(504, 504))
    cands = []
    for n in [k for k in models.ZOO if models.ZOO[k].family != "dl" and k != "rw"]:
        rows = walk_forward(X, y, 1, n, None, segments=(504, 504), params=PARAMS.get(n))
        cands.append(validation_result(rows, base, models.ZOO[n].family))
    sel, status = select(cands, validation_result(base, base, "baseline"))
    assert status in ("no_model_beats_baseline", "insufficient_evidence"), (sel, [(c.model, c.vs_baseline.ci_high) for c in cands])


@pytest.mark.parametrize("name", ["ridge", "rf"])
def test_shuffled_targets_direction_ci_contains_half(name):
    X, y, _ = synth_features(synth_returns(2000, seed=21), h=1)
    ys = y.copy()
    ok = ys.notna().to_numpy()  # keep the trailing NaN targets in place, shuffle the rest
    ys[ok] = np.random.default_rng(5).permutation(y.to_numpy()[ok])
    rows = walk_forward(X, ys, 1, name, None, segments=(504, 504), params=PARAMS.get(name))
    hit = np.array([np.sign(r.y_pred) == np.sign(r.y_true) for r in rows], float)
    se = np.sqrt(0.25 / len(hit))  # binomial CI around observed accuracy
    assert hit.mean() - 1.96 * se <= 0.5 <= hit.mean() + 1.96 * se


def test_ar1_signal_is_recovered_out_of_sample():
    X, y, _ = synth_features(synth_returns(2300, seed=4, phi=0.3), h=1)

    def mae(m):
        rows = walk_forward(X, y, 1, m, None, segments=(252, 504))
        return np.mean([abs(r.y_true - r.y_pred) for r in rows if r.segment == "test"])

    assert min(mae("ar"), mae("ridge")) < mae("rw")


@pytest.mark.parametrize("name", [k for k in ("ridge", "rf", "xgb", "lgbm") if k in models.ZOO])
def test_same_seed_same_walk_forward_predictions(name):
    X, y, _ = series(name)
    a = walk_forward(X, y, 5, name, None, segments=SEG, seed=3, params=PARAMS.get(name))
    b = walk_forward(X, y, 5, name, None, segments=SEG, seed=3, params=PARAMS.get(name))
    assert np.allclose([r.y_pred for r in a], [r.y_pred for r in b], rtol=0, atol=1e-12)


@pytest.mark.slow
@pytest.mark.parametrize("name", ["lstm", "gru"])
def test_dl_runs_on_2600_bars_within_cap(name):
    import time
    t = time.time()
    rows, meta = run(name)
    assert len(rows) == 252 * 2 and not meta["partial"]
    assert time.time() - t < 300
