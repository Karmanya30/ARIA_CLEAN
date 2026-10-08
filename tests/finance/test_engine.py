"""modules/finance/engine.py -- pure functions, known values."""
import time

import pytest

from modules.finance import engine, sip_emi_calc, tax

P = {
    "age": 30, "dependents": 1, "monthly_income": 100_000, "city_tier": 1,
    "expenses": {"food": 15_000, "rent": 25_000, "entertainment": 5_000, "other": 5_000},
    "assets": {"cash": 100_000, "fd": 200_000, "mf": 200_000, "gold": 50_000},
    "loans": [{"kind": "car", "emi": 10_000, "rate_pct": 9.5, "months_left": 36}],
    "term_cover": 10_000_000, "health_cover": 1_000_000, "risk_tolerance": "Moderate",
}


def test_outstanding_balance_formula_and_explicit_override():
    assert engine.outstanding({"emi": 10_000, "rate_pct": 12, "months_left": 12}) == pytest.approx(112_550.8, abs=1)
    assert engine.outstanding({"emi": 10_000, "rate_pct": 0, "months_left": 12}) == 120_000
    assert engine.outstanding({"emi": 10_000, "outstanding": 5}) == 5


def test_snapshot_values():
    s = engine.snapshot(P)
    assert s["monthly_surplus"] == 40_000 and s["savings_rate"] == 0.4 and s["foir"] == 0.1
    assert s["liquid"] == 400_000 and s["emergency_months"] == pytest.approx(400_000 / 60_000, abs=0.1)
    assert s["net_worth"] == pytest.approx(550_000 - engine.outstanding(P["loans"][0]), abs=1)


def test_snapshot_unknown_stays_none_and_falls_back_to_legacy_column():
    s = engine.snapshot({"monthly_income": 50_000, "emergency_fund_months": 3.0})
    assert s["net_worth"] is None and s["monthly_surplus"] is None and s["emergency_months"] == 3.0


@pytest.mark.parametrize("income,verdict", [(30_000, "yes"), (24_000, "stretch"), (20_000, "no")])
def test_foir_verdict_boundaries(income, verdict):
    # personal loan 3y at 13%: EMI on 0.8 * 400k; no expenses/assets so only FOIR decides
    r = engine.afford_purchase({"monthly_income": income}, 400_000)
    assert r["verdict"] == verdict
    assert r["numbers"]["emi"] == round(sip_emi_calc.emi(320_000, 13.0, 3))


def test_car_case_flags_heavy_emi_and_thin_emergency_cover():
    r = engine.afford_purchase(P, 1_500_000, "car")
    assert r["numbers"]["rate_pct"] == 9.5 and r["numbers"]["years"] == 5
    assert r["verdict"] != "yes" and any("15%" in x for x in r["reasons"])


def test_health_score_range_and_renormalisation():
    full = engine.health_score(P)
    assert 0 <= full["score"] <= 100 and len(full["breakdown"]) == 8
    assert sum(b["weight"] for b in full["breakdown"]) == 100
    sparse = engine.health_score({"monthly_income": 100_000, "expenses": {"food": 20_000, "other": 0}, "loans": []})
    unknown = [b for b in sparse["breakdown"] if b["sub"] is None]
    assert unknown and 0 <= sparse["score"] <= 100
    savings = next(b for b in sparse["breakdown"] if b["name"] == "Savings rate")
    assert savings["sub"] == 1.0  # 80% saved


def test_retirement_corpus():
    r = engine.retirement({"age": 30, "expenses": {"other": 50_000}, "risk_tolerance": "Moderate"})
    annual = 50_000 * 12 * 1.06 ** 30
    assert r["corpus"] == round(annual / 0.035) and r["years_to_retire"] == 30
    assert r["sip_needed"] == round(sip_emi_calc.sip_required(r["corpus"], 30, 10.0))


def test_goal_plan_inflates_and_uses_sip_math():
    g = engine.goal_plan({"name": "College", "target": 1_000_000, "years": 10, "saved": 0}, {"risk_tolerance": "Aggressive"})
    assert g["future_target"] == round(1_000_000 * 1.08 ** 10)  # education inflation
    assert g["sip_needed"] == round(sip_emi_calc.sip_required(1_000_000 * 1.08 ** 10, 10, 12.0))


def test_what_if_cut_raises_surplus_and_score():
    r = engine.what_if(P, {"expenses.entertainment": -5_000})
    assert r["monthly_surplus_change"] == 5_000 and r["after"]["monthly_surplus"] == 45_000
    assert r["sip_future_value"] > 0 and P["expenses"]["entertainment"] == 5_000  # original untouched


def test_tax_compare_matches_tax_module():
    r = engine.tax_compare({"monthly_income": 150_000, "used_80c": 150_000})
    assert r["new_tax"] == tax.tax_new(1_800_000).total_tax
    assert r["old_tax"] == tax.tax_old(1_800_000, 150_000, 0).total_tax
    assert r["better"] == ("new" if r["new_tax"] <= r["old_tax"] else "old")


def test_completeness_and_basis_line():
    c = engine.completeness({"age": 30, "loans": [], "city_tier": 1})
    assert c["pct"] == round(300 / 14) and "age" not in c["missing"] and "loans" not in c["missing"] and "city" not in c["missing"]
    line = engine.basis_line({"monthly_income": 120_000, "loans": [{"emi": 15_000}]}, ["income", "emi"])
    assert line.startswith("Based on your profile: income ₹1.2L/mo, EMI ₹15k") and "% complete" in line


def test_engine_is_fast():
    start = time.perf_counter()
    for _ in range(1000):
        engine.health_score(P)
        engine.afford_purchase(P, 1_500_000, "car")
    assert time.perf_counter() - start < 0.5


def test_rent_alone_is_not_known_spending():
    p = {"monthly_income": 120_000, "expenses": {"rent": 25_000}}
    assert engine.total_expenses(p) is None and engine.snapshot(p)["monthly_surplus"] is None
    assert engine.total_expenses({**p, "expenses": {"rent": 25_000, "other": 40_000}}) == 65_000


def test_inr_keeps_meaningful_digits():
    assert [engine.inr(x) for x in (8500, 12345, 123000, 95000, 120000, 200000, 950)] == ["₹8.5k", "₹12.3k", "₹1.23L", "₹95k", "₹1.2L", "₹2L", "₹950"]


def test_sip_capacity_tiers_buffer_and_emergency_fund():
    p = {"monthly_income": 95000, "existing_emi": 8500, "expenses": {"other": 50000}, "assets": {"cash": 100000}}
    r = engine.sip_capacity(p)
    assert r["surplus"] == 36500 and [t["amount"] for t in r["tiers"]] == [10950, 18250, 25550]
    assert max(t["amount"] for t in r["tiers"]) <= 0.9 * 36500
    assert r["first_build_emergency_fund"] and r["verdict"] == "build_emergency_fund_first"
    assert r["emergency_shortfall_amount"] == round(4.3 * 58500)
    assert engine.sip_capacity({**p, "expenses": {"other": 120000}})["verdict"] == "no_surplus"
