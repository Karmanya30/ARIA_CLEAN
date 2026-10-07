"""Deterministic personal-finance engine: pure functions over a profile dict (no I/O, no LLM).

A profile is the dict from shared.user_store.get_financial_profile (FinanceProfile fields; a missing or None key
means unknown). Standard public formulas only: reducing-balance EMI, SIP annuity, inflation compounding,
FOIR, safe-withdrawal-rate corpus. Unknown inputs yield None and never a guessed number.
"""
from __future__ import annotations

import copy
from typing import Any

from modules.finance import sip_emi_calc, tax

INFLATION, EDU_INFLATION = 0.06, 0.08
RETURNS = {"Conservative": 8.0, "Moderate": 10.0, "Aggressive": 12.0}  # % p.a.
SWR, RETIRE_AGE = 0.035, 60
LOAN_RATES = {"home": 8.5, "car": 9.5, "personal": 13.0}
LOAN_YEARS = {"home": 20, "car": 5, "personal": 3}
CORE_FIELDS = ("age", "dependents", "monthly_income", "income_stability", "expenses", "assets", "loans",
               "term_cover", "health_cover", "goals", "risk_tolerance", "tax_regime", "used_80c", "city")


def _lin(x: float | None, zero: float, full: float) -> float | None:
    """0 at `zero`, 1 at `full`, linear between (works for either direction)."""
    return None if x is None else max(0.0, min(1.0, (x - zero) / (full - zero)))


def _ret(p: dict) -> float:
    return RETURNS.get(p.get("risk_tolerance"), RETURNS["Moderate"])


# ── loans & snapshot ─────────────────────────────────────────────────────
def outstanding(loan: dict) -> float:
    if loan.get("outstanding") is not None:
        return float(loan["outstanding"])
    emi, n, r = loan.get("emi") or 0.0, loan.get("months_left") or 0, (loan.get("rate_pct") or 0.0) / 1200
    if not emi or not n:
        return 0.0
    return emi * n if r == 0 else emi * (1 - (1 + r) ** -n) / r


def total_emi(p: dict) -> float | None:
    if p.get("loans") is not None:
        return sum(l.get("emi") or 0.0 for l in p["loans"])
    return p.get("existing_emi")


def total_expenses(p: dict) -> float | None:
    """Monthly spending, or None while it is only partly known: rent alone is not "what you spend", and treating it so
    would inflate the surplus, the savings rate and the health score. Known = three or more categories, or a stated total (other)."""
    e = p.get("expenses")
    return sum(e.values()) if e and (len(e) >= 3 or "other" in e) else None


def liquid(p: dict) -> float | None:
    a = p.get("assets")
    return None if not a else a.get("cash", 0) + a.get("fd", 0) + 0.5 * a.get("mf", 0)


def snapshot(p: dict) -> dict[str, Any]:
    income, exp, emi, a = p.get("monthly_income"), total_expenses(p), total_emi(p), p.get("assets")
    surplus = income - exp - (emi or 0) if income is not None and exp is not None else None
    lq = liquid(p)
    emergency = lq / (exp + (emi or 0)) if lq is not None and exp else p.get("emergency_fund_months")
    debts = sum(outstanding(l) for l in p.get("loans") or []) + (p.get("credit_card_outstanding") or 0)
    snap = {
        "net_worth": sum(a.values()) - debts if a else None,
        "monthly_surplus": surplus,
        "savings_rate": surplus / income if surplus is not None and income else None,
        "emergency_months": emergency,
        "foir": emi / income if emi is not None and income else None,
        "liquid": lq,
    }
    return {k: None if v is None else round(v, 4 if k in ("savings_rate", "foir") else 1) for k, v in snap.items()}


# ── goals / retirement ───────────────────────────────────────────────────
def goal_plan(goal: dict, p: dict) -> dict[str, Any]:
    rate, years = _ret(p), goal["years"]
    infl = EDU_INFLATION if any(w in goal["name"].lower() for w in ("educat", "college", "school", "mba")) else INFLATION
    future = goal["target"] * (1 + infl) ** years
    gap = max(0.0, future - (goal.get("saved") or 0) * (1 + rate / 100) ** years)
    return {"name": goal["name"], "target": goal["target"], "years": years, "future_target": round(future),
            "sip_needed": round(sip_emi_calc.sip_required(gap, years, rate))}


def goals(p: dict) -> list[dict[str, Any]]:
    plans = [goal_plan(g, p) for g in p.get("goals") or []]
    surplus = snapshot(p)["monthly_surplus"]
    on_track = None if surplus is None else surplus >= sum(g["sip_needed"] for g in plans)
    return [{**g, "on_track": on_track} for g in plans]


def retirement(p: dict) -> dict[str, Any] | None:
    exp, age = total_expenses(p), p.get("age")
    if exp is None or age is None:
        return None
    years, rate = max(0, RETIRE_AGE - age), _ret(p)
    annual = exp * 12 * (1 + INFLATION) ** years
    corpus = annual / SWR
    a = p.get("assets") or {}
    invested = sum(a.get(k, 0) for k in ("mf", "stocks", "fd", "epf", "ppf", "nps", "gold"))
    grown = invested * (1 + rate / 100) ** years
    gap = max(0.0, corpus - grown)
    return {"retirement_age": RETIRE_AGE, "years_to_retire": years, "annual_expense_at_retirement": round(annual),
            "corpus": round(corpus), "current_investments_fv": round(grown), "gap": round(gap),
            "sip_needed": round(sip_emi_calc.sip_required(gap, years, rate)) if years else 0,
            "assumptions": f"inflation {INFLATION:.0%}, return {rate:.0f}%, withdrawal {SWR:.1%}"}


# ── health score ─────────────────────────────────────────────────────────
def health_score(p: dict, anomalies: int = 0) -> dict[str, Any]:
    s = snapshot(p)
    income, exp, a = p.get("monthly_income"), total_expenses(p), p.get("assets")
    tier1_family = p.get("city_tier") == 1 and ((p.get("dependents") or 0) > 0 or p.get("marital_status") == "married")
    need_term = (p.get("dependents") or 0) > 0 or bool(p.get("loans"))
    ins = [] if (p.get("dependents") is None and p.get("loans") is None) else [_lin(p.get("health_cover"), 0, 1_000_000 if tier1_family else 500_000)]
    if need_term:
        ins.append(None if p.get("term_cover") is None or not income else min(1.0, p["term_cover"] / (10 * 12 * income)))
    sips = sum(g["sip_needed"] for g in goals(p))
    classes = None
    if a and sum(a.values()) > 0:
        tot = sum(a.values())
        groups = ((a.get("stocks", 0) + a.get("mf", 0)), (a.get("fd", 0) + a.get("ppf", 0) + a.get("epf", 0) + a.get("nps", 0)),
                  a.get("gold", 0), a.get("real_estate", 0), a.get("cash", 0))
        classes = min(1.0, (sum(1 for g in groups if g / tot >= 0.05) - 1) / 2)
    disc = None
    if income and exp is not None and (len(p["expenses"]) >= 3 or "entertainment" in p["expenses"]):
        disc = _lin((p["expenses"].get("entertainment", 0) + p["expenses"].get("other", 0)) / income, 0.30, 0.10)
        disc = max(0.0, disc - 0.2 * anomalies)
    target = 9 if p.get("income_stability") == "variable" or (p.get("dependents") or 0) > 0 else 6
    cover_need = (p.get("credit_card_outstanding") or 0) + (exp or 0)
    rows = [
        ("Savings rate", 20, _lin(s["savings_rate"], 0, 0.30), f"saving {s['savings_rate']:.0%} of income (full marks at 30%)" if s["savings_rate"] is not None else "needs income and expenses"),
        ("Emergency fund", 15, _lin(s["emergency_months"], 0, target), f"{s['emergency_months']:.1f} months of cover (target {target})" if s["emergency_months"] is not None else "needs savings and expenses"),
        ("Debt burden", 15, _lin(s["foir"], 0.50, 0.20), f"EMIs take {s['foir']:.0%} of income (best under 20%)" if s["foir"] is not None else "needs income and loans"),
        ("Insurance", 15, None if not ins or None in ins else sum(ins) / len(ins), "term and health cover vs need" if ins and None not in ins else "needs your cover details"),
        ("Diversification", 10, classes, "spread across asset classes" if classes is not None else "needs your assets"),
        ("Goal progress", 10, None if not p.get("goals") or s["monthly_surplus"] is None else (1.0 if not sips else min(1.0, max(0.0, s["monthly_surplus"]) / sips)), "surplus vs SIP the goals need" if p.get("goals") and s["monthly_surplus"] is not None else "needs goals and a surplus"),
        ("Budget discipline", 5, disc, "entertainment and other spend vs income" if disc is not None else "needs a spending breakdown"),
        ("Liquidity", 10, None if s["liquid"] is None or exp is None else min(1.0, s["liquid"] / cover_need) if cover_need else 1.0, "liquid money vs card dues plus a month of spend" if s["liquid"] is not None and exp is not None else "needs savings and expenses"),
    ]
    known = [(w, sub) for _, w, sub, _ in rows if sub is not None]
    score = round(100 * sum(w * sub for w, sub in known) / sum(w for w, _ in known)) if known else 0
    # coverage: the share of the 100 weight points that could be measured. A score from a few factors alone is provisional, not a verdict.
    return {"score": score, "coverage": sum(w for w, _ in known) / 100, "breakdown": [{"name": n, "weight": w, "sub": None if sub is None else round(sub, 2), "reason": r} for n, w, sub, r in rows]}


# ── decisions ────────────────────────────────────────────────────────────
def afford_purchase(p: dict, price: float, kind: str = "personal", down_pct: float = 0.2, years: float | None = None) -> dict[str, Any]:
    kind = kind if kind in LOAN_RATES else "personal"
    years, rate = years or LOAN_YEARS[kind], LOAN_RATES[kind]
    income, emi0, exp, lq = max(p.get("monthly_income") or 0.0, 1.0), total_emi(p) or 0.0, total_expenses(p), liquid(p)
    down = price * down_pct
    new_emi = sip_emi_calc.emi(price - down, rate, years)
    foir = (emi0 + new_emi) / income
    verdict = "yes" if foir <= 0.40 else "stretch" if foir <= 0.50 else "no"
    reasons = [f"EMIs would take {foir:.0%} of income after this loan (comfortable up to 40%, hard limit 50%)"]
    left = lq - down if lq is not None else None
    months = left / (exp + emi0 + new_emi) if left is not None and exp else None
    caps = []
    if months is not None and months < 6:
        caps.append(f"the down payment leaves only {months:.1f} months of emergency cover (want 6+)")
    if kind == "car" and new_emi > 0.15 * income:
        caps.append("a car EMI above 15% of income is heavy")
    if kind == "home" and price > 5 * 12 * income:
        caps.append("price is above 5x your annual income")
    if caps and verdict == "yes":
        verdict = "stretch"
    return {"verdict": verdict, "reasons": reasons + caps,
            "numbers": {"price": price, "down_payment": round(down), "loan": round(price - down), "emi": round(new_emi), "years": years,
                        "rate_pct": rate, "foir_before": round(emi0 / income, 3), "foir_after": round(foir, 3),
                        "emergency_months_after": None if months is None else round(months, 1)}}


def afford_sip(p: dict, amount: float) -> dict[str, Any]:
    surplus = snapshot(p)["monthly_surplus"]
    years, rate = p.get("horizon_years") or 10, _ret(p)
    verdict = "yes" if amount <= 0.8 * surplus else "stretch" if amount <= surplus else "no"
    return {"verdict": verdict, "reasons": [f"monthly surplus is ₹{surplus:,.0f}"],
            "numbers": {"amount": amount, "surplus": surplus, "surplus_after": round(surplus - amount), "years": years, "rate_pct": rate,
                        "future_value": round(sip_emi_calc.sip_future_value(amount, years, rate))}}


def _apply(p: dict, changes: dict[str, float]) -> dict:
    q = copy.deepcopy(p)
    for path, delta in changes.items():
        parent, _, key = path.rpartition(".")
        d = q.setdefault(parent, {}) if parent else q
        d[key] = max(0.0, (d.get(key) or 0.0) + delta)
    return q


def what_if(p: dict, changes: dict[str, float]) -> dict[str, Any]:
    """changes: {"expenses.food": -5000, "monthly_income": 10000, ...} as deltas."""
    q = _apply(p, changes)
    before, after = snapshot(p), snapshot(q)
    gain = (after["monthly_surplus"] or 0) - (before["monthly_surplus"] or 0)
    years = p.get("horizon_years") or 10
    return {"changes": changes, "before": before, "after": after, "monthly_surplus_change": round(gain),
            "score_before": health_score(p)["score"], "score_after": health_score(q)["score"],
            "sip_future_value": round(sip_emi_calc.sip_future_value(max(gain, 0), years, _ret(p))), "years": years}


def tax_compare(p: dict) -> dict[str, Any] | None:
    if p.get("monthly_income") is None:
        return None
    annual = p["monthly_income"] * 12
    new, old = tax.tax_new(annual), tax.tax_old(annual, p.get("used_80c") or 0.0, p.get("used_80d") or 0.0)
    better = "new" if new.total_tax <= old.total_tax else "old"
    return {"better": better, "saving": round(abs(new.total_tax - old.total_tax)), "new_tax": new.total_tax, "old_tax": old.total_tax}


# ── profile completeness & the "based on" line ───────────────────────────
def completeness(p: dict) -> dict[str, Any]:
    def known(f: str) -> bool:
        if f == "city":
            return p.get("city") is not None or p.get("city_tier") is not None
        if f == "loans":
            return p.get("loans") is not None or p.get("existing_emi") is not None
        return p.get(f) is not None
    missing = [f for f in CORE_FIELDS if not known(f)]
    return {"pct": round(100 * (len(CORE_FIELDS) - len(missing)) / len(CORE_FIELDS)), "missing": missing}


def inr(x: float) -> str:
    x = abs(x) if x is not None else 0
    if x >= 1e7:
        return f"₹{x / 1e7:.1f}Cr"
    if x >= 1e5:
        return f"₹{x / 1e5:.1f}L"
    return f"₹{x / 1e3:.0f}k" if x >= 1e3 else f"₹{x:.0f}"


def basis_line(p: dict, used_fields: list[str]) -> str:
    s = snapshot(p)
    parts = {
        "income": f"income {inr(p['monthly_income'])}/mo" if p.get("monthly_income") is not None else None,
        "expenses": f"spend {inr(total_expenses(p))}/mo" if total_expenses(p) is not None else None,
        "emi": f"EMI {inr(total_emi(p))}" if total_emi(p) is not None else None,
        "surplus": f"surplus {inr(s['monthly_surplus'])}/mo" if s["monthly_surplus"] is not None else None,
        "emergency": f"emergency fund {s['emergency_months']:.1f} mo" if s["emergency_months"] is not None else None,
        "age": f"age {p['age']}" if p.get("age") is not None else None,
        "liquid": f"liquid savings {inr(s['liquid'])}" if s["liquid"] is not None else None,
        "risk": f"{p['risk_tolerance'].lower()} risk" if p.get("risk_tolerance") else None,
    }
    used = ", ".join(t for f in used_fields if (t := parts.get(f)))
    return f"Based on your profile: {used or 'not much yet'} · profile {completeness(p)['pct']}% complete"
