"""WP3 metric tests. Every expected number is hand-computed in the comment above it."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.forecast import metrics as m


def test_point_errors():
    y, p = [1, 2, 3, 4], [1, 3, 2, 6]  # errors 0,1,-1,2
    assert m.mae(y, p) == pytest.approx(1.0)  # (0+1+1+2)/4
    assert m.rmse(y, p) == pytest.approx(np.sqrt(1.5))  # (0+1+1+4)/4
    v, ex = m.mape(y, p)  # |e|/|y| = 0, .5, 1/3, .5 -> mean 1/3 -> 33.33%
    assert v == pytest.approx(100 / 3) and ex == 0
    assert m.smape(y, p) == pytest.approx(30.0)  # 2|e|/(|y|+|p|) = 0, .4, .4, .4 -> .3
    assert m.r2(y, p) == pytest.approx(-0.2)  # sst=5, ssres=6 -> 1-1.2


def test_mape_near_zero_excluded():
    v, ex = m.mape([0.0, 1.0], [1.0, 2.0])  # first excluded; |1-2|/1 = 100%
    assert v == pytest.approx(100.0) and ex == 1
    assert m.mape([0.0, 1e-10], [1.0, 1.0]) == (None, 2)


def test_r2_zero_variance_is_none():
    assert m.r2([1, 1, 1], [1, 2, 3]) is None


def test_classification():
    y, p = [1, -1, 2, -2, 0], [1, 1, -1, -1, 0]
    # up(y)=T,F,T,F,F ; up(p)=T,T,F,F,F (zero prediction/actual = negative): tp1 fp1 fn1 tn2
    assert m.confusion(y, p) == {"tp": 1, "fp": 1, "tn": 2, "fn": 1}
    assert m.directional(y, p) == pytest.approx(0.6)  # 3/5
    assert m.balanced_acc(y, p) == pytest.approx((0.5 + 2 / 3) / 2)
    assert m.prf1(y, p) == pytest.approx((0.5, 0.5, 0.5))
    assert m.balanced_acc([1, 2], [1, 1]) is None  # no down class
    assert m.prf1([1, -1], [-1, -1]) == (None, 0.0, None)  # no predicted ups


def test_probability_metrics():
    assert m.brier([1, 0, 1, 0], [.9, .2, .6, .5]) == pytest.approx(0.115)  # (.01+.04+.16+.25)/4
    t, ece = m.reliability([0, 1, 1, 1], [.1, .2, .8, .9], bins=2)
    # bin0: mean_p .15 freq .5 ; bin1: mean_p .85 freq 1 ; ece = .5*.35 + .5*.15
    assert ece == pytest.approx(0.25) and list(t.n) == [2, 2]


def test_interval_and_quantile_losses():
    assert m.coverage([0, 1, 2, 3], [0] * 4, [1] * 4) == 0.5
    assert m.width([0, 1], [2, 4]) == pytest.approx(2.5)  # (2+3)/2
    y = [1, 2]
    # tau .5, q=[0,2]: d=[1,0] -> [.5,0] mean .25 ; tau .9, q=[2,2]: d=[-1,0] -> [.1,0] mean .05
    qp = {0.5: np.array([0, 2.0]), 0.9: np.array([2.0, 2.0])}
    assert m.pinball(y, qp) == pytest.approx(0.15)
    assert m.crps_q(y, qp) == pytest.approx(0.30)  # 2 x mean pinball (approximate)


def test_bootstrap_reproducible_and_contains_true_difference():
    rng = np.random.default_rng(1)
    em, eb = rng.normal(0, 0.5, 2000), rng.normal(0, 1.0, 2000)  # SYNTHETIC errors
    true_diff = (0.5 - 1.0) * np.sqrt(2 / np.pi)  # E|N(0,s)| = s*sqrt(2/pi)
    a = m.block_bootstrap_ci(em, eb, block=5, seed=7)
    b = m.block_bootstrap_ci(em, eb, block=5, seed=7)
    assert a == b
    assert a.ci_low < true_diff < a.ci_high and a.significant and a.mae_improvement_pct > 0
    assert m.block_bootstrap_ci(em, eb, block=5, seed=8) != a
    same = m.block_bootstrap_ci(em, em, block=5)  # identical errors: zero difference, not significant
    assert same.ci_low == same.ci_high == 0 and not same.significant


def _rows(n=10, h=1):
    d = pd.bdate_range("2024-01-01", periods=n)
    y = np.linspace(-0.02, 0.03, n)
    return pd.DataFrame({"origin_date": d.strftime("%Y-%m-%d"), "horizon": h, "y_true": y,
                         "y_pred": y * 0.5, "price_origin": 100.0,
                         **{c: y * 0.5 + s for c, s in [("q05", -.05), ("q10", -.03), ("q25", -.01),
                            ("q50", 0.0), ("q75", .01), ("q90", .03), ("q95", .05)]}})


def test_metric_block_prices_and_effective_n():
    r = pd.DataFrame({"horizon": 1, "y_true": [0.1, -0.1], "y_pred": [0.1, 0.0], "price_origin": 100.0})
    b = m.metric_block(r)
    # prices: actual 100e^.1, 100e^-.1 ; predicted 100e^.1, 100 -> mae = (0 + |100e^-.1 - 100|)/2
    assert b.mae == pytest.approx(abs(100 * np.exp(-0.1) - 100) / 2)
    assert b.dir_acc == 1.0 and b.n == 2 and b.coverage_90 is None and b.brier is None
    assert m.metric_block(_rows(10, h=5)).effective_n == 2  # 10 // 5
    full = m.metric_block(_rows())
    assert full.coverage_90 == 1.0 and full.mean_width_90 == pytest.approx(0.10)
    assert 0 <= full.brier <= 1 and full.pinball > 0 and full.crps_approx == pytest.approx(2 * full.pinball)
    assert m.metric_block(_rows().iloc[:0]) == m.MetricBlock()


def _sim_rows(origins, preds, h=1):
    return pd.DataFrame({"origin_date": [str(pd.Timestamp(o).date()) for o in origins], "y_pred": preds, "horizon": h})


def test_trade_sim_hand_example_no_cost():
    idx = pd.bdate_range("2024-01-01", periods=5)
    opens = pd.Series([100, 100, 100, 110, 121.0], index=idx)
    # origin idx0, h=2: enter open[1]=100, exit open[3]=110 -> +10%; bench same span 110/100-1
    s = m.trade_sim(_sim_rows([idx[0]], [0.01]), opens, horizon=2, cost_bps=0)
    assert s.hypothetical and s.n_trades == 1
    assert s.cumulative_return == pytest.approx(0.10) and s.benchmark_cumulative_return == pytest.approx(0.10)
    assert m.trade_sim(_sim_rows([idx[0]], [-0.01]), opens, horizon=2).n_trades == 0  # flat


def test_trade_sim_enters_at_next_open_not_same_close():
    idx = pd.bdate_range("2024-01-01", periods=8)
    # the whole 10% jump happens overnight into bar 2: same-close entry (price 100) would "earn" it,
    # next-open entry buys at 110 and earns nothing (minus 2 x 10 bps cost).
    opens = pd.Series([100, 100, 110, 110, 110, 110, 110, 110.0], index=idx)
    s = m.trade_sim(_sim_rows([idx[1]], [0.01]), opens, horizon=2, cost_bps=10)
    assert s.cumulative_return == pytest.approx(0.999 ** 2 - 1) and s.cumulative_return < 0


def test_trade_sim_no_overlap_and_costs_and_stats():
    idx = pd.bdate_range("2024-01-01", periods=12)
    opens = pd.Series(100 * 1.01 ** np.arange(12), index=idx)  # SYNTHETIC steady 1% per bar
    r = _sim_rows(idx[:6], [1.0] * 6)  # h=3: trades enter bars 1 and 5 (origins 0 and 4); 1,2,3 skipped
    s = m.trade_sim(r, opens, horizon=3, cost_bps=0)
    assert s.n_trades == 2 and s.max_drawdown == 0 and s.sortino is None  # no down days
    assert s.cumulative_return == pytest.approx(1.01 ** 6 - 1)  # two 3-bar holds (1->4, 5->8), flat bar 4->5
    assert m.trade_sim(r, opens, horizon=3, cost_bps=50).cumulative_return < s.cumulative_return


def test_recompute_from_parquet(tmp_path, monkeypatch):
    rows = []
    for model, shift in (("rw", 0.0), ("ridge", 0.0)):
        for i, d in enumerate(pd.bdate_range("2024-01-01", periods=40)):
            y = 0.01 * np.sin(i)
            rows.append(dict(origin_date=str(d.date()), target_date=str(d.date()), horizon=5, model=model,
                             fold=0, segment="test", y_true=y, y_pred=0.0 if model == "rw" else y * 0.5,
                             price_origin=100.0))
    run = tmp_path / "forecast_runs" / "r1"
    run.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(run / "predictions.parquet")
    monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m, "_stored_run", lambda _id: None)
    out = m.recompute("r1")
    h = out.horizons[0]
    assert h.horizon == 5 and [r.model for r in h.results] == ["ridge"] and [r.model for r in h.baseline_results] == ["rw"]
    ridge = h.results[0]
    assert ridge.test == m.metric_block(pd.DataFrame(rows).query("model == 'ridge'"), 5)
    assert ridge.vs_baseline.mae_improvement_pct > 0  # ridge errors are half the size of rw's
