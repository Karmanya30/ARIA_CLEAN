"""WP2 selection tests (hand-built results; no model fitting)."""
from __future__ import annotations

from modules.equity_research.forecast.contracts import BaselineComparison, HorizonModelResult, MetricBlock
from modules.equity_research.forecast.selection import select


def mk(model, lo, hi, imp=5.0, n_eff=100.0, n=100, test_mae=1.0):
    return HorizonModelResult(horizon=1, model=model, family="x", validation=MetricBlock(n=n, effective_n=n_eff, mae=1.0),
                              test=MetricBlock(n=50, mae=test_mae),
                              vs_baseline=BaselineComparison(ci_low=lo, ci_high=hi, mae_improvement_pct=imp, significant=hi < 0))


BASE = HorizonModelResult(horizon=1, model="rw", family="baseline", validation=MetricBlock(n=100, effective_n=100, mae=1.0))


def test_winner_requires_ci_upper_below_zero():
    assert select([mk("ridge", -0.2, 0.01)], BASE) == (None, "no_model_beats_baseline")
    assert select([mk("ridge", -0.2, -0.01)], BASE) == ("ridge", "ok_beats_baseline")


def test_prefers_simpler_on_overlapping_cis():
    sel = select([mk("rf", -0.30, -0.05, imp=9.0), mk("ridge", -0.25, -0.02, imp=7.0), mk("lstm", -0.4, -0.1, imp=10.0)], BASE)
    assert sel == ("ridge", "ok_beats_baseline")  # all three overlap -> lowest complexity_rank


def test_prefers_simpler_on_exact_tie():
    assert select([mk("rf", -0.2, -0.1), mk("ridge", -0.2, -0.1)], BASE)[0] == "ridge"


def test_non_overlapping_better_complex_model_wins():
    sel = select([mk("rf", -0.9, -0.5, imp=40.0), mk("ridge", -0.2, -0.05, imp=5.0)], BASE)
    assert sel[0] == "rf"


def test_insufficient_effective_n():
    assert select([mk("ridge", -0.2, -0.1, n_eff=12.0), mk("rf", -0.2, -0.1, n_eff=29.0)], BASE) == (None, "insufficient_evidence")


def test_test_metrics_never_used():
    a = select([mk("ridge", -0.2, -0.1, test_mae=0.1)], BASE)
    b = select([mk("ridge", -0.2, -0.1, test_mae=99.0)], BASE)
    assert a == b == ("ridge", "ok_beats_baseline")


def test_empty_and_failed_and_timeout():
    assert select([], BASE) == (None, "data_unavailable")
    assert select([HorizonModelResult(horizon=1, model="rf", family="ml")], BASE) == (None, "failed")
    assert select([HorizonModelResult(horizon=1, model="rf", family="ml")], BASE, timed_out=True) == (None, "timeout")
