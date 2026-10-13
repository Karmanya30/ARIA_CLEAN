"""Scenario robustness layer: bootstrap determinism, paired-difference sign, calibrated-interval coverage, long-short arithmetic."""
import numpy as np
import pandas as pd
import pytest

from modules.equity_research.scenario_backtest import robustness as rb


def _syms(n_c=60, per=5):
    return np.repeat([f"S{i}" for i in range(n_c)], per)


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    rng = np.random.default_rng(1)
    s, x = _syms(), rng.normal(0.3, 1.0, 300)
    a, b = rb.boot_mean(s, x), rb.boot_mean(s, x)
    assert a == b                                   # same seed, same draws
    assert a["lo"] < x.mean() < a["hi"] and a["lo"] > 0 and a["p"] < 0.05
    m1, m2 = rb.boot_median(s, x), rb.boot_median(s, x)
    assert m1 == m2 and m1["lo"] <= np.median(x) <= m1["hi"]


def test_paired_difference_sign():
    rng = np.random.default_rng(2)
    s = _syms()
    base = (rng.random(300) < 0.45).astype(float)
    aria = np.where(rng.random(300) < 0.5, 1.0, base)   # ARIA wins whenever the coin says so: strictly >= baseline
    up, down = rb.paired_mean(s, aria, base), rb.paired_mean(s, base, aria)
    assert up["est"] > 0 and up["lo"] > 0 and up["p"] < 0.05
    assert down["est"] < 0 and down["hi"] < 0
    assert rb.paired_mean(s, base, base)["est"] == 0


def test_permutation_null_is_centred_on_the_year_mix():
    rng = np.random.default_rng(3)
    n = 400
    yrs = np.repeat([2018, 2019], n // 2)
    r = rng.integers(0, 3, n)
    hit = rng.random((n, 3)) < 0.5                  # calls carry no information
    out = rb.perm_p(r, yrs, lambda rr: hit[np.arange(n), rr].mean(), n_perm=300)
    assert out["p"] > 0.05
    informed = hit.copy()
    informed[np.arange(n), r] = True                # the call always hits: should be detected
    assert rb.perm_p(r, yrs, lambda rr: informed[np.arange(n), rr].mean(), n_perm=300)["p"] < 0.01


def _cases(n_c, years, sigma, width, seed):
    rng = np.random.default_rng(seed)
    rows = []
    for y in years:
        for i in range(n_c):
            base = 100.0
            u = rng.normal(0, sigma)
            rows.append(dict(symbol=f"C{i}", origin_fy=f"Mar {y}", origin_year=y, line="revenue", k=1, actual=base * np.exp(u),
                             bear=base * np.exp(-width), base=base, bull=base * np.exp(width), structural_break=False, short_history=False))
    return pd.DataFrame(rows)


def test_calibrated_interval_reaches_target_out_of_sample():
    c = pd.concat([_cases(80, range(2018, 2022), 0.30, 0.03, 4), _cases(80, range(2022, 2026), 0.30, 0.03, 5)], ignore_index=True)
    out = rb.interval_calibration(c)["cells"]["revenue"][1]
    assert out["test_uncalibrated"]["est"] < 0.15                 # the shipped cases are far too tight for sigma 0.30
    assert out["scale"] > 5
    assert abs(out["fit_coverage_check"] - 0.68) < 0.01
    assert abs(out["test_calibrated"]["est"] - 0.68) < 0.04       # holds on the later origins
    # required scale by hand: actual = base*exp(+0.06) with bull = +0.03 needs s = 2
    one = pd.DataFrame([dict(line="revenue", actual=100 * np.exp(0.06), bear=100 * np.exp(-0.03), base=100.0, bull=100 * np.exp(0.03))])
    assert rb.required_scale(one).iloc[0] == pytest.approx(2.0)


def test_long_short_arithmetic_by_hand():
    d = pd.DataFrame([
        # year 2018: BUY A +0.20, B 0.00 (mean 0.10); SELL C -0.10 -> long-short 0.20
        dict(symbol="A", origin_year=2018, rating="BUY", x=0.20), dict(symbol="B", origin_year=2018, rating="BUY", x=0.00),
        dict(symbol="C", origin_year=2018, rating="SELL", x=-0.10),
        # year 2019: BUY A +0.30, D +0.10 (mean 0.20); SELL C +0.05 -> long-short 0.15
        dict(symbol="A", origin_year=2019, rating="BUY", x=0.30), dict(symbol="D", origin_year=2019, rating="BUY", x=0.10),
        dict(symbol="C", origin_year=2019, rating="SELL", x=0.05)])
    p = rb.portfolio(d, "x")
    y1, y2 = p["years"]
    assert y1["long_short"] == pytest.approx(0.20) and y2["long_short"] == pytest.approx(0.15)
    assert (y1["turnover_long"], y1["turnover_short"]) == (1.0, 1.0)              # first year builds the book
    assert y2["turnover_long"] == pytest.approx(0.5) and y2["turnover_short"] == pytest.approx(0.0)   # A kept, B -> D; C kept
    ls = p["strategies"]["long BUY / short SELL"]["all years"]
    assert ls["gross_by_year_mean"] == pytest.approx(0.175)
    assert ls["cost_bps"][0]["est"] == pytest.approx(0.175)
    # 100 bps round trip: year 1 pays 1% * (1 + 1), year 2 pays 1% * 0.5 -> mean cost 1.25%
    assert ls["cost_bps"][100]["est"] == pytest.approx(0.175 - 0.0125)
    lo = p["strategies"]["long BUY only, excess vs Nifty"]["all years"]
    assert lo["gross_by_year_mean"] == pytest.approx(0.15) and lo["cost_bps"][100]["est"] == pytest.approx(0.15 - 0.01 * (1.0 + 0.5) / 2)


def test_core_reports_all_baselines_and_classes():
    rng = np.random.default_rng(6)
    n = 900
    ex = rng.normal(-0.02, 0.25, n)
    d = pd.DataFrame({"symbol": [f"S{i % 150}" for i in range(n)], "origin_year": np.tile([2018, 2019, 2020], n // 3),
                      "rating": np.where(ex > 0.0, "BUY", "SELL"), "headline": ex})      # clairvoyant: calls follow the outcome
    c = rb.core(d, "headline", 12, n_perm=100)
    assert c["hit"]["paired_vs"]["random_same_mix"]["est"] > 0.2
    assert c["hit"]["perm_year"]["p"] < 0.05
    assert c["buy_minus_sell"]["est"] > 0.3
    cm = np.array(c["classes"]["confusion"])
    assert cm.sum() == n and cm[1].sum() == 0                  # no HOLD calls were made
