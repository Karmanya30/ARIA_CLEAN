"""WP2 walk-forward tests on SYNTHETIC series."""
from __future__ import annotations

import numpy as np
import pytest

from modules.equity_research.forecast import models
from modules.equity_research.forecast.backtest import walk_forward
from modules.equity_research.forecast.contracts import EMBARGO, QUANTILES

from .test_models import synth_features, synth_returns

SEG = (252, 252)


@pytest.fixture(scope="module")
def data():
    return synth_features(synth_returns(1700), h=5)


def test_rows_contract_and_origins_identical(data):
    X, y, px = data
    ma, mb = {}, {}
    a = walk_forward(X, y, 5, "ridge", None, segments=SEG, px=px, meta=ma)
    b = walk_forward(X, y, 5, "rw", None, segments=SEG, meta=mb)
    assert [r.origin_date for r in a] == [r.origin_date for r in b] and len(a) == 504
    assert [r.segment for r in a].count("test") == 252 and a[0].segment == "validation"
    r = a[0]
    assert r.oos and r.created_at and r.model_version == models.ZOO["ridge"].version and r.price_origin > 0
    assert r.target_date > r.origin_date
    q = [r.q05, r.q10, r.q25, r.q50, r.q75, r.q90, r.q95]
    assert q == sorted(q) and len(q) == len(QUANTILES)
    assert ma["partial"] is False and mb["folds"][0]["fold"] == 0


def test_refit_cadence_purge_and_tuning(data):
    X, y, _ = data
    meta = {}
    walk_forward(X, y, 5, "ridge", None, segments=SEG, meta=meta)
    f = meta["folds"]
    assert len(f) == 8  # 504 origins / 63
    assert [x["tuned"] for x in f] == [True, False, False, False, True, False, False, False]
    for x in f:
        assert x["train_last_target_pos"] <= x["test_start_pos"] - 1 - EMBARGO
        assert x["core_last_target_pos"] < x["inner_first_pos"]  # tuning/calibration fit never sees the inner slice
        assert x["inner_last_target_pos"] <= x["test_start_pos"] - 1 - EMBARGO
        assert x["train_n"] >= 756


def test_time_cap_drops_incomplete_model(data):
    X, y, _ = data
    meta = {}
    rows = walk_forward(X, y, 5, "ridge", None, segments=SEG, max_seconds=0.0, meta=meta)
    assert rows == [] and meta["partial"] and meta["reason"] == "timeout: incomplete evaluation"


def test_too_short_history_is_reported_not_raised(data):
    X, y, _ = data
    meta = {}
    assert walk_forward(X.iloc[:500], y.iloc[:500], 5, "rw", None, meta=meta) == [] and meta["reason"] == "too_few_bars"
    assert walk_forward(X, y, 5, "lstm", None, segments=SEG, meta=meta) == [] and meta["reason"] == "too_few_bars"


def test_coverage_of_conformal_interval_is_reasonable(data):
    X, y, _ = data
    rows = walk_forward(X, y, 5, "rw", None, segments=SEG)
    hit = np.mean([r.q05 <= r.y_true <= r.q95 for r in rows])
    assert 0.8 < hit < 0.98  # nominal 0.90 (overlapping 5-bar targets, finite samples)


def test_dl_only_runs_at_horizons_5_21_63(data):
    X, y, _ = data
    for h in (1, 126):
        meta = {}
        assert walk_forward(X, y, h, "lstm", None, segments=SEG, meta=meta) == [] and "not run" in meta["reason"]
    assert models.horizon_ok("gru", 21) and not models.horizon_ok("gru", 1) and models.horizon_ok("ridge", 1)
