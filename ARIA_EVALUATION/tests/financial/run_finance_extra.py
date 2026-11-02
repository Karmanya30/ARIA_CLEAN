"""Audit of budget LP, instrument recommender, spending insights, anomaly, spend-forecast, risk (modules/finance).
No network, no LLM. Usage: python -X utf8 run_finance_extra.py
"""
import sys, os, json, random, statistics
sys.path.insert(0, os.path.dirname(__file__))
from harness import ROOT, Rec
from datetime import date


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"EXC {type(e).__name__}: {str(e)[:80]}"


# ---------------- budget LP
def sec_budget(r):
    from modules.finance.budget_optimize import optimize_budget, FLOORS, SIP_CAP
    f = "Budget LP (budget_optimize.py)"
    cases = [(100000, 0, 1, "Moderate", 6), (100000, 20000, 1, "Aggressive", 3), (60000, 10000, 2, "Conservative", 0),
             (40000, 25000, 3, "Moderate", 2), (30000, 0, 3, "Aggressive", 6), (250000, 50000, 1, "Moderate", 12)]
    for inc, emi, tier, risk, em in cases:
        fl, cap = FLOORS[tier], SIP_CAP[risk]
        efl = 0.05 * inc if em < 6 else 0.0
        mins = emi + fl["food"] + fl["transport"] + fl["utilities"] + efl
        ref_sip = min(cap * inc, inc - mins)  # closed form: non-SIP lines can absorb the rest (food/transport/utilities/emergency unbounded above)
        try:
            b = optimize_budget(inc, emi, tier, risk, em)
        except ValueError as e:
            r.observe(f, f"inc={inc} emi={emi} tier={tier} {risk} em={em}", "infeasible", str(e)[:90], f"reference sip={ref_sip:.0f}")
            continue
        d = b.model_dump()
        r.close(f, f"SIP max inc={inc} emi={emi} t{tier} {risk} em={em}", "reference", d["sip"], round(ref_sip), abs_=0.51)
        r.close(f, f"allocation sums to income (per-line rounding) inc={inc} emi={emi}", "property", sum(d.values()), inc, abs_=4.0)
        r.true(f, f"housing<=35% ent<=15% floors met inc={inc} emi={emi}", "constraint",
               d["housing"] <= 0.35 * inc + 0.5 and d["entertainment"] <= 0.15 * inc + 0.5 and d["food"] >= fl["food"] and d["emi"] == emi)
        r.observe(f, f"split inc={inc} emi={emi} t{tier} {risk}", "realism", {k: round(v / inc * 100, 1) for k, v in d.items()}, "percent of income per line")
    r.raises(f, "income 0", "invalid", lambda: optimize_budget(0, 0, 1, "Moderate", 6), ValueError)
    r.raises(f, "income negative", "invalid", lambda: optimize_budget(-5, 0, 1, "Moderate", 6), ValueError)
    r.raises(f, "EMI+floors > income", "infeasible", lambda: optimize_budget(20000, 15000, 1, "Moderate", 0), ValueError)
    r.observe(f, "negative EMI -5000", "invalid", safe(lambda: optimize_budget(80000, -5000, 1, "Moderate", 6).model_dump()), "")
    r.observe(f, "NaN income", "invalid", safe(lambda: optimize_budget(float("nan"), 0, 1, "Moderate", 6).model_dump()), "")
    r.observe(f, "unknown tier 9 / unknown risk 'Zzz'", "invalid", safe(lambda: optimize_budget(80000, 0, 9, "Zzz", 6).model_dump()), "silent fallback to tier-1 floors / Moderate cap")


# ---------------- instrument recommender
def sec_reco(r):
    from modules.finance import instrument_recommender as IR
    f = "Instrument recommender (instrument_recommender.py)"
    cat = [c for c in json.loads((ROOT / "data/raw/concepts_kb/concepts.json").read_text(encoding="utf8")) if c.get("is_recommendable_instrument")]
    scale = {"Conservative": 2, "Moderate": 5, "Aggressive": 8}
    true_80c = {"elss": True, "ppf": True, "nps": True, "fd": False, "etf": False, "index_fund": False, "direct_equity": False}

    def ref(c, risk, hz, regime, em, has80c):
        s = 100 - abs(scale.get(risk, 5) - c["risk_level"]) * 8
        mh = c.get("min_horizon_years")
        if hz is not None and mh:
            s += 10 if hz >= mh else -30
        if em < 6 and (c.get("lock_in_years") or 0) > 0:
            s -= 25
        if has80c:
            s += 15 if regime == "old" else -10
        return max(0, min(100, s))

    for risk in ("Conservative", "Moderate", "Aggressive"):
        for hz in (None, 1, 5, 15):
            for regime in ("old", "new"):
                for em in (0, 6):
                    got = {x.instrument_id: x.score for x in IR.recommend(risk, hz, regime, em)}
                    for c in cat:
                        r.close(f, f"{c['id']} {risk} hz={hz} {regime} em={em} (rules, TRUE 80C eligibility)", "reference", got[c["id"]],
                                round(ref(c, risk, hz, regime, em, true_80c[c["id"]]), 1), abs_=0.051)
    for c in cat:
        flagged = "80c" in c["tax_treatment"].lower() or "80ccd" in c["tax_treatment"].lower()
        r.eq(f, f"{c['id']}: substring '80c' flag == real 80C eligibility", "defect-probe", flagged, true_80c[c["id"]], note=c["tax_treatment"][:80])
    a, b = IR.recommend("Moderate", 10, "new", 6), IR.recommend("Moderate", 10, "new", 6)
    r.eq(f, "deterministic", "property", [x.model_dump() for x in a], [x.model_dump() for x in b])
    r.true(f, "sorted descending", "property", all(a[i].score >= a[i + 1].score for i in range(len(a) - 1)))
    for x in a:
        r.eq(f, f"fit label {x.instrument_id} score {x.score}", "reference", x.fit, "strong_fit" if x.score >= 70 else "consider" if x.score >= 40 else "not_a_fit")
    r.observe(f, "unknown risk label 'Foo'", "invalid", [(x.instrument_id, x.score) for x in IR.recommend("Foo", 5)][:3], "falls back to Moderate silently")
    r.observe(f, "negative horizon", "boundary", [(x.instrument_id, x.score) for x in IR.recommend("Moderate", -3, "new", 0)][:3], "")
    r.observe(f, "NPS _is_illiquid (catalogue lock_in_years=None)", "probe", IR._is_illiquid([c for c in cat if c["id"] == "nps"][0]), "NPS is locked to ~60 in reality")
    for reg in ("new", "old"):
        etf = [x for x in IR.recommend("Moderate", 10, reg, 6) if x.instrument_id == "etf"][0]
        r.observe(f, f"ETF explanation under {reg} regime", "explanation", {"for": etf.reasons_for, "against": etf.reasons_against, "score": etf.score}, "ETF has no 80C benefit")


# ---------------- spending insights
def sec_spending(r):
    from modules.finance import spending as S
    f = "Spending insights (spending.py)"
    tx = []
    for m in (1, 2, 3):
        d = lambda day: f"2026-{m:02d}-{day:02d}"  # noqa: E731
        tx += [dict(date=d(1), category="housing", amount=20000.0, merchant="Landlord"), dict(date=d(5), category="emi", amount=10000.0, merchant="HDFC"),
               dict(date=d(7), category="food", amount=4000.0 + m * 100, merchant="Swiggy"), dict(date=d(9), category="food", amount=3000.0, merchant="BigBasket"),
               dict(date=d(12), category="entertainment", amount=649.0, merchant="Netflix"), dict(date=d(15), category="transport", amount=2500.0, merchant="Uber"),
               dict(date=d(20), category="utilities", amount=1800.0, merchant="BESCOM")]
    tx.append(dict(date="2026-03-22", category="entertainment", amount=45000.0, merchant="Gadgetworld"))
    income = 100000.0
    ins = S.insights(tx, {"monthly_income": income})
    emi_tot = sum(t["amount"] for t in tx if t["category"] == "emi")
    spend = sum(t["amount"] for t in tx) - emi_tot
    r.close(f, "spend_avg", "reference", ins["cashflow"]["spend_avg"], round(spend / 3, 2), abs_=0.01)
    r.close(f, "emi_avg", "reference", ins["cashflow"]["emi_avg"], round(emi_tot / 3, 2), abs_=0.01)
    r.close(f, "savings_rate %", "reference", ins["cashflow"]["savings_rate"], round((income - spend / 3 - emi_tot / 3) / income * 100, 1), abs_=0.05)
    for m in ("2026-01", "2026-03"):
        sp = sum(t["amount"] for t in tx if t["date"][:7] == m and t["category"] != "emi")
        row = [x for x in ins["cashflow"]["by_month"] if x["month"] == m][0]
        r.close(f, f"by_month spend {m}", "reference", row["spend"], sp, abs_=0.01)
        r.close(f, f"by_month net {m}", "reference", row["net"], income - sp - 10000, abs_=0.01)
    ent = [c for c in ins["categories"] if c["name"] == "entertainment"][0]
    ent_tot = sum(t["amount"] for t in tx if t["category"] == "entertainment")
    r.close(f, "entertainment share_of_income", "reference", ent["share_of_income"], round(ent_tot / 3 / income * 100, 1), abs_=0.05)
    r.eq(f, "entertainment over_benchmark (8%)", "reference", ent["over_benchmark"], ent_tot / 3 / income * 100 > 8)
    trim = [s for s in ins["suggestions"] if s["title"].startswith("Trim entertainment")]
    r.close(f, "trim = avg - 8% income", "reference", trim[0]["saving_per_month"] if trim else None, round(ent_tot / 3 - 0.08 * income), abs_=1)
    r.eq(f, "Netflix detected recurring", "reference", any(x["merchant"] == "Netflix" for x in ins["recurring"]), True)
    r.eq(f, "45000 charge flagged unusual", "reference", [u["merchant"] for u in ins["unusual"]], ["Gadgetworld"])
    r.eq(f, "spent(food,2026-02)", "reference", S.spent(tx, "food", "2026-02"), 7200.0)
    food = [c for c in ins["categories"] if c["name"] == "food"][0]
    r.close(f, "food trend_pct last vs prev month", "reference", food["trend_pct"], round((7300 - 7200) / 7200 * 100, 1), abs_=0.05)
    r.eq(f, "<10 txns => unavailable", "boundary", S.insights(tx[:9], None)["available"], False)
    r.observe(f, "no income, no profile", "missing", {k: safe(lambda k=k: S.insights(tx, None)["cashflow"][k]) for k in ("income_avg", "savings_rate")}, "")
    yb = [dict(date="2025-12-%02d" % (i + 1), category="food", amount=100.0, merchant="A") for i in range(6)] + [dict(date="2026-01-%02d" % (i + 1), category="food", amount=200.0, merchant="B") for i in range(6)]
    v = safe(lambda: S.insights(yb, {"monthly_income": 10000})["categories"][0]["trend_pct"])
    r.close(f, "year-boundary trend Dec->Jan (+100%)", "reference", v if not isinstance(v, str) else None, 100.0, abs_=0.05)
    r.observe(f, "refund (negative amount) in spent()", "invalid", S.spent([dict(date="2026-01-01", category="food", amount=-500.0), dict(date="2026-01-02", category="food", amount=1500.0)], "food"), "refunds net silently to 1000")


# ---------------- anomaly
def sec_anomaly(r):
    from modules.finance.anomaly import detect_for_user
    from modules.finance.schemas import Transaction
    f = "Anomaly (anomaly.py, IsolationForest)"
    random.seed(7)

    def mk(n, extra=None):
        return [Transaction(date=date(2026, 1 + (i % 3), 1 + (i * 3) % 27), category="food", amount=float(random.randint(300, 500))) for i in range(n)] + (extra or [])

    r.eq(f, "fewer than 10 txns => []", "boundary", detect_for_user(mk(9)), [])
    r.eq(f, "None => []", "missing", detect_for_user(None), [])
    base = mk(60)
    big = Transaction(date=date(2026, 2, 10), category="food", amount=50000.0)
    flags = detect_for_user(base + [big])
    r.true(f, "injected ~100x outlier is flagged first", "reference", bool(flags) and flags[0].transaction.amount == 50000.0, f"flags={[(x.transaction.amount, round(x.score, 3)) for x in flags[:3]]}")
    r.true(f, "flag count ~ contamination 2% (<=5 of 61)", "property", len(flags) <= 5, f"n_flags={len(flags)}")
    med = statistics.median([t.amount for t in base] + [50000.0])
    if flags and "x this" in flags[0].reason:
        claimed = float(flags[0].reason.split(" is ")[1].split("x")[0])
        r.close(f, "reason ratio equals amount/category median", "explanation", claimed, round(50000 / med, 1), abs_=0.06, note=flags[0].reason)
    r.observe(f, "no outlier at all: number flagged anyway", "false-positive", len(detect_for_user(mk(60))), "contamination=0.02 forces ~2% flagged in clean data")
    r.observe(f, "all-identical amounts (30)", "boundary", safe(lambda: len(detect_for_user([Transaction(date=date(2026, 1, 1 + i % 28), category="food", amount=100.0) for i in range(30)]))), "")
    r.observe(f, "all-zero amounts (30)", "boundary", safe(lambda: len(detect_for_user([Transaction(date=date(2026, 1, 1 + i % 28), category="food", amount=0.0) for i in range(30)]))), "")
    r.observe(f, "negative amount (log1p of < -1 => NaN)", "invalid", safe(lambda: len(detect_for_user(mk(30, [Transaction(date=date(2026, 1, 5), category="food", amount=-5000.0)])))), "")


# ---------------- spend forecast
def sec_forecast(r):
    import pandas as pd
    from modules.finance import forecast_model as F
    from modules.finance.schemas import Transaction
    from modules.finance.features import transactions_to_dataframe
    f = "Spend forecast LSTM (forecast_model.py)"
    t = [Transaction(date=date(2026, m, 5), category=c, amount=float(a)) for m in range(1, 9)
         for c, a in (("food", 8000), ("housing", 20000), ("transport", 3000), ("utilities", 2000), ("entertainment", 2500), ("emi", 8000))]
    piv = F.monthly_category_ratios(transactions_to_dataframe(t), 100000.0)
    r.close(f, "ratio food Jan (8000/100000)", "reference", piv.loc[pd.Period("2026-01"), "food"], 0.08)
    r.eq(f, "empty history => zero forecast", "boundary", F.predict(100000.0, [])[0].forecast, [0.0, 0.0, 0.0])
    r.observe(f, "income<=0 with history", "invalid", safe(lambda: F.predict(0.0, t)[0].forecast), "")
    if not F.is_trained():
        r.observe(f, "model", "blocked", "not trained", "BLOCKED")
        return
    out = F.predict(100000.0, t)
    bad = [(c.category, i) for c in out for i in range(len(c.forecast)) if not (c.lower_ci[i] <= c.forecast[i] <= c.upper_ci[i])]
    r.true(f, "P10<=P50<=P90 for all categories/months", "property", not bad, f"crossings={bad[:6]} n={len(bad)}")
    r.true(f, "non-negative", "property", all(v >= 0 for c in out for v in c.forecast + c.lower_ci + c.upper_ci))
    out2 = F.predict(200000.0, t)
    get = lambda o, cat: [c for c in o if c.category == cat][0]  # noqa: E731
    for cat, naive in (("food", 8000), ("housing", 20000), ("emi", 8000), ("transport", 3000)):
        r.observe(f, f"{cat} forecast on flat history of {naive}/mo (income 1L)", "accuracy", {"p50": get(out, cat).forecast, "p10": get(out, cat).lower_ci, "p90": get(out, cat).upper_ci}, f"naive forecast = {naive}")
    r.observe(f, "food forecast, same rupee spend, income 2L", "scale", get(out2, "food").forecast, "ratio-scaled model: input ratio halves")


def sec_risk(r):
    from modules.finance import risk_model as RM
    f = "Risk profile XGBoost (risk_model.py)"
    if not RM.is_trained():
        r.observe(f, "model", "blocked", "not trained", "BLOCKED")
        return
    for args in [(200000, 35, 0, 0, 1), (25000, 28, 3, 15000, 3), (80000, 45, 2, 10000, 2), (1e9, 40, 0, 0, 1)]:
        p = safe(RM.predict, *args)
        r.observe(f, f"predict{args}", "probe", (p.label, round(p.confidence, 3)) if not isinstance(p, str) else p, "no oracle (learned model)")
    r.observe(f, "negative income / age 5 / age 200", "invalid", [safe(lambda a=a: RM.predict(*a).label) for a in [(-5000, 35, 0, 0, 1), (50000, 5, 0, 0, 1), (50000, 200, 0, 0, 1)]], "")
    a, b = RM.predict(60000, 35, 1, 5000, 2), RM.predict(60000, 35, 1, 5000, 2)
    r.eq(f, "deterministic", "property", (a.label, a.confidence), (b.label, b.confidence))


if __name__ == "__main__":
    for name, fn, pre in [("budget", sec_budget, "BUD"), ("reco", sec_reco, "REC"), ("spending", sec_spending, "SPD"), ("anomaly", sec_anomaly, "ANO"),
                          ("forecast", sec_forecast, "FCS"), ("risk", sec_risk, "RSK")]:
        rec = Rec(name, pre)
        try:
            fn(rec)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            rec._add("HARNESS", f"{name} aborted", "harness", f"{type(e).__name__}: {e}", "completes", False)
        rec.save()
