"""Diebold-Mariano and Benjamini-Hochberg: hand-checked values and synthetic data with a known answer."""
import numpy as np
import pytest

from modules.equity_research.forecast import metrics


def test_dm_hand_computed():
    # h=1: V = population variance of d = 0.25, n=8, mean(d) = -1.5.
    # raw = -1.5 / sqrt(0.25/8) = -8.4853; HLN factor sqrt((8+1-2)/8) = 0.93541  ->  -7.9373
    eb = np.full(8, 10.0)
    em = np.array([9, 8, 9, 8, 9, 8, 9, 8.0])
    stat, p = metrics.dm_test(em, eb, 1)
    assert stat == pytest.approx(-7.9373, abs=1e-3)
    assert p < 1e-3
    s2, p2 = metrics.dm_test(eb, em, 1)  # swapped: baseline better -> p near 1
    assert s2 == pytest.approx(7.9373, abs=1e-3) and p2 > 0.999


def test_dm_newey_west_lag():
    # d alternates +-1 (mean 0 for even n): stat 0, p 0.5 whatever the lag
    d = np.tile([1.0, -1.0], 20)
    assert metrics.dm_test(10 + d, np.full(40, 10.0), 5)[1] == pytest.approx(0.5, abs=1e-9)
    # positively autocorrelated losses must raise the long-run variance, so |stat| shrinks with h
    rng = np.random.default_rng(0)
    x = np.convolve(rng.normal(size=400), np.ones(8) / 8, "same") - 0.05
    s1, _ = metrics.dm_test(10 + x, np.full(400, 10.0), 1)
    s8, _ = metrics.dm_test(10 + x, np.full(400, 10.0), 8)
    assert abs(s8) < abs(s1)


def test_dm_known_truth():
    rng = np.random.default_rng(1)
    base = rng.normal(0, 1.0, 2000)
    assert metrics.dm_test(rng.normal(0, 0.5, 2000), base, 5)[1] < 1e-6  # clearly better model
    assert metrics.dm_test(rng.normal(0, 2.0, 2000), base, 5)[1] > 0.99  # clearly worse model
    ps = [metrics.dm_test(rng.normal(0, 1, 300), rng.normal(0, 1, 300), 5)[1] for _ in range(300)]
    assert 0.02 < np.mean(np.array(ps) < 0.05) < 0.10  # under H0 about 5% of p-values fall below 0.05


def test_dm_degenerate():
    assert metrics.dm_test([1, 1, 1, 1], [1, 1, 1, 1], 1) == (0.0, 1.0)
    assert metrics.dm_test([1, 2], [1, 2], 1) == (0.0, 1.0)
    assert metrics.dm_test([], [], 5) == (0.0, 1.0)


def test_fdr_bh_known():
    # sorted p .005 .01 .03 .04 vs thresholds .0125 .025 .0375 .05 -> all rejected
    assert metrics.fdr_bh([0.01, 0.04, 0.03, 0.005]).tolist() == [True] * 4
    # sorted .01 .03 .2 .9 vs .0125 .025 .0375 .05: only .01 (BH is step-up from the largest passing rank)
    assert metrics.fdr_bh([0.01, 0.2, 0.03, 0.9]).tolist() == [True, False, False, False]
    # step-up: rank 3 passes (0.03 <= 0.0375) so ranks 1-2 are rejected even though 0.03 > 0.025 is irrelevant
    assert metrics.fdr_bh([0.011, 0.026, 0.037, 0.5]).tolist() == [True, True, True, False]
    nan = metrics.fdr_bh([np.nan, 0.001, 0.9])  # NaN neither rejected nor counted in m
    assert nan.tolist() == [False, True, False]
    assert metrics.fdr_bh([]).tolist() == []
