"""Personalisation helpers: pure functions over the owner's profile (no LLM, nothing logged).

Used to add "for you" lines to stock research, a worked-example hint to the tutor and a profile caption to market answers.
"""
from __future__ import annotations

from typing import Any

from modules.equity_research.intelligence.analysis import _HIGH_VOLATILITY
from modules.finance import engine
from shared import user_store

_HIGH_BETA = 1.2
_RANK = {"Conservative": 0, "Moderate": 1, "Aggressive": 2}


def profile() -> dict[str, Any]:
    """The current owner's known profile facts ({} when there is none)."""
    owner = user_store.current_owner.get()
    p = user_store.get_financial_profile(owner) if owner else None
    return {k: v for k, v in (p or {}).items() if v is not None}


def stock_fit(p: dict, volatility: float | None, beta: float | None, safety: str | None) -> dict[str, Any] | None:
    a = p.get("assets") or {}
    if not p.get("risk_tolerance") and not p.get("monthly_income") and not a:
        return None
    lines: list[str] = []
    risk = p.get("risk_tolerance")
    why = [t for ok, t in ((volatility is not None and volatility > _HIGH_VOLATILITY, f"volatility {volatility:.0f}%"),
                           (beta is not None and beta > _HIGH_BETA, f"beta {beta or 0:.1f}"),
                           (safety == "weak", "weak financial safety")) if ok]
    if risk:
        verdict = ("a poor fit" if _RANK[risk] == 0 else "a stretch" if _RANK[risk] == 1 and len(why) > 1 else "within your range")
        lines.append(f"Risk fit: this stock looks risky ({', '.join(why)}), {verdict} for a {risk.lower()} investor." if why
                     else f"Risk fit: no volatility, beta or safety red flags, in line with a {risk.lower()} investor.")
    s = engine.snapshot(p)
    sur, em = s["monthly_surplus"], s["emergency_months"]
    if sur is not None or em is not None:
        bits = ([f"monthly surplus {engine.inr(sur)}" + (" (none to invest)" if sur <= 0 else "")] if sur is not None else []) \
            + ([f"emergency fund {em:.1f} months" + (" (build 6 first)" if em < 6 else "")] if em is not None else [])
        lines.append("Readiness: " + ", ".join(bits) + ".")
    inv = sum(a.get(k) or 0 for k in ("stocks", "mf", "cash", "fd"))
    if inv > 0:
        lines.append(f"Sizing: keep a single stock to about {engine.inr(inv * 0.05)}-{engine.inr(inv * 0.10)} (5-10% of your investable {engine.inr(inv)}).")
    yrs = p.get("horizon_years") or min((g["years"] for g in p.get("goals") or []), default=None)
    if yrs:
        lines.append(f"Horizon: {yrs:g} years" + (", short for equities (aim for 5+)." if yrs < 5 else "."))
    if not lines:
        return None
    return {"lines": lines, "basis": engine.basis_line(p, ["income", "surplus", "emergency", "risk"]),
            "caveat": "Rules of thumb from your profile, not advice."}


def learner_context(p: dict) -> str:
    """Banded facts for the tutor's worked example; never exact asset values."""
    if not p:
        return ""
    parts = []
    if p.get("age") is not None:
        parts.append(f"age {p['age']}")
    inc = p.get("monthly_income")
    if inc is not None:
        parts.append("income " + next(b for t, b in ((25e3, "under ₹25k"), (5e4, "₹25-50k"), (1e5, "₹50k-1L"), (2e5, "₹1-2L"), (float("inf"), "₹2L+")) if inc < t) + "/month")
    if p.get("risk_tolerance"):
        parts.append(f"{p['risk_tolerance'].lower()} risk")
    if p.get("goals"):
        parts.append("goals " + ", ".join(f"{g['name']} in {g['years']:g}y" for g in p["goals"][:3]))
    sur = engine.snapshot(p)["monthly_surplus"]
    if sur and sur > 0:
        parts.append(f"worked example: SIP of ₹{max(500, round(sur * 0.1 / 500) * 500):,}/mo (10% of surplus)")
    return "; ".join(parts)


def market_caption(p: dict) -> str | None:
    a = {k: v for k, v in (p.get("assets") or {}).items() if v}
    tot = sum(v for k, v in a.items() if k != "real_estate")
    if tot <= 0:
        return None
    groups = {"equity": ("stocks", "mf"), "debt": ("fd", "ppf", "epf", "nps"), "gold": ("gold",), "cash": ("cash",)}
    sh = [(n, round(100 * sum(a.get(k, 0) for k in ks) / tot)) for n, ks in groups.items()]
    return "Based on your profile: " + ", ".join(f"{v}% of your investments are {n}" if i == 0 else f"{v}% {n}" for i, (n, v) in enumerate(sorted(sh, key=lambda x: -x[1])) if v)
