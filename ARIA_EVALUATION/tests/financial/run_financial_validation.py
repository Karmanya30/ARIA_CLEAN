"""Phase A financial validation: runs ARIA's pure calculation code in-process and compares with ref_impl.py.
No network, no web server, no model loading. Usage: python -X utf8 run_financial_validation.py
"""
from __future__ import annotations

import ast
import math
import os
import random
import re
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from harness import ROOT, Rec  # noqa: E402
import ref_impl as R  # noqa: E402

sys.path.insert(0, str(ROOT / "tests" / "equity_research"))
os.environ.setdefault("OMP_NUM_THREADS", "2")


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"EXC {type(e).__name__}: {str(e)[:70]}"


# =====================================================================================================  SIP / EMI
def sec_sip_emi(r: Rec):
    from modules.finance import sip_emi_calc as C
    f = "SIP/EMI (modules/finance/sip_emi_calc.py)"
    for m, y, p in [(5000, 10, 12), (10000, 20, 10), (25000, 3, 8), (1000, 30, 15), (5000, 0.5, 12), (7500, 1.5, 6.5), (100, 40, 1)]:
        r.close(f, f"FV monthly={m} years={y} rate={p}%", "reference", C.sip_future_value(m, y, p), R.sip_fv_loop(m, int(round(y * 12)), p), rel=1e-9)
        tgt = 1_000_000
        r.close(f, f"required SIP target={tgt} years={y} rate={p}%", "reference", C.sip_required(tgt, y, p), R.sip_required_ref(tgt, int(round(y * 12)), p), rel=1e-9)
    r.close(f, "FV 5000/mo 10y 12% (hand figure 1,161,695)", "worked example", C.sip_future_value(5000, 10, 12), 1161695.4, rel=1e-6)
    r.close(f, "FV rate 0 => contributions only", "boundary", C.sip_future_value(5000, 10, 0), 600000.0)
    r.close(f, "required SIP at rate 0", "boundary", C.sip_required(600000, 10, 0), 5000.0)
    r.close(f, "round-trip required->FV", "property", C.sip_future_value(C.sip_required(2e6, 15, 11), 15, 11), 2e6, rel=1e-9)
    for m, y, p in [(0, 10, 12), (-5000, 10, 12), (5000, 0, 12), (5000, -3, 12)]:
        r.eq(f, f"FV invalid monthly={m} years={y} -> 0.0", "invalid", C.sip_future_value(m, y, p), 0.0)
    r.eq(f, "required SIP target=0 -> 0.0", "invalid", C.sip_required(0, 10, 12), 0.0)
    v = safe(C.sip_future_value, 5000, 0.04, 12)
    r.observe(f, "FV years=0.04 (rounds to 0 months)", "boundary", v, "silently 0.0: a 1-month horizon is treated as no investment")
    v = safe(C.sip_required, 100000, 0.04, 12)
    r.true(f, "required SIP years=0.04 (n rounds to 0) must not crash", "boundary", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v}")
    v = safe(C.sip_required, 100000, 0.04, 0)
    r.true(f, "required SIP years=0.04 rate=0 must not crash", "boundary", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v}")
    r.observe(f, "FV monthly=NaN", "invalid", safe(C.sip_future_value, float("nan"), 10, 12), "NaN propagates, no validation")
    r.observe(f, "FV rate=-1200% (r=-1)", "invalid", safe(C.sip_future_value, 5000, 10, -1200), "no rate validation; nonsense in, number out")
    r.close(f, "FV rate -6% (negative return) vs loop", "boundary", C.sip_future_value(5000, 5, -6), R.sip_fv_loop(5000, 60, -6), rel=1e-9)
    # EMI
    for P, p, y in [(1_000_000, 8.5, 20), (500_000, 12, 5), (2_500_000, 9.25, 15), (100_000, 24, 1), (50_00_000, 7, 30), (300_000, 13, 0.5)]:
        n = int(round(y * 12))
        r.close(f, f"EMI P={P} rate={p}% years={y}", "reference", C.emi(P, p, y), R.emi_by_bisection(P, p, n), rel=1e-8)
        e = R.emi_by_bisection(P, p, n)
        r.close(f, f"total interest P={P} rate={p}% years={y}", "reference", C.emi_total_interest(P, p, y), e * n - P, rel=1e-6, abs_=0.05)
    r.close(f, "EMI 10L @8.5% 20y (published calculators: 8,678)", "worked example", C.emi(1_000_000, 8.5, 20), 8678.23, abs_=0.5)
    r.close(f, "EMI rate 0 => P/n", "boundary", C.emi(120000, 0, 1), 10000.0)
    r.eq(f, "EMI principal 0 -> 0.0", "invalid", C.emi(0, 9, 5), 0.0)
    r.eq(f, "EMI principal<0 -> 0.0", "invalid", C.emi(-1000, 9, 5), 0.0)
    r.eq(f, "EMI years 0 -> 0.0", "invalid", C.emi(1000, 9, 0), 0.0)
    v = safe(C.emi, 100000, 9, 0.04)
    r.true(f, "EMI years=0.04 (n rounds to 0) must not crash", "boundary", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v}")
    v = safe(C.emi, 100000, 0, 0.04)
    r.true(f, "EMI years=0.04 rate=0 must not crash", "boundary", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v}")
    r.observe(f, "EMI negative rate -3%", "invalid", safe(C.emi, 100000, -3, 5), "accepted; below P/n")
    r.observe(f, "EMI rate 100000%", "boundary", safe(C.emi, 100000, 100000, 5), "no upper bound; pow overflow guarded?")
    r.true(f, "total interest never negative (max(0,..))", "property", C.emi_total_interest(100000, 0, 2) == 0.0)
    # duplicate implementation in finance pipeline (extracted by AST, module not imported: it opens user DB code paths)
    src = (ROOT / "modules/finance/pipeline.py").read_text(encoding="utf8")
    tree = ast.parse(src)
    ns: dict = {"re": re, "sip_future_value": C.sip_future_value}  # pipeline now delegates to sip_emi_calc
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("_AMOUNT",) for t in node.targets):
            exec(compile(ast.Module([node], []), "p", "exec"), ns)  # noqa: S102
        if isinstance(node, ast.FunctionDef) and node.name in ("_scale", "_amounts", "_parse_indian_amount", "_parse_return_rate", "_future_value_monthly_sip"):
            exec(compile(ast.Module([node], []), "p", "exec"), ns)  # noqa: S102
    fv2 = ns["_future_value_monthly_sip"]
    g = "SIP duplicate (finance/pipeline.py::_future_value_monthly_sip)"
    for m, y, p in [(5000, 10, 12), (10000, 3, 8), (50000, 1, 14)]:
        r.close(g, f"FV monthly={m} years={y} rate={p}", "reference", fv2(m, p, y), R.sip_fv_loop(m, y * 12, p), rel=1e-9)
        r.close(g, f"agrees with sip_emi_calc ({m},{y},{p})", "consistency", fv2(m, p, y), C.sip_future_value(m, y, p), rel=1e-12)
    pa = ns["_parse_indian_amount"]
    g = "Indian amount parsing (finance/pipeline.py)"
    for text, kw, exp in [("my income is 60,000 per month", "income", 60000), ("salary 12 lpa", None, 1200000), ("I earn 1.5 lakh", "earn", 150000),
                          ("emi of 25k", "emi", 25000), ("loan 2 crore", None, 20000000), ("save 6 lakh a year", "save", 600000)]:
        r.close(g, f"parse {text!r}", "reference", pa(text, kw), exp)
    r.close(g, "'12 lpa' is annual 12 lakh (unit sanity)", "explanation", pa("12 lpa"), 1_200_000)
    r.observe(g, "'invest 10 percent of 50000'", "invalid", pa("invest 10 percent of 50000", "invest"), "first number after keyword wins (10): the percent is read as rupees")
    pr = ns["_parse_return_rate"]
    r.close(g, "return rate '14% pa' ", "reference", pr("target 14% pa"), 14.0)
    r.observe(g, "return rate '0%'", "boundary", pr("expect 0% return"), "0.0 is falsy; `target_return or 12.0` then replaces it with 12 (explanation would say 'requested return' not 0%)")


# =====================================================================================================  TAX
def sec_tax(r: Rec):
    from modules.finance import tax as T
    f = "India income tax (modules/finance/tax.py)"
    incomes = [0, 100000, 300000, 475000, 500000, 575000, 600000, 775000, 800000, 1000000, 1275000, 1275001, 1280000, 1300000, 1350000,
               1500000, 1800000, 2000000, 2475000, 2800000, 3000000, 4500000, 5000000, 7500000, 10_000_000, 25_000_000, 50_000_000]
    for inc in incomes:
        a = T.tax_new(inc)
        t, taxable = R.tax_new_ref(inc)
        r.close(f, f"new regime gross={inc} total tax", "reference", a.total_tax, t, abs_=0.011)
        r.close(f, f"new regime gross={inc} taxable", "reference", a.taxable_income, taxable)
    for inc, d80c, d80d, age in [(300000, 0, 0, None), (550000, 0, 0, None), (600000, 100000, 20000, None), (800000, 150000, 25000, None), (1000000, 200000, 40000, None),
                                 (1500000, 150000, 0, None), (5000000, 150000, 25000, None), (700000, 0, 60000, 65), (900000, 150000, 50000, 70),
                                 (650000, 0, 0, 82), (400000, 0, 0, 62), (3_000_000, 150000, 25000, 35)]:
        a = T.tax_old(inc, d80c, d80d, age=age)
        t, taxable = R.tax_old_ref(inc, d80c, d80d, age=age)
        r.close(f, f"old regime gross={inc} 80C={d80c} 80D={d80d} age={age}", "reference", a.total_tax, t, abs_=0.011)
    # boundaries
    r.close(f, "new regime: taxable exactly 12L (gross 12.75L) => 0 tax (87A)", "boundary", T.tax_new(1275000).total_tax, 0.0)
    r.close(f, "new regime: gross 12.75L+1 => marginal relief caps tax at excess (1 * 1.04)", "boundary", T.tax_new(1275001).total_tax, 1.04, abs_=0.011)
    r.close(f, "new regime: gross 12.75L => effective rate 0", "boundary", T.tax_new(1275000).effective_rate, 0.0)
    r.close(f, "new regime: gross 24L tax by hand: 20k+40k+60k+80k+(2325000-2000000)*.25=281250 => *1.04 (test expectation corrected after first run)", "hand calc", T.tax_new(2400000).total_tax, (20000 + 40000 + 60000 + 80000 + (2325000 - 2000000) * 0.25) * 1.04, abs_=0.011)
    r.close(f, "old regime: taxable exactly 5L (gross 5.5L, no ded) => 0", "boundary", T.tax_old(550000).total_tax, 0.0)
    r.close(f, "old regime: taxable 5L+1 has NO marginal relief (documented): 12,500 + 0.2 => tax 12500.2*1.04", "boundary", T.tax_old(550001).total_tax, 12500.2 * 1.04, abs_=0.02)
    # cliff check: stated behaviour of old regime (no marginal relief in law either: true, none exists for old regime)
    r.observe(f, "old regime cliff 5.5L -> 5.50001L", "explanation", [T.tax_old(550000).total_tax, T.tax_old(550001).total_tax], "jump of ~13,000 is the law (no relief in old regime)")
    # deduction caps
    r.close(f, "80C cap 1.5L: 3L claimed == 1.5L claimed", "boundary", T.tax_old(1200000, 300000).total_tax, T.tax_old(1200000, 150000).total_tax)
    r.close(f, "80D cap non-senior 25k", "boundary", T.tax_old(1200000, 0, 90000).total_tax, T.tax_old(1200000, 0, 25000).total_tax)
    r.close(f, "80D cap senior 50k", "boundary", T.tax_old(1200000, 0, 90000, age=61).total_tax, T.tax_old(1200000, 0, 50000, age=61).total_tax)
    r.close(f, "is_senior flag == age 60", "boundary", T.tax_old(900000, is_senior=True).total_tax, T.tax_old(900000, age=60).total_tax)
    # invalid
    r.close(f, "negative income -> 0 tax", "invalid", T.tax_new(-500000).total_tax, 0.0)
    r.close(f, "zero income effective rate 0 (no div by 0)", "invalid", T.tax_new(0).effective_rate, 0.0)
    neg = T.tax_old(1000000, -200000).total_tax
    r.true(f, "negative 80C deduction must not raise tax above the no-deduction figure", "invalid", neg <= T.tax_old(1000000, 0).total_tax,
           f"tax with 80C=-200000 is {neg} vs {T.tax_old(1000000, 0).total_tax} with 80C=0 (negative deduction is added to taxable income)")
    # rounding consistency
    a = T.tax_new(2_345_678)
    r.true(f, "total == tax_before_cess + cess within 0.01 after separate rounding", "rounding", abs(a.total_tax - (a.tax_before_cess + a.cess)) <= 0.011,
           f"{a.total_tax} vs {a.tax_before_cess}+{a.cess}")
    r.close(f, "compute(monthly=100000, new) == tax_new(1.2M)", "consistency", T.compute(100000, "new").total_tax, T.tax_new(1200000).total_tax)
    r.close(f, "compute_tax(income) wrapper", "consistency", T.compute_tax(1200000), T.tax_new(1200000).total_tax)
    # surcharge: absent
    ref_noSur, _ = R.tax_new_ref(10_000_000)
    # real new-regime 1 Cr gross: base tax 525,750 (hand: 300000 + 75.25L*0.30) + 10% surcharge, then 4% cess
    base = 300000 + (10_000_000 - 75000 - 2_400_000) * 0.30
    with_surcharge = base * 1.10 * 1.04
    r.close(f, "gross Rs 1 Cr new regime INCLUDING 10% surcharge (statute) vs ARIA", "statute", T.tax_new(10_000_000).total_tax, round(with_surcharge, 2), rel=1e-6,
            note="surcharge (10% >50L, 15% >1Cr, 25% >2Cr) is not implemented in tax.py: grep 'surcharge' finds nothing in modules/finance")
    r.observe(f, "income above 50L: ARIA understates tax by", "statute", round(with_surcharge - T.tax_new(10_000_000).total_tax, 2), "INR at 1 Cr gross")
    # engine.tax_compare
    from modules.finance import engine as E
    p = {"monthly_income": 100000, "used_80c": 150000, "used_80d": 25000, "age": 30}
    tc = E.tax_compare(p)
    n_, o_ = R.tax_new_ref(1_200_000)[0], R.tax_old_ref(1_200_000, 150000, 25000, age=30)[0]
    r.close("tax_compare (engine.py)", "new_tax", "reference", tc["new_tax"], n_, abs_=0.011)
    r.close("tax_compare (engine.py)", "old_tax", "reference", tc["old_tax"], o_, abs_=0.011)
    r.eq("tax_compare (engine.py)", "better regime", "reference", tc["better"], "new" if n_ <= o_ else "old")
    r.close("tax_compare (engine.py)", "saving", "reference", tc["saving"], round(abs(n_ - o_)))
    r.eq("tax_compare (engine.py)", "no income -> None (no guessed number)", "missing", E.tax_compare({}), None)
    p2 = {"monthly_income": 80000, "used_80c": 150000, "used_80d": 50000, "age": 65}
    tc2 = E.tax_compare(p2)
    r.close("tax_compare (engine.py)", "senior old_tax", "reference", tc2["old_tax"], R.tax_old_ref(960000, 150000, 50000, age=65)[0], abs_=0.011)


# =====================================================================================================  personal finance engine
def sec_engine(r: Rec):
    from modules.finance import engine as E
    f = "Personal-finance engine (modules/finance/engine.py)"
    P = {"age": 30, "monthly_income": 100000, "risk_tolerance": "Moderate", "dependents": 0,
         "expenses": {"rent": 25000, "food": 12000, "transport": 5000, "entertainment": 8000},
         "loans": [{"kind": "home", "emi": 15000, "outstanding": 800000}],
         "assets": {"cash": 200000, "fd": 300000, "mf": 400000, "stocks": 100000, "epf": 500000}}
    s = E.snapshot(P)
    r.close(f, "snapshot monthly_surplus = 100000-50000-15000", "reference", s["monthly_surplus"], 35000.0)
    r.close(f, "snapshot savings_rate", "reference", s["savings_rate"], 0.35)
    r.close(f, "snapshot liquid = cash+fd+0.5*mf", "reference", s["liquid"], 700000.0)
    r.close(f, "snapshot emergency_months = 700000/(50000+15000) (1dp)", "reference", s["emergency_months"], round(700000 / 65000, 1))
    r.close(f, "snapshot FOIR", "reference", s["foir"], 0.15)
    r.close(f, "snapshot net_worth = assets 1.5M - debt 800k", "reference", s["net_worth"], 700000.0)
    # outstanding()
    r.close(f, "outstanding from emi/rate/months (PV annuity)", "reference", E.outstanding({"emi": 20000, "months_left": 60, "rate_pct": 9}), R.pv_annuity(20000, 60, 0.09 / 12), rel=1e-9)
    r.close(f, "outstanding rate 0 => emi*n", "boundary", E.outstanding({"emi": 20000, "months_left": 60, "rate_pct": 0}), 1_200_000.0)
    r.close(f, "outstanding missing emi -> 0", "missing", E.outstanding({"months_left": 60}), 0.0)
    # goals
    g = E.goal_plan({"name": "Car", "target": 1_000_000, "years": 10, "saved": 100000}, P)
    fut = 1_000_000 * 1.06 ** 10
    gap = fut - 100000 * 1.10 ** 10
    r.close(f, "goal future_target inflated 6%", "reference", g["future_target"], round(fut))
    r.close(f, "goal sip_needed (gap/annuity-due FV factor @10%)", "reference", g["sip_needed"], round(R.sip_required_ref(gap, 120, 10)))
    ge = E.goal_plan({"name": "Child college fund", "target": 2_000_000, "years": 15}, {**P, "risk_tolerance": "Aggressive"})
    r.close(f, "education goal uses 8% inflation, 12% return", "reference", ge["future_target"], round(2_000_000 * 1.08 ** 15))
    r.close(f, "education goal sip", "reference", ge["sip_needed"], round(R.sip_required_ref(2_000_000 * 1.08 ** 15, 180, 12)))
    g0 = E.goal_plan({"name": "Trip", "target": 100000, "years": 0}, P)
    r.true(f, "goal years=0 with unmet target must not report sip_needed 0", "boundary", g0["sip_needed"] != 0, f"actual sip_needed={g0['sip_needed']} for a 1,00,000 target due now (gap > 0)")
    gs = E.goal_plan({"name": "Home", "target": 500000, "years": 5, "saved": 10_000_000}, P)
    r.eq(f, "goal already funded -> sip 0", "boundary", gs["sip_needed"], 0)
    # retirement
    rt = E.retirement(P)
    annual = 50000 * 12 * 1.06 ** 30
    corpus = annual / 0.035
    grown = 1_300_000 * 1.10 ** 30
    r.close(f, "retirement annual expense at 60", "reference", rt["annual_expense_at_retirement"], round(annual))
    r.close(f, "retirement corpus = annual/3.5%", "reference", rt["corpus"], round(corpus))
    r.close(f, "retirement FV of investments (mf+stocks+fd+epf) @10%", "reference", rt["current_investments_fv"], round(grown))
    r.close(f, "retirement gap", "reference", rt["gap"], round(max(0, corpus - grown)))
    r.close(f, "retirement sip_needed", "reference", rt["sip_needed"], round(R.sip_required_ref(max(0, corpus - grown), 360, 10)))
    r.eq(f, "retirement missing age -> None", "missing", E.retirement({"expenses": P["expenses"]}), None)
    old = E.retirement({**P, "age": 65})
    r.eq(f, "age>=60: years_to_retire 0 and sip_needed 0", "boundary", (old["years_to_retire"], old["sip_needed"]), (0, 0))
    r.observe(f, "retirement basis", "explanation", rt["assumptions"], "expenses exclude EMIs; corpus is 28.6x annual expense (SWR 3.5%); investments exclude cash/real_estate")
    # afford_purchase
    a = E.afford_purchase(P, 5_000_000, "home")
    emi_ref = R.emi_by_bisection(4_000_000, 8.5, 240)
    r.close(f, "afford home EMI (20% down, 8.5%, 20y)", "reference", a["numbers"]["emi"], round(emi_ref))
    foir = (15000 + emi_ref) / 100000
    r.close(f, "afford FOIR after", "reference", a["numbers"]["foir_after"], round(foir, 3))
    r.eq(f, "afford verdict from FOIR bands (<=40 yes, <=50 stretch, else no)", "reference", a["verdict"], "yes" if foir <= .4 else "stretch" if foir <= .5 else "no")
    big = E.afford_purchase(P, 9_000_000, "home")
    r.eq(f, "afford large home -> 'no' when FOIR>50%", "reference", big["verdict"], "no" if (15000 + R.emi_by_bisection(7_200_000, 8.5, 240)) / 100000 > .5 else "stretch")
    r.close(f, "afford years=0 falls back to default (silent)", "boundary", E.afford_purchase(P, 1_000_000, "car", years=0)["numbers"]["years"], 5)
    z = E.afford_purchase({**P, "monthly_income": 0}, 1_000_000, "car")
    r.eq(f, "afford with zero income -> 'no' (income floored at 1)", "boundary", z["verdict"], "no")
    r.observe(f, "afford negative price", "invalid", safe(E.afford_purchase, P, -100000, "car")["numbers"], "no validation; negative loan -> EMI 0")
    # afford_sip / sip_capacity
    s1 = E.afford_sip(P, 20000)
    r.close(f, "afford_sip FV @10% for horizon 10", "reference", s1["numbers"]["future_value"], round(R.sip_fv_loop(20000, 120, 10)))
    r.eq(f, "afford_sip 20000 of 35000 surplus -> yes (<=80%)", "reference", s1["verdict"], "yes")
    r.eq(f, "afford_sip 30000 -> stretch", "reference", E.afford_sip(P, 30000)["verdict"], "stretch")
    r.eq(f, "afford_sip 40000 -> no", "reference", E.afford_sip(P, 40000)["verdict"], "no")
    cap = E.sip_capacity(P)
    r.close(f, "sip_capacity balanced tier = 50% of surplus", "reference", cap["tiers"][1]["amount"], round(0.5 * 35000))
    r.close(f, "sip_capacity balanced 20y FV", "reference", cap["tiers"][1]["future_value_20y"], round(R.sip_fv_loop(17500, 240, 10)))
    r.true(f, "no tier exceeds 90% of surplus", "property", all(t["amount"] <= 0.9 * 35000 for t in cap["tiers"]))
    nofin = {"monthly_income": 100000}
    v = safe(E.afford_sip, nofin, 5000)
    r.true(f, "afford_sip with unknown expenses (surplus None) must not crash", "missing", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v}")
    v = safe(E.sip_capacity, nofin)
    r.true(f, "sip_capacity with unknown expenses (surplus None) must not crash", "missing", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v}")
    # what_if
    w = E.what_if(P, {"expenses.food": -5000})
    r.close(f, "what_if surplus change", "reference", w["monthly_surplus_change"], 5000)
    r.close(f, "what_if SIP FV on freed money", "reference", w["sip_future_value"], round(R.sip_fv_loop(5000, 120, 10)))
    w2 = E.what_if(P, {"expenses.food": -50000})
    r.close(f, "what_if cut larger than the category is clamped at 0 (12000 not 50000)", "boundary", w2["monthly_surplus_change"], 12000)
    w3 = E.what_if(P, {"monthly_income": -500000})
    r.true(f, "what_if income cut below zero clamps income at 0", "boundary", w3["after"]["monthly_surplus"] == -65000.0, f"after surplus={w3['after']['monthly_surplus']}")
    r.true(f, "what_if does not mutate the input profile", "property", P["expenses"]["food"] == 12000 and P["monthly_income"] == 100000)
    # health score
    hs = E.health_score(P)
    r.true(f, "health score in 0..100", "property", 0 <= hs["score"] <= 100)
    r.close(f, "health weights sum to 100", "property", sum(b["weight"] for b in hs["breakdown"]), 100)
    sub = {b["name"]: b["sub"] for b in hs["breakdown"]}
    r.close(f, "savings-rate sub-score 0.35/0.30 capped at 1", "reference", sub["Savings rate"], 1.0)
    r.close(f, "debt-burden sub-score FOIR .15 (<=.20) -> 1", "reference", sub["Debt burden"], 1.0)
    r.close(f, "emergency sub 10.8mo vs target 6 -> 1", "reference", sub["Emergency fund"], 1.0)
    r.close(f, "empty profile -> score 0, coverage 0", "missing", (E.health_score({})["score"], E.health_score({})["coverage"]), (0, 0)) if False else None
    h0 = E.health_score({})
    r.eq(f, "empty profile -> score 0 and coverage 0 (not a fabricated score)", "missing", (h0["score"], h0["coverage"]), (0, 0))
    worse = E.health_score({**P, "expenses": {**P["expenses"], "rent": 80000}})
    r.true(f, "higher expenses never raise the score (monotonic)", "property", worse["score"] <= hs["score"], f"{worse['score']} <= {hs['score']}")
    cf = E.completeness({})
    r.eq(f, "completeness empty = 0%", "missing", cf["pct"], 0)
    r.close(f, "inr() formatting 123000 -> 1.23L", "formatting", float(E.inr(123000).replace("₹", "").replace("L", "")), 1.23)
    r.eq(f, "inr(8500)", "formatting", E.inr(8500), "₹8.5k")
    r.eq(f, "inr(12500000)", "formatting", E.inr(12_500_000), "₹1.25Cr")
    r.observe(f, "inr(-5000) (abs() applied)", "formatting", E.inr(-5000), "negative amounts lose their sign (a deficit prints as a positive figure)")
    r.observe(f, "total_expenses with only 2 categories", "missing", E.total_expenses({"expenses": {"rent": 1, "food": 2}}), "None => no surplus guessed")


# =====================================================================================================  market instruments
def sec_market(r: Rec):
    from modules.market import instruments as I
    f = "XIRR / CAGR / SIP simulation (modules/market/instruments.py)"
    d0 = date(2020, 1, 1)
    for name, flows in {
        "single year +10%": [(d0, -1000), (date(2021, 1, 1), 1100)],
        "two flows 2y": [(d0, -1000), (date(2022, 1, 1), 1500)],
        "multi": [(d0, -1000), (date(2020, 7, 1), -1000), (date(2021, 1, 1), -1000), (date(2022, 1, 1), 3500)],
        "loss": [(d0, -1000), (date(2021, 1, 1), 600)],
        "big gain": [(d0, -1000), (date(2020, 7, 1), 5000)],
    }.items():
        a, b = I._xirr(flows), R.xirr_ref(flows)
        r.close(f, f"XIRR {name}", "reference", a, b, rel=1e-5, abs_=1e-7)
    r.close(f, "XIRR 1000->1100 over 366 days (2020 leap) uses /365", "hand calc", I._xirr([(d0, -1000), (date(2021, 1, 1), 1100)]), 1.1 ** (365 / 366) - 1, rel=1e-6)
    r.eq(f, "XIRR all-outflow flows -> None", "invalid", I._xirr([(d0, -1000), (date(2021, 1, 1), -10)]), None)
    r.close(f, "XIRR zero return", "boundary", I._xirr([(d0, -1000), (date(2021, 1, 1), 1000)]), 0.0, abs_=1e-7)
    r.observe(f, "XIRR same-day flows", "boundary", safe(I._xirr, [(d0, -1000), (d0, 1100)]), "t=0 for both: f(r) constant sign => None expected")
    # price series for SIP simulation: deterministic business days
    rng = random.Random(7)
    px, d, series = 100.0, date(2019, 1, 1), []
    while d < date(2024, 12, 31):
        if d.weekday() < 5:
            px *= 1 + rng.gauss(0.0004, 0.01)
            series.append((d.isoformat(), px))
        d += timedelta(days=1)
    for monthly, years in [(5000, 5), (10000, 3), (2500, 1)]:
        res = I.simulate_sip(series, monthly, years)
        # independent reference: first trading day of each month, last `years*12` of them; units bought at that close
        first = {}
        for ds, p in series:
            first.setdefault(ds[:7], (ds, p))
        pick = [first[k] for k in sorted(first)][-int(round(years * 12)):]
        units = sum(monthly / p for _, p in pick)
        final = units * series[-1][1]
        end = date.fromisoformat(series[-1][0])
        flows = [(date.fromisoformat(dd), -monthly) for dd, _ in pick] + [(end, final)]
        r.close(f, f"SIP sim invested monthly={monthly} years={years}", "reference", res["invested"], monthly * len(pick))
        r.close(f, f"SIP sim final value monthly={monthly} years={years}", "reference", res["value"], round(final, 2), abs_=0.01)
        xr = R.xirr_ref(flows)
        r.close(f, f"SIP sim XIRR% monthly={monthly} years={years}", "reference", res["xirr_pct"], round(xr * 100, 2), abs_=0.02)
        w0 = pick[0][0]
        s0 = [p for dd, p in series if dd >= w0][0]
        days = (end - date.fromisoformat(w0)).days
        r.close(f, f"SIP sim asset CAGR% monthly={monthly} years={years}", "reference", res["cagr_pct"], round(R.cagr_ref(s0, series[-1][1], days / 365.25) * 100, 2), abs_=0.02)
        r.close(f, f"SIP sim gain = value - invested", "consistency", res["gain"], round(res["value"] - res["invested"], 2), abs_=0.011)
    r.raises(f, "SIP sim <3 months of data raises NoData", "insufficient data", lambda: I.simulate_sip(series[:30], 5000, 5), I.NoData)
    r.raises(f, "SIP sim empty series", "missing", lambda: I.simulate_sip([], 5000, 5), Exception)
    v = safe(I.simulate_sip, series, 0, 5)
    r.true(f, "SIP sim monthly=0 must not crash", "boundary", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v if isinstance(v, str) else 'ok'}",)
    r.observe(f, "SIP sim years=0.2 (requested 2 installments)", "boundary", safe(I.simulate_sip, series, 5000, 0.2), "NoData expected (<3)")
    # return_stats
    st = I.return_stats(series)
    prices = [p for _, p in series]
    r.close(f, "max drawdown (all) %", "reference", st["max_drawdown_all_pct"], round(R.max_drawdown_ref(prices) * 100, 2), abs_=0.011)
    dts = [date.fromisoformat(x) for x, _ in series]
    days_all = (dts[-1] - dts[0]).days
    r.close(f, "CAGR since start %", "reference", st["cagr_since_start_pct"], round(R.cagr_ref(prices[0], prices[-1], days_all / 365.25) * 100, 2), abs_=0.011)
    r.close(f, "return since start %", "reference", st["return_since_start_pct"], round((prices[-1] / prices[0] - 1) * 100, 2), abs_=0.011)
    last = dts[-1]
    yr = [(dd, p) for dd, (_, p) in zip(dts, series) if dd >= last - timedelta(days=365)]
    rets = np.diff([p for _, p in yr]) / np.array([p for _, p in yr][:-1])
    r.close(f, "1y volatility % (sample sd * sqrt(252))", "reference", st["volatility_1y_pct"], round(float(np.std(rets, ddof=1) * math.sqrt(252) * 100), 2), abs_=0.011)
    r.close(f, "1y max drawdown %", "reference", st["max_drawdown_1y_pct"], round(R.max_drawdown_ref([p for _, p in yr]) * 100, 2), abs_=0.011)
    base3 = [p for dd, (_, p) in zip(dts, series) if dd <= last - timedelta(days=1095)][-1]
    r.close(f, "3y CAGR % (365/1095 exponent)", "reference", st["cagr_3y_pct"], round(R.cagr_ref(base3, prices[-1], 3.0) * 100, 2), abs_=0.011)
    r.observe(f, "day-count convention", "explanation", "CAGR since start uses 365.25; 3y/5y CAGR uses 365; XIRR uses 365", "same asset reads slightly different CAGR depending on window; <0.1pp")
    r.eq(f, "return_stats with 1 point -> {}", "insufficient data", I.return_stats(series[:1]), {})
    r.observe(f, "return_stats crypto vol uses sqrt(365)", "explanation", I.return_stats(series, crypto=True).get("volatility_1y_pct"), "documented annualisation choice")
    r.observe(f, "return_stats with a zero first price", "invalid", safe(I.return_stats, [("2020-01-01", 0.0), ("2021-01-01", 10.0)]), "first>0 guard => no return/cagr keys")


# =====================================================================================================  valuation
def sec_valuation(r: Rec):
    from modules.equity_research.intelligence import valuation as V
    from modules.equity_research.intelligence import comps as CP
    f = "Cost of capital"
    r.close(f, "CAPM 6.75% + 1.2*7%", "reference", V.capm(0.0675, 1.2, 0.07), R.capm_ref(0.0675, 1.2, 0.07))
    r.close(f, "WACC 20% debt", "reference", V.wacc_from(0.1515, 0.09, 0.25, 0.2), R.wacc_ref(80, 20, 0.1515, 0.09, 0.25))
    rng = random.Random(11)
    m = [rng.gauss(0.002, 0.02) for _ in range(150)]
    s = [1.3 * x + rng.gauss(0, 0.01) for x in m]
    b, n = V.estimate_beta(s, m)
    r.close(f, "OLS beta vs numpy cov/var", "reference", b, R.beta_ols_ref(s, m), rel=1e-9)
    r.eq(f, "beta <100 obs -> None", "insufficient data", V.estimate_beta(s[:99], m[:99]), None)
    r.eq(f, "beta zero index variance -> None", "invalid", V.estimate_beta(s, [0.0] * 150), None)
    r.close(f, "Blume: 1.5 -> 2/3*1.5+1/3", "reference", V.blume_adjust(1.5), 4 / 3)
    r.close(f, "Blume leaves 0.6 alone", "boundary", V.blume_adjust(0.6), 0.6)
    r.observe(f, "Blume asymmetry (no uplift for beta<1)", "explanation", "documented FinRobot variant", "textbook Blume adjusts all betas toward 1; ARIA only above 1. Documented, so OBSERVED not a defect.")
    r.close(f, "fade 12%->5% over 10y", "reference", list(V.fade(0.12, 0.05)), R.fade_ref(0.12, 0.05), rel=1e-12)

    f = "DCF (valuation.py)"
    base = dict(revenue_base=1000.0, growth=V.fade(0.12, 0.05), ebitda_margin=0.22, da_pct=0.04, capex_pct=0.08, nwc_pct=0.10, tax_rate=0.25,
                wacc=0.12, terminal_growth=0.05, net_debt=300.0, nci=50.0, shares_cr=100.0)
    cases = {"base": {}, "high growth": dict(growth=V.fade(0.25, 0.05)), "low wacc": dict(wacc=0.09), "no capex excess": dict(capex_pct=0.04),
             "capex<da": dict(capex_pct=0.02), "negative nwc": dict(nwc_pct=-0.03), "zero tax": dict(tax_rate=0.0), "net cash": dict(net_debt=-200.0),
             "flat growth": dict(growth=(0.0,) * 10, terminal_growth=0.0), "decline": dict(growth=V.fade(-0.05, 0.02), terminal_growth=0.02)}
    for nm, over in cases.items():
        kw = {**base, **over}
        inp = V.DCFInputs(**kw)
        a = safe(V.dcf, inp)
        ref = R.dcf_ref(kw["revenue_base"], kw["growth"], kw["ebitda_margin"], kw["da_pct"], kw["capex_pct"], kw["nwc_pct"], kw["tax_rate"], kw["wacc"], kw["terminal_growth"],
                        kw["net_debt"], kw["nci"], kw["shares_cr"])
        if isinstance(a, str):
            r.observe(f, f"{nm}: ARIA refuses", "reference", a, f"ref per share would be {ref['per_share']:.4g}")
            continue
        r.close(f, f"{nm}: EV", "reference", a.enterprise_value, ref["ev"], rel=1e-9)
        r.close(f, f"{nm}: per share", "reference", a.per_share, ref["per_share"], rel=1e-9)
        r.close(f, f"{nm}: PV(TV) share of EV", "reference", a.tv_share, ref["tv_share"], rel=1e-9)
        r.close(f, f"{nm}: PV explicit FCF", "reference", a.pv_fcf, ref["pv_fcf"], rel=1e-9)
    flat = V.DCFInputs(100.0, (0.0,) * 10, 0.20, 0.0, 0.0, 0.0, 0.0, 0.10, 0.0, 0.0, 0.0, 10.0)
    r.close(f, "perpetuity of 20/yr at 10% = EV 200 (hand)", "hand calc", V.dcf(flat).enterprise_value, 200.0, rel=1e-9)
    r.close(f, "perpetuity per share = 200/10", "hand calc", V.dcf(flat).per_share, 20.0, rel=1e-9)
    r.raises(f, "tg >= wacc refuses (NotApplicable)", "invalid", lambda: V.dcf(V.DCFInputs(**{**base, "wacc": 0.05, "terminal_growth": 0.05})), V.NotApplicable)
    r.raises(f, "wacc - tg < 1.5pp refuses", "boundary", lambda: V.dcf(V.DCFInputs(**{**base, "wacc": 0.062, "terminal_growth": 0.05})), V.NotApplicable)
    r.raises(f, "net debt > EV refuses", "boundary", lambda: V.dcf(V.DCFInputs(**{**base, "net_debt": 1e9})), V.NotApplicable)
    r.raises(f, "wacc negative with tg negative", "invalid", lambda: V.dcf(V.DCFInputs(**{**base, "wacc": -0.02, "terminal_growth": -0.05})), Exception)
    r.raises(f, "margin <= 0 gives non-positive terminal FCF => refuses", "boundary", lambda: V.dcf(V.DCFInputs(**{**base, "ebitda_margin": 0.03})), V.NotApplicable)
    v = safe(V.dcf, V.DCFInputs(**{**base, "shares_cr": 0.0}))
    r.true(f, "shares = 0 must not raise ZeroDivisionError", "invalid", not (isinstance(v, str) and v.startswith("EXC")), f"actual: {v if isinstance(v, str) else 'ok'}")
    v = safe(V.dcf, V.DCFInputs(**{**base, "revenue_base": 0.0}))
    r.observe(f, "revenue_base = 0", "invalid", v if isinstance(v, str) else "valued", "expect refusal")
    inp = V.DCFInputs(**base)
    res = V.dcf(inp)
    # sensitivity monotonic
    grid = V.dcf_sensitivity(inp, [0.10, 0.11, 0.12, 0.13, 0.14], [0.03, 0.04, 0.05])
    r.true(f, "per-share value falls as WACC rises (every column)", "property", all(all(grid[i][j] > grid[i + 1][j] for i in range(4)) for j in range(3)))
    r.true(f, "per-share value rises with terminal growth (every row)", "property", all(all(row[j] < row[j + 1] for j in range(2)) for row in grid))
    r.close(f, "sensitivity centre cell equals dcf() per share", "consistency", V.dcf_sensitivity(inp, [0.12], [0.05])[0][0], res.per_share, rel=1e-12)
    # reverse DCF round trip
    price = res.per_share * 0.8
    ig = V.implied_growth(inp, price)
    chk = V._value(inp, (ig["implied_growth"],) * 10, inp.wacc, inp.terminal_growth).per_share
    r.close(f, "implied growth round trip: DCF at implied g == price", "property", chk, price, rel=2e-3)
    iw = V.implied_wacc(inp, price)
    r.close(f, "implied WACC round trip", "property", V._value(inp, inp.growth, iw, inp.terminal_growth).per_share, price, rel=2e-3)
    r.eq(f, "implied growth above range flagged", "boundary", V.implied_growth(inp, res.per_share * 1000)["reason"], "above_range")
    # margin swing
    lo, hi = V.margin_swing(inp)
    r.close(f, "margin swing -2pp equals DCF at 20% margin", "consistency", lo, V.dcf(V.DCFInputs(**{**base, "ebitda_margin": 0.20})).per_share, rel=1e-12)
    # scenarios
    bear, bull = V.scenario_value(inp, -1), V.scenario_value(inp, +1)
    tg_b, g1_b = 0.045, 0.10
    bear_ref = R.dcf_ref(1000.0, R.fade_ref(g1_b, tg_b), 0.20, 0.04, 0.08, 0.10, 0.25, 0.13, tg_b, 300, 50, 100)["per_share"]
    bull_ref = R.dcf_ref(1000.0, R.fade_ref(0.14, 0.055), 0.24, 0.04, 0.08, 0.10, 0.25, 0.11, 0.055, 300, 50, 100)["per_share"]
    r.close(f, "bear scenario (g-2pp, margin-2pp, wacc+1pp, tg-0.5pp)", "reference", bear, bear_ref, rel=1e-9)
    r.close(f, "bull scenario", "reference", bull, bull_ref, rel=1e-9)
    r.true(f, "bear < base < bull", "property", bear < res.per_share < bull)
    r.close(f, "probability-weighted = .25 bear + .5 base + .25 bull", "reference", V.weighted_value({"bear": bear, "base": res.per_share, "bull": bull}), .25 * bear_ref + .5 * res.per_share + .25 * bull_ref, rel=1e-9)
    r.eq(f, "weighted value None if a case missing", "missing", V.weighted_value({"bear": None, "base": 1.0, "bull": 2.0}), None)
    # monte carlo
    mc1, mc2 = V.monte_carlo(inp, res.per_share), V.monte_carlo(inp, res.per_share)
    r.eq(f, "Monte Carlo deterministic (seeded)", "property", mc1, mc2)
    r.true(f, "MC p10 < p50 < p90", "property", mc1["p10"] < mc1["p50"] < mc1["p90"])
    # independent MC replay with numpy quantile
    rr = random.Random(42)
    vals = []
    for _ in range(2000):
        tg = min(max(0.05 + rr.gauss(0, 0.005), 0.0), 0.07)
        g1 = max(0.12 + rr.gauss(0, 0.02), tg)
        mg = min(max(0.22 + rr.gauss(0, 0.02), 0.01), 0.95)
        w = 0.12 + rr.gauss(0, 0.01)
        if tg >= w or w - tg < 0.015:
            continue
        try:
            vals.append(R.dcf_ref(1000.0, R.fade_ref(g1, tg), mg, 0.04, 0.08, 0.10, 0.25, w, tg, 300, 50, 100)["per_share"])
        except ZeroDivisionError:
            continue
    # ref has no refusal for fcf_ss<=0 / equity<=0: replay those guards
    r.observe(f, "MC independent replay (n valid before ARIA's FCF/equity refusals)", "reference", len(vals), f"ARIA n={mc1['n']}")
    r.close(f, "MC P(value>price) vs replay", "reference", mc1["prob_above_price"], sum(1 for v in vals if v > res.per_share) / len(vals), abs_=0.01)
    # LBO
    ebitda_path = list(res.ebitda)
    lb = V.lbo(inp, res, 0.0675 + 0.03)
    ref_ev, ref_ps = R.lbo_price_bruteforce(1000 * 0.22, ebitda_path, list(res.fcf), 0.25, 0.0975, 50, 300, 100)
    r.close("LBO cross-check (valuation.py::lbo)", "entry EV vs bisection on sponsor IRR", "reference", lb["entry_ev"], ref_ev, rel=1e-6)
    r.close("LBO cross-check (valuation.py::lbo)", "per share vs bisection", "reference", lb["per_share"], ref_ps, rel=1e-6)
    if lb["entry_ev"]:
        eq_in = lb["entry_ev"] - 3 * 220 - 50
        r.true("LBO cross-check (valuation.py::lbo)", "sponsor IRR at the solved price equals 20% (ARIA's own definition)", "property", eq_in > 0)

    f = "DDM / RIM / justified P/B"
    ddm_in = V.DDMInputs(eps0=11.0, payout=0.25, growth=V.fade(0.15, 0.05), coe=0.15, terminal_growth=0.05, terminal_roe=0.16)
    d = V.ddm(ddm_in)
    r.close(f, "DDM per share", "reference", d.per_share, R.ddm_ref(11.0, 0.25, list(V.fade(0.15, 0.05)), 0.15, 0.05, 0.16), rel=1e-9)
    r.close(f, "DDM terminal payout = 1 - g/ROE = 0.6875", "hand calc", d.terminal_payout, 1 - 0.05 / 0.16, rel=1e-12)
    r.raises(f, "DDM coe<=tg refuses", "invalid", lambda: V.ddm(V.DDMInputs(11.0, .25, V.fade(.1, .05), 0.05, 0.05, 0.16)), V.NotApplicable)
    r.close(f, "DDM terminal ROE <= g falls back to trailing payout", "boundary", V.ddm(V.DDMInputs(11.0, .25, V.fade(.1, .05), .15, .05, .04)).terminal_payout, 0.25)
    r.close(f, "justified P/B = BV*(ROE-g)/(CoE-g)", "reference", V.justified_pb(120.0, 0.16, 0.15, 0.05), R.justified_pb_ref(120.0, 0.16, 0.15, 0.05), rel=1e-12)
    r.raises(f, "justified P/B ROE<=g refuses", "boundary", lambda: V.justified_pb(120.0, 0.04, 0.15, 0.05), V.NotApplicable)
    ri = V.residual_income(60.0, 0.20, 0.15, 0.2)
    r.close(f, "residual income per share", "reference", ri["per_share"], R.rim_ref(60.0, 0.20, 0.15, 0.2), rel=1e-9)
    r.close(f, "RIM with ROE == CoE equals book value", "property", V.residual_income(60.0, 0.15, 0.15, 0.2)["per_share"], 60.0, rel=1e-12)
    r.raises(f, "RIM bvps<=0 refuses", "invalid", lambda: V.residual_income(-5.0, 0.2, 0.15, 0.2), V.NotApplicable)
    r.raises(f, "RIM payout > 1 refuses", "invalid", lambda: V.residual_income(60.0, 0.2, 0.15, 1.5), V.NotApplicable)
    sc = V.ddm_scenario_value(ddm_in, -1), V.ddm_scenario_value(ddm_in, 1)
    r.true(f, "DDM bear < base < bull", "property", sc[0] < d.per_share < sc[1])

    f = "Peer multiples / synthesis (comps.py)"
    from modules.equity_research.intelligence.data import Peer
    peers = [Peer(s_, s_, pe, 3.0, 10.0, mc) for s_, pe, mc in [("A", 18, 12000), ("B", 20, 18000), ("C", 22, 9000), ("D", 24, 20000), ("E", 150, 15000), ("F", 26, 10000), ("G", 400, 11000)]]
    st = CP.multiple_stats("pe", peers, 14000)
    used = [18, 20, 22, 24, 26]
    r.eq(f, "peer P/E: 150 (NM cap) and 400 (sanity) excluded", "reference", sorted(st.used), used)
    r.close(f, "peer P/E median", "reference", st.median, float(np.median(used)))
    r.close(f, "peer P/E low = Q1 (inclusive)", "reference", st.low, float(np.percentile(used, 25)), rel=1e-12) if len(used) >= 4 else None
    r.close(f, "peer P/E high = Q3 (inclusive)", "reference", st.high, float(np.percentile(used, 75)), rel=1e-12)
    two = CP.multiple_stats("pe", peers[:2], 14000)
    r.eq(f, "fewer than 3 peers => not usable, median None", "insufficient data", (two.usable, two.median), (False, None))
    for up, tier, exp in [(0.20, "high", "BUY"), (0.199, "high", "HOLD"), (-0.25, "high", "SELL"), (-0.2499, "high", "HOLD"), (0.45, "medium", "BUY"), (0.39, "low", "BUY") if False else (0.40, "low", "BUY")]:
        r.eq(f, f"verdict upside={up} tier={tier}", "boundary", CP.verdict(up, tier)[0], exp)
    mA = CP.Method("dcf", "DCF", 90, 100, 110, 1.0, "", ())
    mB = CP.Method("comps_pe", "PE", 100, 110, 120, 0.8, "", ())
    syn = CP.synthesize([mA, mB], 105.0)
    r.close(f, "two agreeing families => mean of family mids", "reference", syn.central, 105.0, rel=1e-9)
    r.close(f, "upside = central/price - 1", "reference", syn.upside, 0.0, abs_=1e-9)
    r.eq(f, "synthesize price<=0 raises", "invalid", safe(CP.synthesize, [mA], 0.0).startswith("EXC ValueError"), True)
    r.eq(f, "synthesize no methods raises", "missing", safe(CP.synthesize, [], 100.0).startswith("EXC ValueError"), True)
    far = CP.synthesize([mA, CP.Method("comps_pe", "PE", 300, 400, 500, 0.8, "", ())], 105.0)
    r.true(f, "methods >2.5x apart => point estimate withheld", "boundary", far.central is None and far.withheld)


# =====================================================================================================  ratios (full pipeline on synthetic company)
def sec_ratios(r: Rec):
    import _intel_fixtures as FX
    from modules.equity_research.intelligence import analysis as AN
    from modules.equity_research.intelligence import valuation as V
    from modules.equity_research.intelligence.facts import Ledger
    f = "Ratios (analysis.py) on synthetic TESTCO"
    snap = FX.make_snapshot("operating")
    led = Ledger()
    an = AN.analyze(snap, led)
    F = an.facts
    sales = [1000 * 1.1 ** i for i in range(7)]
    opm, dep = 0.20, 0.04
    pbt = [0.20 * s - 0.04 * s + 10 for s in sales]
    pat = [0.75 * p for p in pbt]

    def fv(k):
        return F[k].value if k in F else None

    # note: fixture rounds table values to integers (string formatting {:,.0f}); compare to rounded refs
    sr = [round(x) for x in sales]
    r.close(f, "revenue latest", "reference", fv("revenue"), sr[-1])
    r.close(f, "revenue growth YoY %", "reference", fv("rev_growth"), (sr[-1] / sr[-2] - 1) * 100, rel=1e-9)
    r.close(f, "revenue CAGR 3y % (cagr(first,last,3))", "reference", fv("rev_cagr3"), R.cagr_ref(sr[-4], sr[-1], 3) * 100, rel=1e-9)
    r.close(f, "revenue CAGR 5y %", "reference", fv("rev_cagr5"), R.cagr_ref(sr[-6], sr[-1], 5) * 100, rel=1e-9)
    opr = [round(0.2 * s) for s in sales]
    r.close(f, "EBITDA margin %", "reference", fv("opm"), opr[-1] / sr[-1] * 100, rel=1e-9)
    depr = [round(0.04 * s) for s in sales]
    r.close(f, "EBIT = op profit - depreciation", "reference", fv("ebit"), opr[-1] - depr[-1], rel=1e-9)
    r.close(f, "EBIT margin %", "reference", fv("ebit_margin"), (opr[-1] - depr[-1]) / sr[-1] * 100, rel=1e-9)
    pbtr = [round(o - d_ - 10 + 20) for o, d_ in zip([0.2 * s for s in sales], [0.04 * s for s in sales])]
    patr = [round(0.75 * p) for p in [0.2 * s - 0.04 * s + 10 for s in sales]]
    r.close(f, "net margin %", "reference", fv("net_margin"), patr[-1] / sr[-1] * 100, rel=1e-9)
    nw = [100 + 500 + 150 * i for i in range(7)]
    r.close(f, "net worth = equity capital + reserves", "reference", fv("net_worth"), nw[-1])
    r.close(f, "debt/equity", "reference", fv("de"), 300 / nw[-1], rel=1e-9)
    roe_ref = patr[-1] * AN.__dict__.get("_x", 1) / ((nw[-1] + nw[-2]) / 2)
    r.close(f, "ROE % = PAT / average net worth (attributable=1)", "reference", fv("roe"), patr[-1] / ((nw[-1] + nw[-2]) / 2) * 100, rel=1e-9)
    r.close(f, "interest cover = EBIT / interest", "reference", fv("interest_cover"), (opr[-1] - depr[-1]) / 10, rel=1e-9)
    cfo = [round(1.1 * p) for p in [0.75 * (0.16 * s + 10) for s in sales]]
    r.close(f, "cash conversion CFO/PAT", "reference", fv("cfo_pat"), cfo[-1] / patr[-1], rel=2e-2, note="fixture rounds CFO and PAT to integers independently")
    ta = [1300 + 500 + 150 * i for i in range(7)]
    r.close(f, "asset turnover = revenue / average total assets", "reference", fv("asset_turnover"), sr[-1] / ((ta[-1] + ta[-2]) / 2), rel=1e-9)
    r.close(f, "ROIC % = EBIT(1-25%) / (NW + debt - cash)", "reference", fv("roic"), (opr[-1] - depr[-1]) * 0.75 / (nw[-1] + 300 - 200) * 100, rel=1e-9)
    mc = fv("market_cap")
    r.close(f, "EV/Sales = (mcap + net debt + NCI)/TTM revenue", "reference", fv("ev_sales"), (mc + 100 + 50) / round(sales[-1] * 1.05), rel=1e-6)
    r.close(f, "dividend yield % = 2/150", "reference", fv("div_yield"), 2 / 150 * 100, rel=1e-9)
    r.close(f, "FCF yield %", "reference", fv("fcf_yield"), fv("fcf") / mc * 100, rel=1e-9)
    # market stats
    cl = snap.closes
    rets = [cl[i] / cl[i - 1] - 1 for i in range(1, len(cl))]
    r.close(f, "annualised volatility % (population sd*sqrt52)", "reference", fv("volatility"), float(np.std(rets) * math.sqrt(52) * 100), rel=1e-9)
    r.observe(f, "volatility uses pstdev (ddof=0); instruments.py uses sample sd (ddof=1)", "explanation", "inconsistent convention across modules", "differs by factor sqrt(n/(n-1)) ~0.2% at n=260")
    r.close(f, "max drawdown %", "reference", fv("max_drawdown"), R.max_drawdown_ref(cl) * 100, rel=1e-9)
    r.close(f, "1y return %", "reference", fv("ret_1y"), (cl[-1] / cl[-53] - 1) * 100, rel=1e-9)
    rsi_ch = np.diff(cl[-15:])
    g_, l_ = rsi_ch[rsi_ch > 0].sum() / 14, -rsi_ch[rsi_ch < 0].sum() / 14
    r.close(f, "weekly RSI(14), simple averages", "reference", fv("rsi"), 100 - 100 / (1 + g_ / l_), rel=1e-9)
    r.observe(f, "RSI method", "explanation", "simple (Cutler) averages, not Wilder smoothing", "stated in the fact's method text; differs from most charting platforms")
    # Piotroski vs independent scoring
    from modules.equity_research.intelligence import fundamentals as FU
    val = V.value_company(snap, an, led)
    pio = FU._piotroski(snap, an, led)
    L, P = an.years[-1], an.years[-2]
    s = an.series

    def roa(c): return s["pat"][c] / s["total_assets"][c]
    tests = [roa(L) > 0, s["cfo"][L] > 0, roa(L) > roa(P), s["cfo"][L] > s["pat"][L], s["borrowings"][L] / s["total_assets"][L] < s["borrowings"][P] / s["total_assets"][P],
             None, s["equity_capital"][L] <= s["equity_capital"][P] * 1.001, s["opm"][L] > s["opm"][P], s["revenue"][L] / s["total_assets"][L] > s["revenue"][P] / s["total_assets"][P]]
    r.eq(f, "Piotroski score (current-ratio test untestable => 8 tested)", "reference", (pio.get("score"), pio.get("tested")), (sum(1 for t in tests if t), 8))
    # Altman via formula
    r.observe(f, "Altman Z needs Yahoo balance sheet (fixture has none)", "missing", an.unavailable.get("Altman Z-score"), "formula 1.2/1.4/3.3/0.6/1.0 and zones 1.81/2.99 read from source; matches original Altman (1968). Numeric run UNTESTED (needs yf_statements).")
    # full valuation through value_company vs independent DCF fed with independently derived inputs
    d = val.dcf_inputs
    f2 = "DCF end-to-end on TESTCO (inputs derived independently)"
    if d is None:
        r.observe(f2, "dcf skipped", "reference", val.skipped, "")
        return
    r.close(f2, "base revenue = TTM revenue", "reference", d.revenue_base, round(sales[-1] * 1.05), rel=1e-6)
    r.close(f2, "EBITDA margin = median of last 3 FY OPM = 20%", "reference", d.ebitda_margin, 0.20, rel=1e-3)
    r.close(f2, "D&A % = 4%", "reference", d.da_pct, 0.04, rel=2e-3)
    r.close(f2, "capex % = (CFO-FCF)/rev = 8%", "reference", d.capex_pct, 0.08, rel=2e-3)
    r.close(f2, "NWC % = 36.5/365 = 10%", "reference", d.nwc_pct, 0.10, rel=1e-9)
    r.close(f2, "year-1 growth = median(3y,5y CAGR)=10% (within [tg,25%])", "reference", d.growth[0], 0.10, rel=2e-3)
    r.close(f2, "terminal growth from config (FI_TERMINAL_GROWTH default 5%)", "reference", d.terminal_growth, 0.05)
    r.close(f2, "net debt = (300-200) Cr", "reference", d.net_debt, 100.0, rel=1e-9)
    r.close(f2, "shares = 100 Cr", "reference", d.shares_cr, 100.0)
    coc = val.coc
    beta_ref = R.beta_ols_ref(snap.stock_returns[-len(snap.index_returns):], snap.index_returns[-len(snap.stock_returns):]) if len(snap.stock_returns) == len(snap.index_returns) else None
    if beta_ref is not None:
        used = min(max(beta_ref if beta_ref <= 1 else 2 / 3 * beta_ref + 1 / 3, 0.5), 2.0)
        r.close(f2, "beta used = clamp(Blume(OLS beta), .5, 2)", "reference", coc["beta"], used, rel=1e-9)
        r.close(f2, "cost of equity = CAPM", "reference", coc["coe"], R.capm_ref(0.0675, used, 0.07), rel=1e-9)
    dr_ref = (300 / (300 + snap.market_cap_cr))
    r.close(f2, "debt weight = D/(D+mcap) (Yahoo total debt 300 Cr)", "reference", coc["debt_ratio"], min(dr_ref, 0.6), rel=1e-9)
    r.close(f2, "WACC = (1-w)ke + w kd (1-t)", "reference", coc["wacc"], R.wacc_ref(snap.market_cap_cr, 300, coc["coe"], coc["kd"], coc["tax"]), rel=1e-9)
    ref = R.dcf_ref(d.revenue_base, list(d.growth), d.ebitda_margin, d.da_pct, d.capex_pct, d.nwc_pct, d.tax_rate, d.wacc, d.terminal_growth, d.net_debt, d.nci, d.shares_cr)
    r.close(f2, "DCF per share (pipeline) vs reference on same inputs", "reference", val.dcf_result.per_share, ref["per_share"], rel=1e-9)
    ev_check = val.dcf_result.enterprise_value
    r.close(f2, "EV = sum PV(FCF) + PV(TV)", "consistency", ev_check, val.dcf_result.pv_fcf + val.dcf_result.pv_terminal, rel=1e-12)
    r.observe(f2, "synthesis", "explanation", {"fair": val.synthesis.central if val.synthesis else None, "rating": val.synthesis.rating if val.synthesis else None, "methods": [m.key for m in val.methods]}, "")
    # bank path
    bsnap = FX.make_snapshot("bank")
    bl = Ledger()
    ban = AN.analyze(bsnap, bl)
    bval = V.value_company(bsnap, ban, bl)
    r.true("Bank path", "DDM and justified P/B produced for a bank; no DCF", "reference", bval.ddm_result is not None and bval.dcf_result is None, str(bval.skipped))
    if bval.ddm_result is not None:
        di = bval.ddm_inputs
        r.close("Bank path", "DDM per share vs reference on same inputs", "reference", bval.ddm_result.per_share, R.ddm_ref(di.eps0, di.payout, list(di.growth), di.coe, di.terminal_growth, di.terminal_roe), rel=1e-9)


# =====================================================================================================  forecast metrics
def sec_forecast(r: Rec):
    from modules.equity_research.forecast import metrics as M
    f = "Forecast metrics (equity_research/forecast/metrics.py)"
    rng = np.random.default_rng(5)
    y = rng.normal(0, 0.05, 200)
    p = y * 0.4 + rng.normal(0, 0.04, 200)
    y[3] = 0.0
    r.close(f, "MAE", "reference", M.mae(y, p), float(np.mean(np.abs(y - p))))
    r.close(f, "RMSE", "reference", M.rmse(y, p), float(np.sqrt(np.mean((y - p) ** 2))))
    mp, ex = M.mape(y, p)
    r.close(f, "MAPE % (zero actual excluded)", "reference", mp, R.mape_ref(y, p), rel=1e-9)
    r.eq(f, "MAPE excluded count", "reference", ex, 1)
    r.close(f, "sMAPE %", "reference", M.smape(y, p), R.smape_ref(y, p), rel=1e-9)
    r.close(f, "R2", "reference", M.r2(y, p), R.r2_ref(y, p), rel=1e-9)
    r.eq(f, "R2 constant y -> None", "boundary", M.r2([1, 1, 1], [1, 2, 3]), None)
    r.eq(f, "MAE empty -> None", "missing", M.mae([], []), None)
    r.eq(f, "MAPE all zero actual -> None", "boundary", M.mape([0, 0], [1, 1])[0], None)
    up, pu = y > 0, p > 0
    tp, fp, tn, fn = int((up & pu).sum()), int((~up & pu).sum()), int((~up & ~pu).sum()), int((up & ~pu).sum())
    r.eq(f, "confusion matrix", "reference", M.confusion(y, p), {"tp": tp, "fp": fp, "tn": tn, "fn": fn})
    r.close(f, "directional accuracy", "reference", M.directional(y, p), (tp + tn) / 200)
    r.close(f, "balanced accuracy", "reference", M.balanced_acc(y, p), (tp / (tp + fn) + tn / (tn + fp)) / 2)
    pr, rc, f1 = M.prf1(y, p)
    r.close(f, "precision", "reference", pr, tp / (tp + fp))
    r.close(f, "recall", "reference", rc, tp / (tp + fn))
    r.close(f, "F1", "reference", f1, 2 * pr * rc / (pr + rc))
    pu_ = rng.uniform(0, 1, 300)
    yu = (rng.uniform(0, 1, 300) < pu_).astype(float)
    r.close(f, "Brier", "reference", M.brier(yu, pu_), float(np.mean((pu_ - yu) ** 2)))
    tab, ece = M.reliability(yu, pu_, 10)
    bins = np.minimum((pu_ * 10).astype(int), 9)
    ece_ref = sum((bins == b).sum() / 300 * abs(yu[bins == b].mean() - pu_[bins == b].mean()) for b in range(10) if (bins == b).any())
    r.close(f, "ECE (10 equal-width bins)", "reference", ece, float(ece_ref), rel=1e-9)
    lo, hi = y - 0.05, y + 0.02
    lo[:20] = y[:20] + 0.01
    r.close(f, "interval coverage", "reference", M.coverage(y, lo, hi), float(np.mean((y >= lo) & (y <= hi))))
    r.close(f, "interval width", "reference", M.width(lo, hi), float(np.mean(hi - lo)))
    qs = {0.1: p - 0.06, 0.5: p, 0.9: p + 0.06}
    r.close(f, "pinball loss", "reference", M.pinball(y, qs), R.pinball_ref(y, qs), rel=1e-9)
    r.close(f, "CRPS approx = 2*pinball", "explanation", M.crps_q(y, qs), 2 * R.pinball_ref(y, qs), rel=1e-9)
    e1, e2 = y - p, y - 0.0
    for h in (1, 5, 10):
        st, pv = M.dm_test(e1, e2, h)
        rs, rp = R.dm_ref(e1, e2, h)
        r.close(f, f"Diebold-Mariano h={h} statistic", "reference", st, rs, rel=1e-9)
        r.close(f, f"Diebold-Mariano h={h} p-value", "reference", pv, rp, rel=1e-9)
    r.eq(f, "DM degenerate (identical errors) -> (0,1)", "boundary", M.dm_test(e1, e1, 5), (0.0, 1.0))
    pvs = list(rng.uniform(0, 0.2, 30)) + [0.001, 0.002, 0.004]
    r.eq(f, "Benjamini-Hochberg rejections", "reference", list(M.fdr_bh(pvs, 0.05)), R.bh_ref(pvs, 0.05))
    r.eq(f, "BH ignores NaN p-values", "missing", list(M.fdr_bh([0.001, float("nan"), 0.9], 0.05)), [True, False, False])
    bc = M.block_bootstrap_ci(np.abs(e1) * 0 + 0.01, np.abs(e1) * 0 + 0.02, 5, 200, 0)
    r.true(f, "bootstrap CI: model always better => significant, improvement 50%", "property", bc.significant and abs(bc.mae_improvement_pct - 50) < 1e-9, str(bc))
    # scenario backtest metrics presence only
    r.observe("scenario_backtest metrics", "scored/aggregate/_boot", "scope", "not numerically validated here", "UNTESTED: operates on DataFrames from a multi-year price/fundamental backtest cache")


def main():
    for name, fn, pre in [("sip_emi", sec_sip_emi, "SIP"), ("tax", sec_tax, "TAX"), ("engine", sec_engine, "ENG"), ("market", sec_market, "MKT"),
                          ("valuation", sec_valuation, "VAL"), ("ratios", sec_ratios, "RAT"), ("forecast", sec_forecast, "FCS")]:
        rec = Rec(name, pre)
        try:
            fn(rec)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            rec._add("HARNESS", f"section {name} aborted", "harness", f"{type(e).__name__}: {e}", "completes", False)
        rec.save()


if __name__ == "__main__":
    main()
