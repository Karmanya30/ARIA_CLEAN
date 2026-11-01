"""Independent reference implementations (textbook formulas, written from scratch; nothing imported from ARIA).

Plain Python + numpy only. Each function is deliberately written in a different way from ARIA's closed form
(loops / bisection / brute force) so a shared algebra slip cannot hide.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np


# ---------------------------------------------------------------- time value of money
def sip_fv_loop(monthly, n_months, annual_pct):
    """Annuity due by explicit month-by-month roll-forward: deposit at start of month, then grow one month."""
    r = annual_pct / 1200.0
    bal = 0.0
    for _ in range(n_months):
        bal = (bal + monthly) * (1 + r)
    return bal


def emi_by_bisection(principal, annual_pct, n_months):
    """Find the payment that amortises the loan to zero in n months (simulated balance, bisection)."""
    r = annual_pct / 1200.0
    if r == 0:
        return principal / n_months

    def end_balance(pmt):
        b = principal
        for _ in range(n_months):
            b = b * (1 + r) - pmt
        return b

    lo, hi = 0.0, principal * (1 + r)
    for _ in range(200):
        mid = (lo + hi) / 2
        if end_balance(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def sip_required_ref(target, n_months, annual_pct):
    return target / sip_fv_loop(1.0, n_months, annual_pct)


def pv_annuity(pmt, n, r):
    return sum(pmt / (1 + r) ** k for k in range(1, n + 1))


# ---------------------------------------------------------------- India income tax (published slabs)
def _bracket_tax(income, brackets):
    """brackets: list of (lower_bound, rate) ascending; tax = sum over slices."""
    tax = 0.0
    for i, (lo, rate) in enumerate(brackets):
        hi = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if income > lo:
            tax += (min(income, hi) - lo) * rate
    return tax


NEW_BR = [(0, 0), (400000, .05), (800000, .10), (1200000, .15), (1600000, .20), (2000000, .25), (2400000, .30)]


def tax_new_ref(gross):
    taxable = max(0.0, gross - 75000)
    t = _bracket_tax(taxable, NEW_BR)
    if taxable <= 1200000:
        t = 0.0  # 87A: full rebate up to Rs 60,000 covers all tax on <= 12L
    else:
        t = min(t, taxable - 1200000)  # marginal relief
    return round(t * 1.04, 2), taxable


def tax_old_ref(gross, d80c=0, d80d=0, age=None, senior=False):
    senior = senior or (age is not None and age >= 60)
    cap_d = 50000 if senior else 25000
    taxable = max(0.0, gross - 50000 - min(d80c, 150000) - min(d80d, cap_d))
    exempt = 500000 if (age is not None and age >= 80) else 300000 if senior else 250000
    t = _bracket_tax(taxable, [(0, 0), (exempt, .05), (500000, .20), (1000000, .30)])
    if taxable <= 500000:
        t = max(0.0, t - 12500)
    return round(t * 1.04, 2), taxable


# ---------------------------------------------------------------- XIRR / CAGR
def xirr_ref(flows):
    """Newton from several starts, falling back to scan+bisection; actual/365."""
    d0 = flows[0][0]
    ts = np.array([(d - d0).days / 365.0 for d, _ in flows])
    cs = np.array([c for _, c in flows])
    f = lambda r: float(np.sum(cs / (1 + r) ** ts))
    grid = np.linspace(-0.95, 20, 4000)
    vals = [f(g) for g in grid]
    for a, b, fa, fb in zip(grid, grid[1:], vals, vals[1:]):
        if fa == 0:
            return a
        if fa * fb < 0:
            lo, hi = a, b
            for _ in range(100):
                m = (lo + hi) / 2
                if f(lo) * f(m) <= 0:
                    hi = m
                else:
                    lo = m
            return (lo + hi) / 2
    return None


def cagr_ref(first, last, years):
    return (last / first) ** (1.0 / years) - 1


def max_drawdown_ref(prices):
    peak, worst = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        worst = min(worst, p / peak - 1)
    return worst


# ---------------------------------------------------------------- cost of capital
def capm_ref(rf, beta, erp):
    return rf + beta * erp


def beta_ols_ref(stock, index):
    s, m = np.asarray(stock, float), np.asarray(index, float)
    return float(np.cov(s, m, ddof=1)[0, 1] / np.var(m, ddof=1))


def wacc_ref(e, d, ke, kd, t):
    v = e + d
    return e / v * ke + d / v * kd * (1 - t)


# ---------------------------------------------------------------- DCF (explicit, year by year)
def dcf_ref(rev0, growth, ebitda_m, da_pct, capex_pct, nwc_pct, tax, wacc, tg, net_debt, nci, shares):
    """FCFF = EBIT(1-t) + D&A - capex - dNWC. Growth capex above D&A scales with g/g1 (ARIA's stated convention,
    re-implemented here from its documentation, not copied)."""
    g1 = growth[0]
    pv = 0.0
    rev_prev = rev0
    fcfs = []
    for t, g in enumerate(growth, start=1):
        rev = rev_prev * (1 + g)
        da = da_pct * rev
        ebit = ebitda_m * rev - da
        scale = g / g1 if g1 > 0 else 1.0
        capex = max(da + (capex_pct - da_pct) * rev * scale, 0.0)
        dnwc = nwc_pct * (rev - rev_prev)
        fcf = ebit * (1 - tax) + da - capex - dnwc
        fcfs.append(fcf)
        pv += fcf / (1 + wacc) ** t
        rev_prev = rev
    n = len(growth)
    # steady state: capex = D&A grown at tg (anchor min(D&A, capex)), NWC grows with revenue
    anchor = min(da_pct, capex_pct)
    da_n = anchor * rev_prev
    ebit_n = ebitda_m * rev_prev - da_n
    fcf_ss = ebit_n * (1 - tax) + da_n - da_n * (1 + tg) - nwc_pct * rev_prev * tg
    tv = fcf_ss * (1 + tg) / (wacc - tg)
    pv_tv = tv / (1 + wacc) ** n
    ev = pv + pv_tv
    eq = ev - net_debt - nci
    return {"ev": ev, "equity": eq, "per_share": eq / shares, "pv_fcf": pv, "pv_tv": pv_tv, "tv_share": pv_tv / ev, "fcf": fcfs, "fcf_ss": fcf_ss}


def fade_ref(g1, tg, n=10):
    return [g1 + (tg - g1) * i / (n - 1) for i in range(n)]


def gordon(cf_next, r, g):
    return cf_next / (r - g)


def ddm_ref(eps0, payout, growth, coe, tg, roe_t):
    eps = eps0
    pv = 0.0
    for t, g in enumerate(growth, start=1):
        eps *= 1 + g
        pv += eps * payout / (1 + coe) ** t
    sustainable = 1 - tg / roe_t if roe_t > tg else payout
    term_payout = min(max(sustainable, payout), 1.0)
    tv = eps * (1 + tg) * term_payout / (coe - tg)
    return pv + tv / (1 + coe) ** len(growth)


def justified_pb_ref(bvps, roe, coe, g):
    return bvps * (roe - g) / (coe - g)


def rim_ref(bv0, roe0, coe, payout, years=10):
    """Edwards-Bell-Ohlson with ROE fading linearly to CoE."""
    bv, total = bv0, 0.0
    for t in range(1, years + 1):
        roe_t = roe0 + (coe - roe0) * t / years
        total += (roe_t - coe) * bv / (1 + coe) ** t
        bv = bv + roe_t * bv * (1 - payout)
    return bv0 + total


def lbo_price_bruteforce(ebitda0, ebitda_path, fcf_path, tax, rate, nci, net_debt, shares, lev=3.0, hurdle_irr=0.20, years=5):
    """Bisection on entry EV until sponsor IRR == hurdle (sponsor equity = EV - debt - nci; exit at entry multiple)."""
    debt0 = lev * ebitda0
    nd = debt0
    for t in range(years):
        interest = max(nd, 0) * rate
        nd -= fcf_path[t] - interest * (1 - tax)
    growth = ebitda_path[years - 1] / ebitda0

    def irr_at(ev):
        eq_in = ev - debt0 - nci
        eq_out = growth * ev - nd - nci
        if eq_in <= 0 or eq_out <= 0:
            return None
        return (eq_out / eq_in) ** (1 / years) - 1

    lo, hi = debt0 + nci + 1e-6, 1e9
    for _ in range(300):
        mid = (lo + hi) / 2
        irr = irr_at(mid)
        if irr is None or irr > hurdle_irr:
            lo = mid  # still earns more than hurdle (or equity not positive at the low end): can pay more
        else:
            hi = mid
    ev = (lo + hi) / 2
    return ev, (ev - net_debt - nci) / shares


# ---------------------------------------------------------------- forecast error metrics
def mape_ref(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    k = np.abs(y) >= 1e-8
    return 100 * np.mean(np.abs((y[k] - p[k]) / y[k]))


def smape_ref(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    d = np.abs(y) + np.abs(p)
    k = d > 0
    return 100 * np.mean(2 * np.abs(y[k] - p[k]) / d[k])


def r2_ref(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return 1 - np.sum((y - p) ** 2) / np.sum((y - y.mean()) ** 2)


def bh_ref(pv, q=0.05):
    m = len(pv)
    order = sorted(range(m), key=lambda i: pv[i])
    kmax = -1
    for rank, i in enumerate(order, start=1):
        if pv[i] <= q * rank / m:
            kmax = rank
    rej = [False] * m
    for rank, i in enumerate(order, start=1):
        if rank <= kmax:
            rej[i] = True
    return rej


def dm_ref(e1, e2, h):
    """Diebold-Mariano with Newey-West/Bartlett variance and Harvey-Leybourne-Newbold correction, t(n-1)."""
    from scipy import stats
    d = np.abs(np.asarray(e1, float)) - np.abs(np.asarray(e2, float))
    n = len(d)
    dbar = d.mean()
    gam = [np.sum((d[k:] - dbar) * (d[:n - k] - dbar)) / n for k in range(h)]
    var = gam[0] + 2 * sum((1 - k / h) * gam[k] for k in range(1, h))
    stat = dbar / math.sqrt(var / n)
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    stat *= hln
    return stat, stats.t.cdf(stat, n - 1)


def pinball_ref(y, qs):
    y = np.asarray(y, float)
    out = []
    for tau, q in qs.items():
        q = np.asarray(q, float)
        out.append(np.mean([tau * (a - b) if a >= b else (tau - 1) * (a - b) for a, b in zip(y, q)]))
    return float(np.mean(out))
