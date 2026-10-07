"""Spending analysis over stored transactions (pure functions; no I/O, no logging of transaction contents).

insights(txns, profile) -> cashflow, categories vs rule-of-thumb benchmarks, top merchants, recurring payments,
unusual charges and deterministic suggestions. spent() filters by category / month / merchant for chat.
Only debits are stored, so income comes from the profile's monthly_income (None when unknown).
"""
from __future__ import annotations

import re
from datetime import date
from statistics import median, pstdev
from typing import Any

from modules.finance.anomaly import MIN_TRANSACTIONS

# Indian rules of thumb: max share of monthly income (percent) per category.
BENCHMARKS = {"housing": 35, "food": 15, "transport": 10, "utilities": 8, "entertainment": 8, "medical": 8}
EMI_WARN_PCT = 40
RECURRING_TOL = 0.10
UNAVAILABLE = "upload a statement or add more transactions"

_inr = lambda x: f"₹{x:,.0f}"  # noqa: E731
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_label(ym: str) -> str:
    return f"{_MONTHS[int(ym[5:7]) - 1]} {ym[:4]}"


def _months_between(a: str, b: str) -> list[str]:
    y, m, out = int(a[:4]), int(a[5:7]), []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def basis(txns: list[dict]) -> str:
    ds = sorted(t["date"][:7] for t in txns)
    a, b = ds[0], ds[-1]
    span = month_label(a) if a == b else (f"{_MONTHS[int(a[5:7]) - 1]}-{month_label(b)}" if a[:4] == b[:4]
                                          else f"{month_label(a)}-{month_label(b)}")
    return f"Based on your uploaded transactions ({span})"


def spent(txns: list[dict], category: str | None = None, month: str | None = None, merchant: str | None = None) -> float:
    """Total spent, optionally for one category, one 'YYYY-MM' month, or merchants containing a word."""
    return round(sum(t["amount"] for t in txns
                     if (not category or t["category"] == category) and (not month or t["date"][:7] == month)
                     and (not merchant or merchant.lower() in (t.get("merchant") or "").lower())), 2)


def _recurring(txns: list[dict]) -> list[dict]:
    by_m: dict[str, list[dict]] = {}
    for t in txns:
        if (t.get("merchant") or "").strip() and t["merchant"] != "Unknown":
            by_m.setdefault(t["merchant"].lower(), []).append(t)
    out = []
    for group in by_m.values():
        mid = median(t["amount"] for t in group)
        same = [t for t in group if abs(t["amount"] - mid) <= RECURRING_TOL * mid]
        months = {t["date"][:7] for t in same}
        if len(months) >= 2 and len(same) <= len(months):  # at most one charge a month: a bill, not shopping
            out.append({"merchant": same[0]["merchant"], "amount": round(median(t["amount"] for t in same), 2),
                        "months": len(months), "category": same[0]["category"]})
    return sorted(out, key=lambda r: -r["amount"])


def _unusual(txns: list[dict], income: float | None, recurring: list[dict]) -> list[dict]:
    """Each charge is judged against the REST of its category (so a huge one cannot hide itself in the mean/sd)."""
    fixed = ("emi", "housing")
    pool = [t for t in txns if t["category"] not in fixed]
    out = []
    for k, t in enumerate(txns):
        if t["category"] in fixed or t["amount"] < 5000 and not (income and t["amount"] >= 0.05 * income):
            continue  # fixed payments are never flagged; small ones are not material
        if any(r["merchant"].lower() == (t.get("merchant") or "").lower() and abs(t["amount"] - r["amount"]) <= RECURRING_TOL * r["amount"] for r in recurring):
            continue
        same = [x["amount"] for x in txns if x["category"] == t["category"] and x is not t]
        if len(same) + 1 >= 4:  # ponytail: robust median/MAD; fewer than 4 rows -> compare with all discretionary spend
            med = median(same)
            limit = max(3 * med, med + 4 * max(median(abs(x - med) for x in same), 0.1 * med))
        else:
            others = [x["amount"] for x in pool if x is not t]
            if not others:
                continue
            med = median(others)
            limit = 3 * med
        if t["amount"] > limit:
            out.append({"date": t["date"], "merchant": t.get("merchant") or "Unknown", "amount": round(t["amount"], 2),
                        "category": t["category"], "why": f"about {t['amount'] / med:.0f}x your usual spend in this category (typically {_inr(med)})"})
    return sorted(out, key=lambda u: -u["amount"])[:5]


def insights(txns: list[dict], profile: dict | None) -> dict[str, Any]:
    if len(txns) < MIN_TRANSACTIONS:
        return {"available": False, "reason": UNAVAILABLE}
    income = (profile or {}).get("monthly_income") or None
    ds = sorted(t["date"][:7] for t in txns)
    months = _months_between(ds[0], ds[-1])
    n = len(months)
    emi_tot = spent(txns, "emi")
    spend_tot = round(spent(txns) - emi_tot, 2)
    spend_avg, emi_avg = spend_tot / n, emi_tot / n
    by_month = [{"month": m, "spend": round(spent(txns, month=m) - spent(txns, "emi", m), 2), "emi": spent(txns, "emi", m)}
                for m in months]
    for r in by_month:
        r["net"] = round(income - r["spend"] - r["emi"], 2) if income else None
    total = spend_tot + emi_tot
    cats = []
    for name in sorted({t["category"] for t in txns}, key=lambda c: -spent(txns, c)):
        tot = spent(txns, name)
        prev = spent(txns, name, months[-2]) if n > 1 else 0
        bench = BENCHMARKS.get(name)
        share_inc = round(tot / n / income * 100, 1) if income else None
        cats.append({"name": name, "total": tot, "monthly_avg": round(tot / n, 2),
                     "share_of_spend": round(tot / total * 100, 1), "share_of_income": share_inc,
                     "trend_pct": round((spent(txns, name, months[-1]) - prev) / prev * 100, 1) if prev else None,
                     "benchmark_pct": bench if income else None,
                     "over_benchmark": bool(bench and share_inc is not None and share_inc > bench)})
    merchants: dict[str, dict] = {}
    for t in txns:
        m = merchants.setdefault((t.get("merchant") or "Unknown").lower(), {"merchant": t.get("merchant") or "Unknown", "total": 0.0, "count": 0})
        m["total"], m["count"] = round(m["total"] + t["amount"], 2), m["count"] + 1
    recurring = _recurring(txns)
    unusual = _unusual(txns, income, recurring)

    tips, notes = [], []
    for c in cats:
        if c["over_benchmark"]:
            trim = round(c["monthly_avg"] - c["benchmark_pct"] / 100 * income)
            tips.append({"title": f"Trim {c['name']} spending",
                         "detail": f"{c['name'].title()} is {c['share_of_income']}% of your income against a {c['benchmark_pct']}% guideline. "
                                   f"Cutting about {_inr(trim)} a month brings it to the guideline.",
                         "saving_per_month": trim, "priority": "high" if c["share_of_income"] - c["benchmark_pct"] > 5 else "medium"})
    subs = [r for r in recurring if r["category"] not in ("emi", "housing", "food", "transport")]  # food/transport repeats are habits, not subscriptions
    if subs:
        yearly = sum(r["amount"] * 12 for r in subs)
        tips.append({"title": "Review your recurring payments",
                     "detail": "; ".join(f"{r['merchant']} {_inr(r['amount'])}/month" for r in subs[:6])
                               + f". Together about {_inr(yearly)} a year. Review these and cancel what you do not use.",
                     "saving_per_month": None, "priority": "low"})
    if unusual:
        u = unusual[0]
        d = date.fromisoformat(u["date"])
        tips.append({"title": f"Verify the {_inr(u['amount'])} charge at {u['merchant']} on {d.day} {_MONTHS[d.month - 1]}",
                     "detail": f"It is {u['why']}. Check you recognise it.", "saving_per_month": None, "priority": "high"})
    if income:
        if emi_avg / income * 100 > EMI_WARN_PCT:
            tips.append({"title": "EMIs are heavy", "detail": f"EMIs take {emi_avg / income * 100:.0f}% of your income; "
                         f"keep them under {EMI_WARN_PCT}%.", "saving_per_month": None, "priority": "high"})
        if spend_avg + emi_avg > income:
            gap = round(spend_avg + emi_avg - income)
            tips.append({"title": "You are overspending", "detail": f"You spend about {_inr(gap)} a month more than you earn.",
                         "saving_per_month": gap, "priority": "high"})
    else:
        notes.append("Add your monthly income in Profile to see your savings rate and how each category compares with guidelines.")
    if n < 2:
        notes.append("Only one month of data, so there are no trends yet.")
    tips.sort(key=lambda s: {"high": 0, "medium": 1, "low": 2}[s["priority"]])
    return {"available": True, "reason": None, "period": {"from": min(t["date"] for t in txns), "to": max(t["date"] for t in txns), "months": n},
            "cashflow": {"income_avg": income, "spend_avg": round(spend_avg, 2), "emi_avg": round(emi_avg, 2),
                         "savings_rate": round((income - spend_avg - emi_avg) / income * 100, 1) if income else None,
                         "by_month": by_month},
            "categories": cats, "top_merchants": sorted(merchants.values(), key=lambda m: -m["total"])[:8],
            "recurring": recurring, "subscriptions": subs, "fixed_bills": [r for r in recurring if r["category"] in ("emi", "housing")], "unusual": unusual, "suggestions": tips, "notes": notes}


# ── chat ─────────────────────────────────────────────────────────────────
_CATS = (("emi", r"\bemis?\b|loans?"), ("housing", r"rent|housing"), ("food", r"food|grocer|dining|restaurant|eating"),
         ("transport", r"transport|fuel|petrol|cab|commute"), ("utilities", r"utilit|electric|\bbills?\b"),
         ("entertainment", r"entertain|movies?|subscription"), ("medical", r"medical|health|pharmac|doctor"))
_MONTH_RE = "|".join(m.lower() for m in _MONTHS)


def parse_spend_query(t: str, txns: list[dict]) -> dict[str, Any]:
    """Category / merchant / month from 'how much did I spend on food last month' (all optional)."""
    latest = max(x["date"][:7] for x in txns)
    ref = min(date.today().strftime("%Y-%m"), latest)  # statements are uploaded after the period: clamp to the data
    prev = f"{int(ref[:4]) - 1}-12" if ref[5:] == "01" else f"{ref[:5]}{int(ref[5:]) - 1:02d}"
    month = ref if "this month" in t else prev if "last month" in t else None
    if (m := re.search(rf"\b({_MONTH_RE})[a-z]*\b(?:\s+(\d{{4}}))?", t)) and not month:
        mm = f"{_MONTHS.index(m.group(1).capitalize()) + 1:02d}"
        year = m.group(2) or next((y for y in sorted({x["date"][:4] for x in txns}, reverse=True) if f"{y}-{mm}" in {x["date"][:7] for x in txns}), ref[:4])
        month = f"{year}-{mm}"
    category = next((c for c, p in _CATS if re.search(p, t)), None)
    merchant = None
    if not category and (m := re.search(r"\b(?:on|at|for|to)\s+(?!my\b|the\b)([a-z0-9&'.]+(?: [a-z0-9&'.]+)?)", t)):
        w = m.group(1).split()
        merchant = " ".join(x for x in w if x not in ("last", "this", "in", "total", "overall", "so", "every", "per", "during") and not re.fullmatch(_MONTH_RE + "[a-z]*", x))
    return {"category": category, "merchant": merchant or None, "month": month}


def chat_result(kind: str, args: dict, txns: list[dict], profile: dict | None) -> dict[str, Any]:
    """Numbers for a chat question (narrated by the LLM, or by chat_template when it is unavailable)."""
    if kind == "spent":
        total = spent(txns, args["category"], args["month"], args["merchant"])
        return {"kind": kind, **args, "total": total, "count": sum(1 for t in txns if (not args["category"] or t["category"] == args["category"])
                and (not args["month"] or t["date"][:7] == args["month"]) and (not args["merchant"] or args["merchant"] in (t.get("merchant") or "").lower()))}
    ins = insights(txns, profile)
    if kind == "top":
        return {"kind": kind, "top_merchants": ins.get("top_merchants") or sorted(
            ({"merchant": t.get("merchant"), "total": t["amount"], "count": 1} for t in txns), key=lambda m: -m["total"])[:8]}
    return {"kind": kind, **ins}


def chat_template(res: dict) -> str:
    kind = res["kind"]
    if kind == "spent":
        what = res["merchant"] or res["category"] or "everything"
        when = f"in {month_label(res['month'])}" if res["month"] else "in total"
        return (f"Insight: You spent {_inr(res['total'])} on {what} {when} across {res['count']} transactions.\n"
                "Analysis: This comes straight from your uploaded transactions.\nRecommendation: Ask where you can cut to see ways to lower it.\n"
                "Risk: Cash payments and anything not in the statement are not counted.")
    if kind == "top":
        return ("Insight: Your biggest spending by merchant: " + "; ".join(f"{m['merchant']} {_inr(m['total'])}" for m in res["top_merchants"][:5]) + ".\n"
                "Analysis: These account for most of your outgoings.\nRecommendation: Start trimming from the largest discretionary ones.\nRisk: Totals cover only the uploaded period.")
    if not res["available"]:
        return f"{res['reason'].capitalize()}. I need at least 10 transactions to analyse your spending."
    cf, cats = res["cashflow"], res["categories"]
    if kind == "trend":
        return ("Insight: Monthly spending: " + "; ".join(f"{month_label(r['month'])} {_inr(r['spend'] + r['emi'])}" for r in cf["by_month"]) + ".\n"
                "Analysis: Includes EMIs.\nRecommendation: Look at the month that jumps and find the category behind it.\nRisk: The latest month may be incomplete.")
    if kind == "recurring":
        r, fixed = res["subscriptions"], res["fixed_bills"]
        body = "; ".join(f"{x['merchant']} {_inr(x['amount'])}/month (about {_inr(x['amount'] * 12)} a year)" for x in r) if r else "none found"
        bills = "; ".join(f"{x['merchant']} {_inr(x['amount'])}/month" for x in fixed)
        return (f"Insight: Subscriptions: {body}.\nAnalysis: Same merchant, similar amount, in two or more months" + (f". Fixed bills, not subscriptions: {bills}" if bills else "") + ".\n"
                "Recommendation: Review these and cancel what you do not use.\nRisk: Some may be shared or essential.")
    if kind == "unusual":
        u = res["unusual"]
        body = "; ".join(f"{x['merchant']} {_inr(x['amount'])} on {x['date']} ({x['why']})" for x in u) if u else "nothing stands out"
        return f"Insight: Unusual charges: {body}.\nAnalysis: Flagged when far above your usual for that category.\nRecommendation: Verify any you do not recognise.\nRisk: A large charge is not necessarily fraud."
    if kind == "cut":
        tips = "; ".join(f"{s['title']}: {s['detail']}".rstrip(".") for s in res["suggestions"]) or "no category is above its guideline"
        return f"Insight: {tips}.\nAnalysis: Guidelines are rules of thumb for share of income.\nRecommendation: Start with the highest-priority item.\nRisk: Your needs may differ from the rules of thumb."
    top = ", ".join(f"{c['name']} {_inr(c['monthly_avg'])}/month" for c in cats[:4])
    sr = f", savings rate {cf['savings_rate']}%" if cf["savings_rate"] is not None else ""
    return (f"Insight: You spend about {_inr(cf['spend_avg'] + cf['emi_avg'])} a month (EMI {_inr(cf['emi_avg'])}){sr}.\n"
            f"Analysis: Biggest categories: {top}.\nRecommendation: {res['suggestions'][0]['title'] if res['suggestions'] else 'Keep tracking monthly'}.\n"
            "Risk: Based only on the uploaded period.")
