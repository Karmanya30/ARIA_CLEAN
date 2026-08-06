"""Closed-form financial calculators — deterministic, no ML.

Grounding FinGPT/Groq narrations in real formulas (instead of letting the
LLM guess numbers) is what makes the "Insight" section trustworthy.
"""
from __future__ import annotations


def sip_future_value(monthly: float, years: float, annual_return_pct: float) -> float:
    """Future value of a monthly SIP, contribution at end of each period."""
    if monthly <= 0 or years <= 0:
        return 0.0
    r = annual_return_pct / 12 / 100
    n = int(round(years * 12))
    if r == 0:
        return monthly * n
    return monthly * ((pow(1 + r, n) - 1) / r) * (1 + r)


def sip_required(target: float, years: float, annual_return_pct: float) -> float:
    """Monthly SIP required to reach `target` in `years` at `annual_return_pct`."""
    if target <= 0 or years <= 0:
        return 0.0
    r = annual_return_pct / 12 / 100
    n = int(round(years * 12))
    if r == 0:
        return target / n
    return target / (((pow(1 + r, n) - 1) / r) * (1 + r))


def emi(principal: float, annual_rate_pct: float, years: float) -> float:
    """Standard reducing-balance EMI formula."""
    if principal <= 0 or years <= 0:
        return 0.0
    r = annual_rate_pct / 12 / 100
    n = int(round(years * 12))
    if r == 0:
        return principal / n
    return principal * r * pow(1 + r, n) / (pow(1 + r, n) - 1)


def emi_total_interest(principal: float, annual_rate_pct: float, years: float) -> float:
    """Total interest paid over the loan tenure."""
    monthly = emi(principal, annual_rate_pct, years)
    n = int(round(years * 12))
    return max(0.0, monthly * n - principal)
