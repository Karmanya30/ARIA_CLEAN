"""Deterministic valuation models and the cross-method synthesis: known answers and refusals."""
import math
import random

import pytest

from modules.equity_research.intelligence.comps import (
    Method, Peer, multiple_stats, synthesize, verdict,
)
from modules.equity_research.intelligence.valuation import (
    DCFInputs, DDMInputs, NotApplicable, blume_adjust, capm, dcf, dcf_sensitivity, ddm, estimate_beta, fade,
    implied_growth, implied_wacc, justified_pb, margin_swing, wacc_from,
)


def flat(**over) -> DCFInputs:
    """Zero growth, no reinvestment, no tax: FCF is a constant 20 a year, so EV is a perpetuity."""
    base = dict(revenue_base=100.0, growth=(0.0,) * 10, ebitda_margin=0.20, da_pct=0.0, capex_pct=0.0, nwc_pct=0.0, tax_rate=0.0,
                wacc=0.10, terminal_growth=0.0, net_debt=0.0, nci=0.0, shares_cr=10.0)
    return DCFInputs(**{**base, **over})


def growing(**over) -> DCFInputs:
    base = dict(revenue_base=1000.0, growth=fade(0.12, 0.05), ebitda_margin=0.22, da_pct=0.04, capex_pct=0.08, nwc_pct=0.10,
                tax_rate=0.25, wacc=0.12, terminal_growth=0.05, net_debt=300.0, nci=50.0, shares_cr=100.0)
    return DCFInputs(**{**base, **over})


# ── cost of capital ────────────────────────────────────────────────────────
def test_capm_and_wacc():
    coe = capm(0.0675, 1.2, 0.07)
    assert coe == pytest.approx(0.1515)
    assert wacc_from(coe, 0.09, 0.25, 0.2) == pytest.approx(0.8 * 0.1515 + 0.2 * 0.09 * 0.75)


def test_blume_only_adjusts_high_betas():
    assert blume_adjust(0.5) == 0.5  # a structurally defensive low beta is left alone
    assert blume_adjust(1.0) == pytest.approx(1.0)
    assert blume_adjust(2.0) == pytest.approx(2 / 3 * 2 + 1 / 3)


def test_estimate_beta_recovers_slope_and_needs_history():
    rng = random.Random(3)
    m = [rng.gauss(0, 0.02) for _ in range(200)]
    beta, n = estimate_beta([1.5 * x for x in m], m)
    assert beta == pytest.approx(1.5) and n == 200
    assert estimate_beta(m[:50], m[:50]) is None  # under ~2 years of weekly data
    assert estimate_beta([0.01] * 150, [0.0] * 150) is None  # index with no variance


def test_fade_runs_from_start_to_terminal():
    g = fade(0.12, 0.05, 10)
    assert g[0] == pytest.approx(0.12) and g[-1] == pytest.approx(0.05) and len(g) == 10
    assert all(a > b for a, b in zip(g, g[1:]))


# ── DCF ────────────────────────────────────────────────────────────────────
def test_dcf_known_answer_perpetuity():
    res = dcf(flat())
    assert res.enterprise_value == pytest.approx(200.0)  # a 20-a-year perpetuity at 10%
    assert res.per_share == pytest.approx(20.0)
    assert res.tv_share == pytest.approx(1 - sum(20 / 1.1**t for t in range(1, 11)) / 200)


def test_dcf_bridge_subtracts_net_debt_and_minorities():
    res = dcf(flat(net_debt=40.0, nci=10.0))
    assert res.equity_value == pytest.approx(150.0)
    assert res.per_share == pytest.approx(15.0)


@pytest.mark.parametrize(
    "over, why",
    [
        (dict(terminal_growth=0.10), "not below the discount rate"),
        (dict(wacc=0.105, terminal_growth=0.095), "minimum"),
        (dict(net_debt=500.0), "exceed the enterprise value"),
        (dict(ebitda_margin=0.0), "not positive"),
    ],
)
def test_dcf_refuses_rather_than_publish_a_bad_number(over, why):
    with pytest.raises(NotApplicable, match=why):
        dcf(flat(**over))


def test_sensitivity_grid_marks_refused_cells_none():
    grid = dcf_sensitivity(growing(), [0.06, 0.12], [0.03, 0.05])
    assert grid[0][1] is None  # WACC 6% vs growth 5%: spread below the floor
    assert grid[1][0] is not None and grid[1][0] < grid[1][1]  # lower terminal growth, lower value


def test_value_falls_as_wacc_rises_and_rises_with_margin():
    lo, mid, hi = (dcf(growing(wacc=w)).per_share for w in (0.10, 0.12, 0.14))
    assert lo > mid > hi
    swing_lo, swing_hi = margin_swing(growing())
    assert swing_lo < dcf(growing()).per_share < swing_hi


def test_reverse_dcf_round_trips_the_growth_it_was_priced_on():
    inp = growing()
    price = dcf(inp.__class__(**{**inp.__dict__, "growth": (0.09,) * 10})).per_share
    out = implied_growth(inp, price)
    assert out["reason"] == "solved" and out["implied_growth"] == pytest.approx(0.09, abs=2e-4)
    w = implied_wacc(inp, dcf(inp).per_share)
    assert w == pytest.approx(inp.wacc, abs=2e-4)


def test_reverse_dcf_reports_a_price_no_growth_can_justify():
    out = implied_growth(growing(), 1e9)
    assert out["implied_growth"] is None and out["reason"] == "above_range"


def test_capex_scales_with_growth_so_faded_growth_needs_less_reinvestment():
    fast, slow = growing(growth=(0.12,) * 10), growing(growth=fade(0.12, 0.05))
    assert dcf(slow).fcf[-1] / dcf(slow).revenue[-1] > dcf(fast).fcf[-1] / dcf(fast).revenue[-1] - 1  # sanity: both positive margins
    assert all(f > 0 for f in dcf(slow).fcf[5:])


# ── DDM and justified P/B ──────────────────────────────────────────────────
def test_ddm_known_answer_and_terminal_payout_normalisation():
    inp = DDMInputs(eps0=10.0, payout=0.2, growth=(0.0,) * 10, coe=0.12, terminal_growth=0.0, terminal_roe=0.15)
    res = ddm(inp)
    assert res.dividends == pytest.approx((2.0,) * 10)
    assert res.terminal_payout == pytest.approx(1.0)  # 1 - g/ROE = 1 at zero growth
    assert res.per_share == pytest.approx(sum(2 / 1.12**t for t in range(1, 11)) + (10 / 0.12) / 1.12**10)


def test_ddm_and_pb_refuse_bad_spreads():
    inp = DDMInputs(10.0, 0.2, (0.05,) * 10, coe=0.06, terminal_growth=0.05, terminal_roe=0.15)
    with pytest.raises(NotApplicable):
        ddm(inp)
    with pytest.raises(NotApplicable):
        justified_pb(100.0, roe=0.04, coe=0.12, tg=0.05)  # ROE below growth: book value destroys value
    assert justified_pb(100.0, roe=0.15, coe=0.12, tg=0.05) == pytest.approx(100 * 0.10 / 0.07)


# ── peer multiples ─────────────────────────────────────────────────────────
def peer(sym, pe=None, pb=None, ev=None):
    return Peer(sym, sym, pe, pb, ev, 1000.0)


def test_multiple_stats_separates_artifacts_from_not_meaningful_and_needs_three():
    peers = [peer("A", ev=10), peer("B", ev=12), peer("C", ev=14), peer("D", ev=905.9), peer("E", ev=80), peer("F", ev=0.1)]
    st = multiple_stats("ev_ebitda", peers)
    assert st.used == [10, 12, 14] and st.median == 12
    reasons = {sym: why for sym, _, why in st.dropped}
    assert "artifact" in reasons["D"] and "artifact" in reasons["F"] and "not meaningful" in reasons["E"]
    assert not multiple_stats("pe", [peer("A", pe=10), peer("B", pe=12)]).usable


# ── synthesis ──────────────────────────────────────────────────────────────
def m(key, mid, weight=1.0):
    return Method(key, key, mid * 0.8, mid, mid * 1.2, weight, "test")


def test_agreeing_methods_blend_by_weight_at_high_confidence():
    s = synthesize([m("dcf", 100, 1.0), m("comps_pe", 120, 0.5)], price=90)
    assert s.tier == "high" and s.central == pytest.approx(110.0) and not s.withheld  # intrinsic and relative count equally


def test_divergent_methods_use_the_median_and_lower_confidence():
    s = synthesize([m("a", 100), m("b", 200), m("c", 210)], price=150)
    assert s.tier == "medium" and s.central == 200 and any("median" in n for n in s.notes)


def test_methods_that_do_not_corroborate_withhold_the_point_but_keep_a_direction():
    s = synthesize([m("dcf", 100), m("comps_pe", 500)], price=5000)
    assert s.withheld and s.central is None and s.tier == "very_low"
    assert s.rating == "SELL" and s.upside < 0  # direction from the nearest edge of the range
    assert (s.low, s.high) == (100, 500)


def test_single_method_far_from_market_is_withheld():
    assert synthesize([m("dcf", 40)], price=100).withheld
    assert not synthesize([m("dcf", 90)], price=100).withheld


def test_model_far_from_market_is_outside_calibration():
    s = synthesize([m("a", 1000), m("b", 1100)], price=100)
    assert s.withheld and s.tier in ("low", "very_low")


def test_verdict_is_always_directional_with_wider_bands_at_lower_confidence():
    assert verdict(0.25, "high")[0] == "BUY" and verdict(0.25, "medium")[0] == "HOLD"
    assert verdict(-0.30, "high")[0] == "SELL" and verdict(-0.30, "medium")[0] == "HOLD"
    for tier in ("high", "medium", "low", "very_low"):
        for up in (-0.9, -0.1, 0.0, 0.1, 0.9):
            assert verdict(up, tier)[0] in ("BUY", "HOLD", "SELL")


def test_synthesis_rejects_empty_input():
    with pytest.raises(ValueError):
        synthesize([], 100)
    assert math.isfinite(synthesize([m("a", 100)], 100).upside)


def test_peer_multiple_methods_are_one_vote_not_three():
    """Three multiples off one peer group must not outvote the DCF (ITC +135%, LT +82% before this)."""
    methods = [m("dcf", 100), m("comps_pe", 200), m("comps_fpe", 200), m("comps_ev_ebitda", 200)]
    s = synthesize(methods, price=100)
    assert s.spread == pytest.approx(2.0) and s.central == pytest.approx(150.0)  # midpoint of the two families, not the median (200) of four methods
    assert (s.low, s.high) == (100, 200)  # the range still shows every method


def test_approaches_that_diverge_beyond_2_5x_withhold_the_point_and_stay_conservative():
    s = synthesize([m("dcf", 100), m("comps_pe", 260), m("comps_fpe", 260)], price=90)
    assert s.withheld and s.central is None and s.tier == "low"
    assert s.rating == "HOLD" and s.upside == pytest.approx(100 / 90 - 1)  # direction from the range edge all approaches agree on
    inside = synthesize([m("dcf", 100), m("comps_pe", 260)], price=150)
    assert inside.withheld and inside.rating == "HOLD" and inside.upside == 0.0  # price inside the range: no directional claim
    assert synthesize([m("dcf", 100), m("comps_pe", 500)], price=5000).tier == "very_low"
