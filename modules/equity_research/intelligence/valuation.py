"""
Deterministic valuation: cost of capital, DCF, DDM, justified P/B, reverse DCF.

Everything here is arithmetic on typed inputs -- the LLM chooses none of it.
Each input is derived from the company's own statements (3-year medians, CAGRs)
or from a *configured* macro assumption, and is registered on the ledger with the
reason it was chosen. Models refuse (``NotApplicable``) rather than emit a number
they cannot defend: terminal growth at/above the discount rate, a WACC-minus-growth
spread so thin it puts a 60x multiplier on the terminal cash flow, a non-positive
steady-state cash flow, or net debt exceeding enterprise value.

Non-financial companies: DCF + peer P/E + peer EV/EBITDA.
Banks / NBFCs (no meaningful free cash flow): DDM + justified P/B + peer P/B + peer P/E.

Model structure and guard rails adapted from FinRobot (Apache-2.0, AI4Finance
Foundation; see THIRD_PARTY_NOTICES.md). Code is an independent implementation.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field, replace

from config import settings
from modules.equity_research.intelligence.analysis import Analysis, Risk, cagr, fy, median_recent
from modules.equity_research.intelligence.comps import (
    LABELS, MIN_PEERS, group_name, SIZE_RATIO_MAX, WEIGHTS_DEFAULT, Method, Synthesis, comps_table, multiple_stats, synthesize,
)
from modules.equity_research.intelligence.data import Snapshot
from modules.equity_research.intelligence.facts import ASSUMPTION, CALCULATED, Fact, Ledger, fmt

MODEL = "ARIA valuation model"
CONFIG = "ARIA configuration (FI_* settings; not live market data)"
PROJECTION_YEARS = 10
MIN_GORDON_SPREAD = 0.015  # WACC/CoE minus terminal growth must be at least this
BETA_BOUNDS = (0.5, 2.0)
TAX_BOUNDS = (0.15, 0.35)
STATUTORY_TAX = 0.2517  # Indian base corporate tax incl. surcharge and cess
GROWTH_CAP = 0.25
MIN_BETA_OBS = 100  # weekly returns needed for a regression beta (~2 years)
TV_DOMINANCE = 0.85  # terminal value share of EV above which the DCF is flagged


class NotApplicable(ValueError):
    """The model cannot produce a defensible value for this company; the message says why."""


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ── cost of capital ────────────────────────────────────────────────────────
def capm(rf: float, beta: float, erp: float) -> float:
    return rf + beta * erp


def blume_adjust(raw_beta: float) -> float:
    """Blume mean-reversion (2/3 raw + 1/3 market), applied only above 1.0: noisy high
    betas revert toward the market, but a low beta on a defensive franchise is structural
    (FinRobot's asymmetric variant), so it is left alone."""
    return raw_beta if raw_beta <= 1.0 else 2 / 3 * raw_beta + 1 / 3


def estimate_beta(stock: list[float], index: list[float]) -> tuple[float, int] | None:
    """OLS slope of stock on index returns. None if too few observations or no index variance."""
    n = min(len(stock), len(index))
    if n < MIN_BETA_OBS:
        return None
    s, m = stock[-n:], index[-n:]
    ms, mm = statistics.fmean(s), statistics.fmean(m)
    var = sum((x - mm) ** 2 for x in m)
    if var == 0:
        return None
    return sum((a - ms) * (b - mm) for a, b in zip(s, m)) / var, n


def wacc_from(coe: float, kd: float, tax: float, debt_ratio: float) -> float:
    return (1 - debt_ratio) * coe + debt_ratio * kd * (1 - tax)


def fade(g1: float, tg: float, n: int = PROJECTION_YEARS) -> tuple[float, ...]:
    """Growth stepping linearly from g1 in year 1 to the terminal rate in year n."""
    return tuple(g1 + (tg - g1) * i / (n - 1) for i in range(n))


# ── DCF ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DCFInputs:
    revenue_base: float  # ₹ Cr, trailing twelve months
    growth: tuple[float, ...]  # annual revenue growth, one per projection year
    ebitda_margin: float
    da_pct: float  # depreciation & amortisation / revenue
    capex_pct: float  # capex / revenue in the growth phase
    nwc_pct: float  # net working capital / revenue: change in NWC = nwc_pct x change in revenue
    tax_rate: float
    wacc: float
    terminal_growth: float
    net_debt: float  # ₹ Cr
    nci: float  # ₹ Cr, minority interest
    shares_cr: float  # crore shares, so ₹ Cr / Cr shares = ₹ per share


@dataclass(frozen=True)
class DCFResult:
    revenue: tuple[float, ...]
    ebitda: tuple[float, ...]
    fcf: tuple[float, ...]
    pv_fcf: float
    terminal_fcf: float
    terminal_value: float
    pv_terminal: float
    tv_share: float  # PV of terminal value / enterprise value
    enterprise_value: float
    equity_value: float
    per_share: float


def projection_lines(inp: DCFInputs, growth: tuple[float, ...]) -> dict[str, list[float]]:
    """Every line of the explicit forecast, per year: FCF = EBIT(1-t) + D&A - capex - change in NWC.
    Net investment (capex minus D&A) scales with the growth rate: as growth fades the company
    needs proportionally less growth capex, instead of carrying peak-growth capex into maturity."""
    g1 = growth[0]
    out: dict[str, list[float]] = {k: [] for k in ("revenue", "growth", "ebitda", "margin", "da", "ebit", "tax", "nopat", "capex", "nwc_change", "fcf")}
    prev = inp.revenue_base
    for g in growth:
        rev = prev * (1 + g)
        da = rev * inp.da_pct
        scale = g / g1 if g1 > 0 else 1.0
        capex = max(da + rev * (inp.capex_pct - inp.da_pct) * scale, 0.0)
        ebit = rev * inp.ebitda_margin - da
        tax = ebit * inp.tax_rate
        dnwc = inp.nwc_pct * (rev - prev)
        for k, v in (("revenue", rev), ("growth", g), ("ebitda", rev * inp.ebitda_margin), ("margin", inp.ebitda_margin), ("da", da), ("ebit", ebit),
                     ("tax", tax), ("nopat", ebit - tax), ("capex", capex), ("nwc_change", dnwc), ("fcf", ebit - tax + da - capex - dnwc)):
            out[k].append(v)
        prev = rev
    return out


def _project(inp: DCFInputs, growth: tuple[float, ...]) -> tuple[list[float], list[float], list[float]]:
    """Revenue, EBITDA and free cash flow per year (see projection_lines)."""
    lines = projection_lines(inp, growth)
    return lines["revenue"], lines["ebitda"], lines["fcf"]


def _terminal_fcf(inp: DCFInputs, rev_n: float, tg: float) -> float:
    """Steady-state FCF on the final-year revenue. In perpetuity reinvestment normalises:
    capex settles at maintenance (D&A) plus growth (x(1+g)). The anchor is min(D&A, capex)
    so amortisation of acquired intangibles, which needs no cash replacement, is not
    treated as perpetual reinvestment."""
    anchor = min(inp.da_pct, inp.capex_pct)
    da = rev_n * anchor
    ebit = rev_n * inp.ebitda_margin - da
    return ebit * (1 - inp.tax_rate) + da - da * (1 + tg) - inp.nwc_pct * rev_n * tg


def _value(inp: DCFInputs, growth: tuple[float, ...], wacc: float, tg: float) -> DCFResult:
    if tg >= wacc:
        raise NotApplicable(f"terminal growth ({tg:.1%}) is not below the discount rate ({wacc:.1%}); the perpetuity is undefined")
    if wacc - tg < MIN_GORDON_SPREAD:
        raise NotApplicable(
            f"discount rate minus terminal growth is only {wacc - tg:.2%} (minimum {MIN_GORDON_SPREAD:.1%}); "
            f"it would capitalise the terminal cash flow {1 / (wacc - tg):.0f}x"
        )
    revenue, ebitda, fcf = _project(inp, growth)
    n = len(fcf)
    pv_fcf = sum(f / (1 + wacc) ** (i + 1) for i, f in enumerate(fcf))
    terminal_fcf = _terminal_fcf(inp, revenue[-1], tg)
    if terminal_fcf <= 0:
        raise NotApplicable("steady-state free cash flow is not positive, so a perpetuity cannot be capitalised (use relative valuation)")
    terminal_value = terminal_fcf * (1 + tg) / (wacc - tg)
    pv_terminal = terminal_value / (1 + wacc) ** n
    ev = pv_fcf + pv_terminal
    equity = ev - inp.net_debt - inp.nci
    if equity <= 0:
        raise NotApplicable("net debt and minority interest exceed the enterprise value, so equity value is not meaningful")
    return DCFResult(tuple(revenue), tuple(ebitda), tuple(fcf), pv_fcf, terminal_fcf, terminal_value, pv_terminal,
                     pv_terminal / ev, ev, equity, equity / inp.shares_cr)


def dcf(inp: DCFInputs) -> DCFResult:
    return _value(inp, inp.growth, inp.wacc, inp.terminal_growth)


def dcf_sensitivity(inp: DCFInputs, waccs: list[float], tgs: list[float]) -> list[list[float | None]]:
    """Per-share value for every (WACC, terminal growth) pair; None where the model refuses."""
    grid: list[list[float | None]] = []
    for w in waccs:
        row_: list[float | None] = []
        for g in tgs:
            try:
                row_.append(_value(inp, inp.growth, w, g).per_share)
            except NotApplicable:
                row_.append(None)
        grid.append(row_)
    return grid


def margin_swing(inp: DCFInputs, pp: float = 0.02) -> tuple[float | None, float | None]:
    """Per-share value with the EBITDA margin moved -/+ ``pp``: the terminal value capitalises
    the steady-state margin, so this is the assumption the WACC x growth grid never shows."""
    def at(margin: float) -> float | None:
        if not 0 < margin < 1:
            return None
        try:
            return dcf(replace(inp, ebitda_margin=margin)).per_share
        except NotApplicable:
            return None
    return at(inp.ebitda_margin - pp), at(inp.ebitda_margin + pp)


def implied_growth(inp: DCFInputs, price: float, lo: float = -0.10, hi: float = 0.50) -> dict:
    """Reverse DCF: the constant annual revenue growth over the projection window that makes
    the DCF equal the market price (bisection; value is increasing in growth)."""
    n = len(inp.growth)

    def at(g: float) -> float | None:
        try:
            return _value(inp, (g,) * n, inp.wacc, inp.terminal_growth).per_share
        except NotApplicable:
            return None

    p_lo, p_hi = at(lo), at(hi)
    out = {"implied_growth": None, "floor_price": p_lo, "ceiling_price": p_hi, "reason": "solved"}
    if p_hi is None:
        return {**out, "reason": "not_applicable"}
    if price > p_hi:
        return {**out, "reason": "above_range"}  # not explainable by any growth in the bracket
    if p_lo is not None and price < p_lo:
        return {**out, "reason": "below_range"}
    for _ in range(60):
        mid = (lo + hi) / 2
        p = at(mid)  # None: the model refuses at this growth (e.g. non-positive steady-state FCF), i.e. worth less than any price
        lo, hi = (mid, hi) if p is None or p < price else (lo, mid)
        if hi - lo < 1e-5:
            break
    return {**out, "implied_growth": (lo + hi) / 2}


def implied_wacc(inp: DCFInputs, price: float, lo: float = 0.04, hi: float = 0.30) -> float | None:
    """Discount rate the market price implies under the model's own growth path (value falls as WACC rises)."""
    def at(w: float) -> float | None:
        try:
            return _value(inp, inp.growth, w, inp.terminal_growth).per_share
        except NotApplicable:
            return None

    lo = max(lo, inp.terminal_growth + MIN_GORDON_SPREAD)
    p_lo, p_hi = at(lo), at(hi)
    if p_lo is None or p_hi is None or not p_hi <= price <= p_lo:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        p = at(mid)
        if p is None:
            return None
        lo, hi = (mid, hi) if p > price else (lo, mid)
        if hi - lo < 1e-5:
            break
    return (lo + hi) / 2


# Scenario spreads: what "bull" and "bear" mean is fixed here, not judged by a model.
SCENARIO_GROWTH_PP, SCENARIO_MARGIN_PP, SCENARIO_WACC_PP, SCENARIO_TG_PP = 0.02, 0.02, 0.01, 0.005
MC_DRAWS, MC_SEED, MC_MIN_VALID = 2000, 42, 200


# How much weight each case gets in the probability-weighted value (a stated convention, like the spreads above;
# the weighted value is reported beside the three cases, never instead of them). Idea from ai-hedge-fund (MIT).
SCENARIO_WEIGHTS = {"bear": 0.25, "base": 0.50, "bull": 0.25}


def scenario_inputs(inp: DCFInputs, d: int) -> tuple[DCFInputs, tuple[float, ...], float, float]:
    """Inputs, growth path, WACC and terminal growth of the bull (d=+1), base (0) or bear (d=-1) case: growth and
    margin +/-2pp, WACC -/+1pp, terminal growth +/-0.5pp, all at once."""
    if d == 0:
        return inp, inp.growth, inp.wacc, inp.terminal_growth
    tg = inp.terminal_growth + d * SCENARIO_TG_PP
    g1 = max(inp.growth[0] + d * SCENARIO_GROWTH_PP, tg)
    return replace(inp, ebitda_margin=inp.ebitda_margin + d * SCENARIO_MARGIN_PP), fade(g1, tg, len(inp.growth)), inp.wacc - d * SCENARIO_WACC_PP, tg


def scenario_value(inp: DCFInputs, d: int) -> float | None:
    """DCF per share in the bull (d=+1) or bear (d=-1) case. None where the model refuses."""
    try:
        return _value(*scenario_inputs(inp, d)).per_share
    except NotApplicable:
        return None


def scenario_detail(inp: DCFInputs, d: int) -> dict:
    """The whole case, line by line: its assumptions, every forecast line, the discounting and the bridge from enterprise
    value to value per share. {"reason": ...} where the model refuses this case."""
    case_inp, growth, wacc, tg = scenario_inputs(inp, d)
    try:
        res = _value(case_inp, growth, wacc, tg)
    except NotApplicable as exc:
        return {"reason": str(exc)}
    lines = projection_lines(case_inp, growth)
    factors = [1 / (1 + wacc) ** (i + 1) for i in range(len(growth))]
    return {"assumptions": {"g1": growth[0], "g_final": growth[-1], "margin": case_inp.ebitda_margin, "wacc": wacc, "terminal_growth": tg,
                            "tax": case_inp.tax_rate, "capex_pct": case_inp.capex_pct, "nwc_pct": case_inp.nwc_pct},
            "lines": lines, "discount_factor": factors, "pv_fcf": [f * k for f, k in zip(lines["fcf"], factors)],
            "bridge": {"sum_pv_fcf": res.pv_fcf, "terminal_fcf": res.terminal_fcf, "terminal_value": res.terminal_value, "pv_terminal": res.pv_terminal,
                       "tv_share": res.tv_share, "enterprise_value": res.enterprise_value, "net_debt": inp.net_debt, "nci": inp.nci,
                       "equity_value": res.equity_value, "shares_cr": inp.shares_cr, "per_share": res.per_share,
                       "ev_ebitda_fwd": res.enterprise_value / lines["ebitda"][0] if lines["ebitda"][0] > 0 else None}}


def weighted_value(cases: dict[str, float | None]) -> float | None:
    """Probability-weighted value per share across bear/base/bull; None unless every case could be valued."""
    if any(cases.get(k) is None for k in SCENARIO_WEIGHTS):
        return None
    return sum(w * cases[k] for k, w in SCENARIO_WEIGHTS.items())


def monte_carlo(inp: DCFInputs, price: float, draws: int = MC_DRAWS, seed: int = MC_SEED) -> dict | None:
    """Distribution of DCF value under independent uncertainty in growth (sd 2pp), margin (sd 2pp), WACC
    (sd 1pp) and terminal growth (sd 0.5pp). Seeded, so the same inputs always give the same answer
    (the audit re-runs it). None if too few draws produced a valid value."""
    rng = random.Random(seed)
    tg0, g0 = inp.terminal_growth, inp.growth[0]
    out: list[float] = []
    for _ in range(draws):
        tg = clamp(tg0 + rng.gauss(0, SCENARIO_TG_PP), 0.0, 0.07)
        g1 = max(g0 + rng.gauss(0, SCENARIO_GROWTH_PP), tg)
        m = clamp(inp.ebitda_margin + rng.gauss(0, SCENARIO_MARGIN_PP), 0.01, 0.95)
        try:
            out.append(_value(replace(inp, ebitda_margin=m), fade(g1, tg, len(inp.growth)), inp.wacc + rng.gauss(0, SCENARIO_WACC_PP), tg).per_share)
        except NotApplicable:
            continue
    if len(out) < MC_MIN_VALID:
        return None
    q = statistics.quantiles(out, n=10, method="inclusive")
    return {"n": len(out), "p10": q[0], "p50": q[4], "p90": q[8], "prob_above_price": sum(1 for v in out if v > price) / len(out)}


# LBO cross-check: what a financial buyer could pay and still earn its hurdle. Fixed rules, stated in the report.
LBO_LEVERAGE, LBO_TARGET_IRR, LBO_YEARS, LBO_SPREAD = 3.0, 0.20, 5, 0.03  # debt / EBITDA, sponsor IRR, hold (years), debt cost over risk-free


def lbo(inp: DCFInputs, res: DCFResult, rate: float) -> dict:
    """Highest entry enterprise value at which a sponsor that borrows LBO_LEVERAGE x EBITDA, sweeps all free cash flow
    into the debt and sells after LBO_YEARS at its entry EV/EBITDA multiple still earns LBO_TARGET_IRR, on the DCF's own
    projection. Sponsor equity in = EV - debt - minorities, out = (exit EBITDA / entry EBITDA) x EV - net debt at exit -
    minorities, so the hurdle solves in closed form. ``per_share`` is None, with a reason, when no price is binding."""
    n = LBO_YEARS
    ebitda0 = inp.revenue_base * inp.ebitda_margin
    out = {"per_share": None, "entry_ev": None, "entry_multiple": None, "leverage": LBO_LEVERAGE, "rate": rate, "irr": LBO_TARGET_IRR,
           "years": n, "min_cover": None, "reason": ""}
    if ebitda0 <= 0 or len(res.fcf) < n:
        return {**out, "reason": "needs positive EBITDA and a five-year projection"}
    debt0 = LBO_LEVERAGE * ebitda0
    nd, cover = debt0, []
    for t in range(n):
        interest = max(nd, 0.0) * rate
        if interest:
            cover.append(res.ebitda[t] / interest)
        nd -= res.fcf[t] - interest * (1 - inp.tax_rate)
    a, hurdle = res.ebitda[n - 1] / ebitda0, (1 + LBO_TARGET_IRR) ** n
    if a >= hurdle:
        return {**out, "reason": "the model's EBITDA growth alone beats the 20% hurdle, so leverage does not bound the price"}
    ev = (hurdle * (debt0 + inp.nci) - (nd + inp.nci)) / (hurdle - a)
    if ev <= debt0 + inp.nci:
        return {**out, "reason": f"free cash flow cannot carry {LBO_LEVERAGE:g}x EBITDA of acquisition debt"}
    per_share = (ev - inp.net_debt - inp.nci) / inp.shares_cr
    if per_share <= 0:
        return {**out, "reason": "existing net debt exceeds what a leveraged buyer could pay"}
    return {**out, "per_share": per_share, "entry_ev": ev, "entry_multiple": ev / ebitda0, "min_cover": min(cover) if cover else None}


def _ddm_case(inp: DDMInputs, d: int) -> tuple[DDMInputs, float]:
    """Inputs and cost of equity of the bull (d=+1), base (0) or bear (d=-1) case: EPS growth +/-2pp, cost of equity -/+1pp."""
    if d == 0:
        return inp, inp.coe
    tg = inp.terminal_growth
    g1 = max(inp.growth[0] + d * SCENARIO_GROWTH_PP, tg)
    return replace(inp, growth=fade(g1, tg, len(inp.growth))), inp.coe - d * SCENARIO_WACC_PP


def ddm_scenario_value(inp: DDMInputs, d: int) -> float | None:
    """DDM per share, bull (d=+1) / bear (d=-1). None where the model refuses."""
    case, coe = _ddm_case(inp, d)
    try:
        return ddm(case, coe=coe).per_share
    except NotApplicable:
        return None


def ddm_scenario_detail(inp: DDMInputs, d: int) -> dict:
    """The DDM case line by line: EPS, growth, dividends and their present values, then the terminal value."""
    case, coe = _ddm_case(inp, d)
    try:
        res = ddm(case, coe=coe)
    except NotApplicable as exc:
        return {"reason": str(exc)}
    eps, path = case.eps0, []
    for g in case.growth:
        eps *= 1 + g
        path.append(eps)
    factors = [1 / (1 + coe) ** (i + 1) for i in range(len(case.growth))]
    return {"assumptions": {"g1": case.growth[0], "g_final": case.growth[-1], "coe": coe, "terminal_growth": case.terminal_growth, "payout": case.payout},
            "lines": {"eps": path, "growth": list(case.growth), "dps": list(res.dividends)},
            "discount_factor": factors, "pv_dps": [d_ * k for d_, k in zip(res.dividends, factors)],
            "bridge": {"sum_pv_dividends": res.pv_dividends, "terminal_payout": res.terminal_payout, "terminal_value": res.terminal_value,
                       "pv_terminal": res.pv_terminal, "per_share": res.per_share}}


# ── DDM and justified P/B (banks, NBFCs) ───────────────────────────────────
@dataclass(frozen=True)
class DDMInputs:
    eps0: float  # ₹, trailing
    payout: float  # dividend payout ratio held through the explicit window
    growth: tuple[float, ...]  # annual EPS growth
    coe: float
    terminal_growth: float
    terminal_roe: float  # long-run ROE, used to normalise the terminal payout


@dataclass(frozen=True)
class DDMResult:
    dividends: tuple[float, ...]
    pv_dividends: float
    terminal_payout: float
    terminal_value: float
    pv_terminal: float
    per_share: float


def ddm(inp: DDMInputs, coe: float | None = None, tg: float | None = None) -> DDMResult:
    """Multi-stage dividend discount model. The terminal dividend is stepped up to the payout the
    long-run ROE can sustain (1 - g/ROE): a bank retaining most of its earnings today is building
    capital that matures into dividends, and discounting its low trailing payout forever undervalues it."""
    coe = inp.coe if coe is None else coe
    tg = inp.terminal_growth if tg is None else tg
    if tg >= coe or coe - tg < MIN_GORDON_SPREAD:
        raise NotApplicable(f"cost of equity ({coe:.1%}) is too close to terminal growth ({tg:.1%}) for a perpetuity")
    eps, dividends = inp.eps0, []
    for g in inp.growth:
        eps *= 1 + g
        dividends.append(eps * inp.payout)
    n = len(dividends)
    pv_div = sum(d / (1 + coe) ** (i + 1) for i, d in enumerate(dividends))
    terminal_payout = clamp(1 - tg / inp.terminal_roe, inp.payout, 1.0) if inp.terminal_roe > tg else inp.payout
    terminal_value = eps * (1 + tg) * terminal_payout / (coe - tg)
    pv_terminal = terminal_value / (1 + coe) ** n
    value = pv_div + pv_terminal
    if value <= 0:
        raise NotApplicable("the dividend stream has no positive value")
    return DDMResult(tuple(dividends), pv_div, terminal_payout, terminal_value, pv_terminal, value)


RIM_YEARS = 10


def residual_income(bvps: float, roe: float, coe: float, payout: float, years: int = RIM_YEARS) -> dict:
    """Residual income model (Edwards-Bell-Ohlson): value = book value + present value of future profits in excess of the
    cost of equity on that book. Return on equity fades in a straight line to the cost of equity over ``years`` (competitive
    advantage erodes), so no excess return is assumed after that -- the conservative textbook closing. Book value grows by
    retained earnings. Concept as used in ai-hedge-fund (MIT); this implementation keeps book value and the cost of equity
    from the company's own statements and ARIA's CAPM, and applies no arbitrary haircut."""
    if bvps <= 0:
        raise NotApplicable("book value per share is not positive")
    if not 0 <= payout <= 1:
        raise NotApplicable("dividend payout is outside 0-100%")
    bv, pv, rows = bvps, 0.0, []
    for t in range(1, years + 1):
        r = roe + (coe - roe) * t / years
        ri = (r - coe) * bv
        pv_ri = ri / (1 + coe) ** t
        pv += pv_ri
        rows.append({"year": t, "roe": r, "book": bv, "residual_income": ri, "pv": pv_ri})
        bv += r * bv * (1 - payout)
    return {"per_share": bvps + pv, "book": bvps, "pv_residual": pv, "rows": rows}


def justified_pb(bvps: float, roe: float, coe: float, tg: float) -> float:
    """Price = book value x (ROE - g) / (CoE - g): what a bank earning ``roe`` on book deserves."""
    if coe - tg < MIN_GORDON_SPREAD:
        raise NotApplicable("cost of equity is too close to terminal growth for a P/B-ROE valuation")
    if roe <= tg:
        raise NotApplicable(f"return on equity ({roe:.1%}) does not exceed terminal growth ({tg:.1%}); book value is not creating value")
    return bvps * (roe - tg) / (coe - tg)


# ── assembling a valuation for one company ─────────────────────────────────
@dataclass
class Valuation:
    synthesis: Synthesis | None = None
    methods: list[Method] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # method -> why it was not run
    notes: list[str] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    coc: dict[str, float] = field(default_factory=dict)  # rf, beta, erp, coe, kd, tax, debt_ratio, wacc (fractions)
    dcf_inputs: DCFInputs | None = None
    dcf_result: DCFResult | None = None
    dcf_extra: dict = field(default_factory=dict)  # sensitivity grid, margin swing, reverse DCF
    ddm_inputs: DDMInputs | None = None
    ddm_result: DDMResult | None = None
    comps: dict | None = None
    scenarios: dict[str, float | None] = field(default_factory=dict)  # bear / base / bull per-share value
    monte_carlo: dict | None = None
    facts: dict[str, Fact] = field(default_factory=dict)
    withheld_by_audit: bool = False  # set by the pipeline when the verification gate blocks the valuation


def value_company(snap: Snapshot, an: Analysis, ledger: Ledger) -> Valuation:
    val = Valuation()
    price = snap.price
    if not price:
        val.skipped["all"] = "no share price available"
        ledger.miss("Valuation", "no share price available")
        return val
    if an.latest:
        (_intrinsic_financial if snap.is_financial else _intrinsic_operating)(snap, an, ledger, val)
    else:
        val.skipped["intrinsic"] = "no financial statements available"
    _comps(snap, an, ledger, val)
    if val.methods:
        street = an.facts["target_mean"].value if "target_mean" in an.facts else None
        val.synthesis = synthesize(val.methods, price, street=street)
        _register_synthesis(val, ledger)
    return val


def _assume(ledger: Ledger, label: str, value: float, unit: str, method: str, *, kind: str = ASSUMPTION,
            inputs=(), source: str = MODEL, period: str = "forecast") -> Fact:
    # Everything not stamped "today" (a model output) is something the model was fed.
    return ledger.add(label, value, unit, period, source, kind, method=method, inputs=inputs,
                      tag="" if period == "today" else "model_input")


def _cost_of_capital(snap: Snapshot, an: Analysis, ledger: Ledger, val: Valuation, *, with_debt: bool) -> None:
    rf, erp = settings.FI_RISK_FREE_RATE, settings.FI_EQUITY_RISK_PREMIUM
    f_rf = _assume(ledger, "Risk-free rate", rf * 100, "%", "10-year G-sec proxy: a configured assumption, not a live yield", source=CONFIG, period="configured")
    f_erp = _assume(ledger, "Equity risk premium", erp * 100, "%", "India equity risk premium: a configured assumption", source=CONFIG, period="configured")
    est = estimate_beta(snap.stock_returns, snap.index_returns)
    if est:
        raw, n = est
        f_raw = _assume(ledger, "Beta (raw)", raw, "", "OLS slope of the stock's weekly returns on Nifty 50", kind=CALCULATED,
                        source="ARIA analysis (Yahoo Finance prices)", period=f"{n} weekly returns")
        beta = clamp(blume_adjust(raw), *BETA_BOUNDS)
        adj = "" if abs(beta - raw) < 1e-9 else f"; adjusted from {raw:.2f} (Blume mean reversion above 1.0, bounded to {BETA_BOUNDS[0]}-{BETA_BOUNDS[1]})"
        f_beta = _assume(ledger, "Beta (used)", beta, "", f"regression beta vs Nifty 50{adj}", kind=CALCULATED, inputs=[f_raw], period=f"{n} weekly returns")
    else:
        beta = 1.0
        f_beta = _assume(ledger, "Beta (used)", beta, "", "fewer than ~2 years of weekly prices: market beta of 1.0 assumed", period="assumed")
        val.notes.append("Beta could not be estimated (insufficient price history); a market beta of 1.0 was assumed.")
    coe = capm(rf, beta, erp)
    f_coe = _assume(ledger, "Cost of equity", coe * 100, "%", "CAPM: risk-free + beta x equity risk premium", kind=CALCULATED, inputs=[f_rf, f_beta, f_erp])
    val.coc = {"rf": rf, "erp": erp, "beta": beta, "coe": coe}
    val.facts.update(rf=f_rf, erp=f_erp, beta=f_beta, coe=f_coe)
    if not with_debt:
        return

    s, L = an.series, an.latest
    borrowings, interest = s["borrowings"], s["interest"]
    prev = an.years[-2] if len(an.years) > 1 else None
    avg_debt = statistics.fmean([borrowings[L], borrowings[prev]]) if prev and borrowings.get(L) and borrowings.get(prev) else borrowings.get(L)
    if interest.get(L) is not None and avg_debt:
        kd = clamp(interest[L] / avg_debt, rf, rf + 0.06)
        f_kd = _assume(ledger, "Pre-tax cost of debt", kd * 100, "%", "interest expense / average borrowings, kept between the risk-free rate and risk-free + 6pp", kind=CALCULATED, period=fy(L))
    else:
        kd = rf + 0.015
        f_kd = _assume(ledger, "Pre-tax cost of debt", kd * 100, "%", "interest or borrowings unavailable: risk-free + 1.5pp assumed")
    tax_hist = median_recent([s["tax_rate"].get(c) for c in an.years])
    tax = clamp(tax_hist, *TAX_BOUNDS) if tax_hist is not None else STATUTORY_TAX
    f_tax = _assume(ledger, "Tax rate", tax * 100, "%", "median effective rate of the last 3 years, bounded to 15-35%" if tax_hist is not None
                    else "statutory rate (25.17%): no usable history", kind=CALCULATED if tax_hist is not None else ASSUMPTION)
    total_debt = (snap.info.get("totalDebt") or 0) / 1e7 or (borrowings.get(L) or 0.0)
    mcap = snap.market_cap_cr
    debt_ratio = clamp(total_debt / (total_debt + mcap), 0.0, 0.6) if mcap else 0.0
    f_dr = _assume(ledger, "Debt / (debt + market cap)", debt_ratio * 100, "%", "market-value capital structure weight, capped at 60%", kind=CALCULATED, period="latest")
    wacc = wacc_from(coe, kd, tax, debt_ratio)
    f_wacc = _assume(ledger, "WACC", wacc * 100, "%", "(1 - D/V) x cost of equity + D/V x cost of debt x (1 - tax)", kind=CALCULATED, inputs=[f_coe, f_kd, f_tax, f_dr])
    val.coc.update(kd=kd, tax=tax, debt_ratio=debt_ratio, wacc=wacc)
    val.facts.update(kd=f_kd, tax=f_tax, debt_ratio=f_dr, wacc=f_wacc)


def _base_growth(an: Analysis, floor: float) -> tuple[float, str]:
    """Year-1 growth: median of the 3y and 5y history (revenue or EPS), kept between the
    terminal rate and 25%. Returns (growth, plain-English provenance)."""
    return _growth_from(an, ("rev_cagr3", "rev_cagr5"), "rev_growth", floor, "revenue")


def _growth_from(an: Analysis, cagr_keys: tuple[str, ...], yoy_key: str, floor: float, what: str) -> tuple[float, str]:
    hist = [an.facts[k].value / 100 for k in cagr_keys if k in an.facts]
    if hist:
        raw, basis = statistics.median(hist), f"median of the 3y and 5y {what} CAGR"
    elif yoy_key in an.facts:
        raw, basis = an.facts[yoy_key].value / 100, f"latest-year {what} growth (too little history for a CAGR)"
    else:
        raise NotApplicable(f"no {what} growth history to project from")
    g = clamp(raw, floor, GROWTH_CAP)
    note = "" if g == raw else f" ({raw:.1%} raised/lowered to {g:.1%}: kept between the terminal rate and {GROWTH_CAP:.0%})"
    return g, f"{basis} = {raw:.1%}{note}"


def _intrinsic_operating(snap: Snapshot, an: Analysis, ledger: Ledger, val: Valuation) -> None:
    try:
        _dcf(snap, an, ledger, val)
    except NotApplicable as exc:
        val.skipped["dcf"] = str(exc)
        ledger.miss("DCF valuation", str(exc))


def _dcf(snap: Snapshot, an: Analysis, ledger: Ledger, val: Valuation) -> None:
    s, L, years = an.series, an.latest, an.years
    _cost_of_capital(snap, an, ledger, val, with_debt=True)
    coc, tg = val.coc, settings.FI_TERMINAL_GROWTH
    f_tg = _assume(ledger, "Terminal growth", tg * 100, "%", "long-run nominal growth: a configured assumption", source=CONFIG, period="configured")

    revenue_base = an.ttm.get("revenue") or s["revenue"][L]
    base_period = "TTM" if an.ttm.get("revenue") else fy(L)
    margin = median_recent([s["opm"].get(c) for c in years])
    da = median_recent([s["da_pct"].get(c) for c in years])
    if margin is None or margin <= 0:
        raise NotApplicable("EBITDA margin is not positive, so a cash-flow projection is not meaningful")
    if da is None:
        raise NotApplicable("depreciation is not available")
    capex = median_recent([s["capex_pct"].get(c) for c in years])
    nwc_latest = s["nwc_pct"].get(L)
    shares = snap.shares / 1e7 if snap.shares else None
    if not shares:
        raise NotApplicable("share count is not available")
    g1, g_basis = _base_growth(an, tg)
    net_debt = snap.net_debt_cr
    nd_method = "total debt - total cash (Yahoo Finance, consolidated)"
    if net_debt is None:
        net_debt = s["borrowings"].get(L) or 0.0
        nd_method = "cash unknown: borrowings used as net debt (conservative)"
        val.notes.append("Cash balance unavailable: net debt was taken as gross borrowings, which understates equity value.")
    nci = snap.nci_cr or 0.0
    if snap.nci_cr is None:
        val.notes.append("Minority interest unavailable: assumed zero in the enterprise-to-equity bridge.")

    A = lambda label, value, unit, method, **kw: _assume(ledger, label, value, unit, method, **kw)  # noqa: E731
    f_base = A("Base revenue", revenue_base, "₹ Cr", "trailing twelve months (screener.in, consolidated)" if base_period == "TTM" else "latest fiscal year", kind=CALCULATED, period=base_period, source="screener.in")
    f_g = A("Year-1 revenue growth", g1 * 100, "%", g_basis + f"; fades linearly to {tg:.1%} by year {PROJECTION_YEARS}")
    f_m = A("Forecast EBITDA margin", margin * 100, "%", "median of the last 3 fiscal years, held flat", kind=CALCULATED)
    f_da = A("Depreciation / revenue", da * 100, "%", "median of the last 3 fiscal years", kind=CALCULATED)
    capex_pct = capex if capex is not None else da
    f_cx = A("Capex / revenue", capex_pct * 100, "%", "median of the last 3 fiscal years (operating cash flow - free cash flow)" if capex is not None
             else "capex not derivable: set equal to depreciation (maintenance only)", kind=CALCULATED if capex is not None else ASSUMPTION)
    nwc = clamp(nwc_latest, -0.05, 0.30) if nwc_latest is not None else 0.0
    f_nwc = A("Working capital / revenue", nwc * 100, "%", "working-capital days / 365 (screener.in), bounded to -5%..30%; scales with revenue growth" if nwc_latest is not None
              else "working-capital days unavailable: assumed nil", kind=CALCULATED if nwc_latest is not None else ASSUMPTION)
    f_nd = A("Net debt", net_debt, "₹ Cr", nd_method, kind=CALCULATED, period="latest", source="Yahoo Finance")
    f_nci = A("Minority interest", nci, "₹ Cr", "Yahoo Finance balance sheet" if snap.nci_cr is not None else "unavailable: assumed zero", kind=CALCULATED if snap.nci_cr is not None else ASSUMPTION, period="latest", source="Yahoo Finance")

    inp = DCFInputs(revenue_base, fade(g1, tg), margin, da, capex_pct, nwc, coc["tax"], coc["wacc"], tg, net_debt, nci, shares)
    res = dcf(inp)
    val.dcf_inputs, val.dcf_result = inp, res
    assumption_facts = [f_base, f_g, f_m, f_da, f_cx, f_nwc, f_nd, f_nci, f_tg, val.facts["wacc"]]
    val.facts.update(base_rev=f_base, g1=f_g, margin=f_m, da=f_da, capex=f_cx, nwc=f_nwc, net_debt=f_nd, nci=f_nci, tg=f_tg)
    F = val.facts
    F["dcf_value"] = _assume(ledger, "DCF fair value per share", res.per_share, "₹", "10-year FCF projection + Gordon-growth terminal value; equity = EV - net debt - minorities",
                             kind=CALCULATED, inputs=assumption_facts, period="today")
    F["dcf_ev"] = _assume(ledger, "Enterprise value (DCF)", res.enterprise_value, "₹ Cr", "PV of 10 years of FCF + PV of terminal value", kind=CALCULATED, period="today")
    F["dcf_tv_share"] = _assume(ledger, "Terminal value share of EV", res.tv_share * 100, "%", "PV of terminal value / enterprise value", kind=CALCULATED, period="today")

    waccs = [coc["wacc"] - 0.02, coc["wacc"] - 0.01, coc["wacc"], coc["wacc"] + 0.01, coc["wacc"] + 0.02]
    tgs = [tg - 0.01, tg - 0.005, tg, tg + 0.005, tg + 0.01]
    grid = dcf_sensitivity(inp, waccs, tgs)
    inner = [v for r in grid[1:4] for v in r[1:4] if v is not None]
    low, high = (min(inner), max(inner)) if inner else (res.per_share, res.per_share)
    swing = margin_swing(inp)
    reverse = implied_growth(inp, snap.price)
    iw = implied_wacc(inp, snap.price)
    val.dcf_extra = {"wacc_values": waccs, "tg_values": tgs, "prices": grid, "margin_swing": swing, "reverse": reverse, "implied_wacc": iw}
    F["dcf_low"] = _assume(ledger, "DCF value, low case", low, "₹", "lowest of the WACC +/-1pp x terminal growth +/-0.5pp grid", kind=CALCULATED, period="today")
    F["dcf_high"] = _assume(ledger, "DCF value, high case", high, "₹", "highest of the WACC +/-1pp x terminal growth +/-0.5pp grid", kind=CALCULATED, period="today")
    if reverse["implied_growth"] is not None:
        F["implied_growth"] = _assume(ledger, "Market-implied revenue growth", reverse["implied_growth"] * 100, "%",
                                      f"constant annual growth over {PROJECTION_YEARS} years at which this DCF equals today's price", kind=CALCULATED, period="today")
    if iw is not None:
        F["implied_wacc"] = _assume(ledger, "Market-implied WACC", iw * 100, "%", "discount rate at which this DCF equals today's price, holding growth", kind=CALCULATED, period="today")

    bear, bull = scenario_value(inp, -1), scenario_value(inp, +1)
    val.scenarios = {"bear": bear, "base": res.per_share, "bull": bull}
    if (pw := weighted_value(val.scenarios)) is not None:
        F["scenario_weighted"] = _assume(ledger, "Probability-weighted DCF value", pw, "₹", "bear 25% / base 50% / bull 25% of the three DCF cases", kind=CALCULATED, period="today")
    for name, v in (("bear", bear), ("bull", bull)):
        if v is not None:
            up = name == "bull"
            F[f"scenario_{name}"] = _assume(
                ledger, f"DCF value, {name} scenario", v, "₹",
                f"growth and margin {'+' if up else '-'}{SCENARIO_GROWTH_PP * 100:.0f}pp, WACC {'-' if up else '+'}{SCENARIO_WACC_PP * 100:.0f}pp, "
                f"terminal growth {'+' if up else '-'}{SCENARIO_TG_PP * 100:.1f}pp", kind=CALCULATED, period="today")
    mc = monte_carlo(inp, snap.price)
    if mc:
        val.monte_carlo = mc
        how = f"{mc['n']:,} seeded Monte Carlo scenarios"
        F["mc_p10"] = _assume(ledger, "DCF value, 10th percentile", mc["p10"], "₹", how, kind=CALCULATED, period="today")
        F["mc_p90"] = _assume(ledger, "DCF value, 90th percentile", mc["p90"], "₹", how, kind=CALCULATED, period="today")
        F["mc_prob"] = _assume(ledger, "Share of scenarios above today's price", mc["prob_above_price"] * 100, "%", how, kind=CALCULATED, period="today")
    lb = lbo(inp, res, settings.FI_RISK_FREE_RATE + LBO_SPREAD)
    val.dcf_extra["lbo"] = lb
    if lb["per_share"] is not None:
        F["lbo_value"] = _assume(ledger, "LBO-implied value per share", lb["per_share"], "₹", kind=CALCULATED, period="today",
                                 method=f"highest price at which a buyer borrowing {LBO_LEVERAGE:g}x EBITDA at {lb['rate']:.1%} and selling after "
                                        f"{LBO_YEARS} years at the entry multiple earns {LBO_TARGET_IRR:.0%} a year; cross-check only")

    val.methods.append(Method("dcf", "Discounted cash flow", low, res.per_share, high, WEIGHTS_DEFAULT["dcf"],
                              f"WACC {coc['wacc']:.1%}, terminal growth {tg:.1%}, growth {g1:.1%} fading over {PROJECTION_YEARS}y",
                              tuple(f.id for f in (F["dcf_value"], F["dcf_low"], F["dcf_high"], val.facts["wacc"], f_tg, f_g, f_m))))
    if res.tv_share > TV_DOMINANCE:
        val.risks.append(Risk("valuation", "medium", "DCF dominated by terminal value",
                              f"{fmt(res.tv_share * 100, '%')} of enterprise value is the terminal value, so the result rests on long-run assumptions.", (F["dcf_tv_share"].id,)))
    if reverse["reason"] == "above_range":
        val.risks.append(Risk("valuation", "high", "Price not explained by cash-flow growth",
                              f"Even 50% annual revenue growth (worth {fmt(reverse['ceiling_price'], '₹')} per share) does not justify today's price under these assumptions: "
                              "the market is pricing something a cash-flow model cannot capture.", ()))
    if swing[0] is not None and swing[1] is not None and res.per_share > 0:
        f_lo = _assume(ledger, "DCF value at margin -2pp", swing[0], "₹", "DCF re-run with the EBITDA margin 2 percentage points lower", kind=CALCULATED, period="today")
        f_hi = _assume(ledger, "DCF value at margin +2pp", swing[1], "₹", "DCF re-run with the EBITDA margin 2 percentage points higher", kind=CALCULATED, period="today")
        if (swing[1] - swing[0]) / res.per_share > 0.5:
            val.risks.append(Risk("valuation", "medium", "Value is highly margin-sensitive",
                                  f"A 2pp change in EBITDA margin moves the DCF value between {f_lo.text} and {f_hi.text}.", (f_lo.id, f_hi.id)))


def _intrinsic_financial(snap: Snapshot, an: Analysis, ledger: Ledger, val: Valuation) -> None:
    _cost_of_capital(snap, an, ledger, val, with_debt=False)
    tg, coe, L = settings.FI_TERMINAL_GROWTH, val.coc["coe"], an.latest
    f_tg = _assume(ledger, "Terminal growth", tg * 100, "%", "long-run nominal growth: a configured assumption", source=CONFIG, period="configured")
    roe = median_recent([an.series["roe"].get(c) for c in an.years])
    if roe is None:
        val.skipped["ddm"] = val.skipped["justified_pb"] = "return on equity is not available"
        return
    roe_t = clamp(roe, tg + 0.02, 0.25)
    f_roe = _assume(ledger, "Long-run ROE", roe_t * 100, "%", "median of the last 3 fiscal years' ROE, bounded to 7%..25%", kind=CALCULATED, period="3y median")
    F = val.facts

    try:  # DDM
        eps0 = (an.facts.get("eps_ttm") or an.facts.get("eps"))
        if eps0 is None:
            raise NotApplicable("EPS is not available")
        payout = median_recent([an.series["payout"].get(c) for c in an.years])
        if payout is None:
            raise NotApplicable("dividend payout history is not available")
        g1, g_basis = _growth_from(an, ("eps_cagr3", "eps_cagr5"), "pat_growth", tg, "EPS")
        g1 = min(g1, 0.20)
        f_eps = _assume(ledger, "Base EPS", eps0.value, "₹", "trailing twelve months" if eps0.period == "TTM" else "latest fiscal year", kind=CALCULATED, period=eps0.period, source="screener.in")
        f_pay = _assume(ledger, "Dividend payout", payout * 100, "%", "median of the last 3 fiscal years, held through the explicit window", kind=CALCULATED)
        f_g = _assume(ledger, "Year-1 EPS growth", g1 * 100, "%", g_basis + f"; fades linearly to {tg:.1%} by year {PROJECTION_YEARS} (capped at 20%)")
        F.update(eps0=f_eps, payout=f_pay, g1=f_g, roe_t=f_roe, tg=f_tg)
        inp = DDMInputs(eps0.value, payout, fade(g1, tg), coe, tg, roe_t)
        res = ddm(inp)
        val.ddm_inputs, val.ddm_result = inp, res
        grid = [ddm(inp, coe=c, tg=g).per_share for c in (coe - 0.01, coe + 0.01) for g in (tg - 0.005, tg + 0.005)
                if c - g >= MIN_GORDON_SPREAD]
        low, high = (min(grid + [res.per_share]), max(grid + [res.per_share]))
        F["ddm_value"] = _assume(ledger, "DDM fair value per share", res.per_share, "₹", "10-year dividend projection + Gordon terminal value at a sustainable payout",
                                 kind=CALCULATED, inputs=[f_eps, f_pay, f_g, f_roe, F["coe"], f_tg], period="today")
        bear, bull = ddm_scenario_value(inp, -1), ddm_scenario_value(inp, +1)
        val.scenarios = {"bear": bear, "base": res.per_share, "bull": bull}
        if (pw := weighted_value(val.scenarios)) is not None:
            F["scenario_weighted"] = _assume(ledger, "Probability-weighted DDM value", pw, "₹", "bear 25% / base 50% / bull 25% of the three DDM cases", kind=CALCULATED, period="today")
        for name, v in (("bear", bear), ("bull", bull)):
            if v is not None:
                up = name == "bull"
                F[f"scenario_{name}"] = _assume(
                    ledger, f"DDM value, {name} scenario", v, "₹",
                    f"EPS growth {'+' if up else '-'}{SCENARIO_GROWTH_PP * 100:.0f}pp, cost of equity {'-' if up else '+'}{SCENARIO_WACC_PP * 100:.0f}pp",
                    kind=CALCULATED, period="today")
        val.methods.append(Method("ddm", "Dividend discount model", low, res.per_share, high, WEIGHTS_DEFAULT["ddm"],
                                  f"cost of equity {coe:.1%}, terminal growth {tg:.1%}, EPS growth {g1:.1%} fading over {PROJECTION_YEARS}y",
                                  (F["ddm_value"].id, F["coe"].id, f_g.id, f_roe.id)))
    except NotApplicable as exc:
        val.skipped["ddm"] = str(exc)
        ledger.miss("DDM valuation", str(exc))

    try:  # justified P/B
        bvps = snap.info.get("bookValue")
        bv_source = "Yahoo Finance"
        if not isinstance(bvps, (int, float)) or bvps <= 0:
            nw, sh = an.series["net_worth"].get(L), snap.shares
            bvps, bv_source = (nw * 1e7 / sh, "screener.in net worth / Yahoo shares") if nw and sh else (None, "")
        if not bvps:
            raise NotApplicable("book value per share is not available")
        f_bv = _assume(ledger, "Book value per share", float(bvps), "₹", "as reported" if bv_source == "Yahoo Finance" else bv_source, kind="raw" if bv_source == "Yahoo Finance" else CALCULATED, period="latest", source=bv_source)
        value = justified_pb(bvps, roe_t, coe, tg)
        lo_v, hi_v = justified_pb(bvps, roe_t, coe + 0.01, tg), justified_pb(bvps, roe_t, coe - 0.01, tg)
        F["jpb_value"] = _assume(ledger, "Justified P/B value per share", value, "₹", "book value x (ROE - g) / (cost of equity - g)", kind=CALCULATED, inputs=[f_bv, f_roe, F["coe"], f_tg], period="today")
        F["bvps"] = f_bv
        val.methods.append(Method("justified_pb", "Justified P/B (ROE-based)", lo_v, value, hi_v, WEIGHTS_DEFAULT["justified_pb"],
                                  f"ROE {roe_t:.1%} vs cost of equity {coe:.1%}: justified P/B {(roe_t - tg) / (coe - tg):.2f}x",
                                  (F["jpb_value"].id, f_bv.id, f_roe.id, F["coe"].id)))
    except NotApplicable as exc:
        val.skipped["justified_pb"] = str(exc)
        ledger.miss("Justified P/B valuation", str(exc))


def _comps(snap: Snapshot, an: Analysis, ledger: Ledger, val: Valuation) -> None:
    if not snap.peers:
        reason = "no peer set for this company's industry" if not snap.peer_group else "peer data unavailable"
        for k in (("comps_pb", "comps_pe", "comps_fpe") if snap.is_financial else ("comps_pe", "comps_fpe", "comps_ev_ebitda")):
            val.skipped[k] = reason
        return
    sizes = [p.mcap_cr for p in snap.peers if p.mcap_cr]
    if snap.market_cap_cr and len(sizes) >= MIN_PEERS:
        ratio = snap.market_cap_cr / statistics.median(sizes)
        if ratio > SIZE_RATIO_MAX or ratio < 1 / SIZE_RATIO_MAX:
            reason = (f"the company is {ratio:.1f}x the size of the median {snap.peer_group} peer, so peer multiples are not comparable "
                      f"(more than {SIZE_RATIO_MAX:g}x apart)")
            for k in (("comps_pb", "comps_pe", "comps_fpe") if snap.is_financial else ("comps_pe", "comps_fpe", "comps_ev_ebitda")):
                val.skipped[k] = reason
            val.notes.append("Peer-multiple valuation was skipped: " + reason + ".")
            return
    stats = {k: multiple_stats(k, snap.peers) for k in ("pe", "fwd_pe", "pb", "ev_ebitda")}
    val.comps = comps_table(snap.peers, stats)
    val.comps["group"] = snap.peer_group
    info, F = snap.info, val.facts
    src = f"Yahoo Finance peer multiples ({group_name(snap.peer_group)} peers)"

    def apply(kind: str, key: str, label: str, subject: float | None, subject_label: str, convert=lambda x: x) -> None:
        st = stats[kind]
        if not st.usable:
            val.skipped[key] = f"only {len(st.used)} usable peer multiples (need {MIN_PEERS})"
            return
        if subject is None or subject <= 0:
            val.skipped[key] = f"{subject_label} is not available or not positive"
            return
        f_med = ledger.add(f"Peer median {label}", st.median, "x", f"{len(st.used)} peers", src, "raw", method="median of peers passing the sanity and not-meaningful filters")
        mid, low, high = convert(st.median * subject), convert(st.low * subject), convert(st.high * subject)
        if mid <= 0:
            val.skipped[key] = "implied equity value is not positive"
            return
        F[key] = ledger.add(f"Peer-multiple value ({label})", mid, "₹", "today", MODEL, CALCULATED,
                            method=f"peer median {label} x company {subject_label}", inputs=[f_med])
        val.methods.append(Method(key, f"Peer {label}", low, mid, high, WEIGHTS_DEFAULT[key],
                                  f"peer median {label} {st.median:.1f}x on {subject_label} ({len(st.used)} peers)", (F[key].id, f_med.id)))

    eps = info.get("trailingEps")
    eps = float(eps) if isinstance(eps, (int, float)) and not isinstance(eps, bool) else (an.facts["eps_ttm"].value if "eps_ttm" in an.facts else None)
    apply("pe", "comps_pe", "P/E", eps, "trailing EPS")
    feps = info.get("forwardEps")
    apply("fwd_pe", "comps_fpe", "forward P/E", float(feps) if isinstance(feps, (int, float)) and not isinstance(feps, bool) else None,
          "forward EPS (Yahoo consensus)")
    if snap.is_financial:
        bv = info.get("bookValue")
        apply("pb", "comps_pb", "P/B", float(bv) if isinstance(bv, (int, float)) and not isinstance(bv, bool) else None, "book value per share")
        return
    ev, mult, sh = info.get("enterpriseValue"), info.get("enterpriseToEbitda"), snap.shares
    ebitda_cr = ev / mult / 1e7 if isinstance(ev, (int, float)) and isinstance(mult, (int, float)) and mult > 0 else None
    nd = snap.net_debt_cr
    if ebitda_cr and nd is not None and sh:
        # EBITDA implied by Yahoo's own EV and multiple, so subject and peers share one definition
        apply("ev_ebitda", "comps_ev_ebitda", "EV/EBITDA", ebitda_cr, "EBITDA (Yahoo definition)",
              convert=lambda x: (x - nd - (snap.nci_cr or 0.0)) / (sh / 1e7))
    else:
        val.skipped["comps_ev_ebitda"] = "EBITDA, net debt or share count unavailable"


def _register_synthesis(val: Valuation, ledger: Ledger) -> None:
    syn = val.synthesis
    ids = [m_id for m in syn.methods for m_id in m.facts[:1]]
    if syn.central is not None:
        val.facts["fair_value"] = ledger.add("Fair value per share", syn.central, "₹", "today", MODEL, CALCULATED,
                                             method="confidence-weighted blend when methods agree within 1.5x, otherwise the median of methods", inputs=ids)
    val.facts["range_low"] = ledger.add("Fair value range, low", syn.low, "₹", "today", MODEL, CALCULATED, method="lowest method value" if len(syn.methods) > 1 else "single method, low case", inputs=ids)
    val.facts["range_high"] = ledger.add("Fair value range, high", syn.high, "₹", "today", MODEL, CALCULATED, method="highest method value" if len(syn.methods) > 1 else "single method, high case", inputs=ids)
    val.facts["upside"] = ledger.add("Upside / downside to fair value", syn.upside * 100, "%", "today", MODEL, CALCULATED,
                                     method="fair value / share price - 1" if syn.central is not None else "nearest edge of the range vs share price (point estimate withheld)", inputs=ids)
    if syn.spread is not None:
        f_spread = ledger.add("Method dispersion (highest / lowest)", syn.spread, "x", "today", MODEL, CALCULATED, method="highest method value / lowest method value", inputs=ids)
        val.facts["spread"] = f_spread
        if syn.spread > 1.5:
            val.risks.append(Risk("valuation", "high" if syn.spread > 2.5 else "medium", "Valuation methods disagree",
                                  f"The highest and lowest method values differ {f_spread.text}, so the fair value is uncertain.", (f_spread.id,)))
