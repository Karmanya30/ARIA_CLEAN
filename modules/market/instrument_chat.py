"""The FACTS about ONE instrument (quote, profile, return stats, a 5-year SIP, and for listed companies the user's saved
research report and recent headlines), a deterministic answer for plain lookups, and a facts-only summary.

This module is a context provider for the one answer pipeline: the prompt, the number check and the fallback loop live in
modules/qa/focus.py and modules/qa/trust.py, and run for every channel."""
from __future__ import annotations

import re
from typing import Any

from loguru import logger

from modules.market import instruments as I
from modules.qa import trust

ungrounded = trust.ungrounded  # the number check lives in modules/qa/trust.py (shared by every channel)


def _strip(d: dict, drop: tuple[str, ...]) -> dict:
    return {k: v for k, v in d.items() if k not in drop and v is not None}


def gather(it: dict, owner_id: str | None = None) -> dict[str, Any]:
    """Facts for the prompt. Each part is fetched on its own so one dead source only adds a line to "unavailable"."""
    facts: dict[str, Any] = {"instrument": {"id": it["id"], "name": it["name"], "type": it["type"], "exchange": it["exchange"], "currency": it["currency"]},
                             "unavailable": []}
    q = I.quote(it)
    if q.get("price") is None:
        facts["unavailable"].append(f"price/quote ({q.get('error', 'no data')})")
    facts["quote"] = _strip(q, ("id", "type", "source"))
    facts["quote"]["data_note"] = q.get("delay_note")
    try:
        p = I.profile(it)
        facts["what_is"] = p["what_is"]
        facts["description"] = p["description"]
        facts["risk_tags"] = [f"{t['tag']}: {t['why']}" for t in p["risk_tags"]]
        facts["return_and_risk_stats"] = p["stats"]
        if not p["stats"]:
            facts["unavailable"].append("price-history statistics (returns, volatility, drawdown)")
    except Exception as exc:
        facts["unavailable"].append(f"profile ({type(exc).__name__})")
    try:
        s = I.sip(it, 5000, 5)
        facts["sip_simulation"] = {k: s[k] for k in ("monthly", "years_used", "invested", "value", "xirr_pct", "cagr_pct", "worst_drawdown_pct", "start", "end")}
        facts["sip_simulation"]["note"] = "historical simulation of investing 5000 a month; " + I.CAVEAT
    except I.Unsupported:
        pass
    except Exception as exc:
        facts["unavailable"].append(f"SIP simulation ({type(exc).__name__})")
    if it["type"] == "stock" and owner_id:
        try:
            from shared.user_store import list_research_reports

            reps = list_research_reports(owner_id, it["symbol"])
            if reps:
                r = reps[0]
                facts["aria_saved_research"] = {k: r.get(k) for k in ("rating", "stance", "fair_value", "price", "upside_pct", "confidence", "data_as_of", "created_at")
                                                if r.get(k) is not None}
        except Exception as exc:
            logger.debug(f"saved research lookup skipped: {type(exc).__name__}")
    if it["type"] in ("stock", "etf", "crypto", "commodity", "index"):
        try:
            from shared.news import fetch_news

            news = fetch_news(re.sub(r"\b(limited|ltd|inc\.?|corp\w*)\b", "", it["name"], flags=re.I).strip(), limit=4)
            if news:
                facts["news"] = [{"headline": n["title"], "source": n.get("source", ""), "age_hours": n.get("age_hours")} for n in news]
        except Exception as exc:
            logger.debug(f"news skipped: {type(exc).__name__}")
    return facts


def _f(x: Any, nd: int = 2) -> str:
    return f"{x:,.{nd}f}"


def plain_summary(facts: dict, why: str) -> str:
    """Deterministic answer from the facts alone (used when the model is down or its numbers cannot be traced)."""
    i, q, st = facts["instrument"], facts["quote"], facts.get("return_and_risk_stats", {})
    ccy = f" {i['currency']}" if i["currency"] and i["currency"] != "INR" else ""
    rupee = "₹" if i["currency"] == "INR" else ""
    parts = [why]
    if q.get("price") is not None:
        label = "NAV" if i["type"] == "mutual_fund" else "yield" if q.get("yield") is not None else "price"
        unit = "%" if label == "yield" else ""
        line = f"{q.get('name', i['name'])}: latest {label} {rupee}{_f(q['price'], 4 if abs(q['price']) < 1 else 2)}{unit}{ccy if label != 'yield' else ''}"
        if q.get("change_pct") is not None:
            line += f", {q['change_pct']:+.2f}% versus the previous reading"
        parts.append(line + f" (as of {str(q.get('as_of'))[:10]})." + (" This data is stale." if q.get("stale") else ""))
    else:
        parts.append(f"I could not fetch a current price for {i['name']} right now.")
    bits = [f"{lab} {st[k]:+.2f}%" for k, lab in (("return_1y_pct", "1-year return"), ("cagr_3y_pct", "3-year CAGR"), ("cagr_5y_pct", "5-year CAGR")) if st.get(k) is not None]
    if st.get("volatility_1y_pct") is not None:
        bits.append(f"1-year volatility {st['volatility_1y_pct']:.1f}%")
    if st.get("max_drawdown_1y_pct") is not None:
        bits.append(f"worst fall in the last year {st['max_drawdown_1y_pct']:.1f}%")
    if bits:
        parts.append("History: " + "; ".join(bits) + ". " + I.CAVEAT)
    if st.get("cagr_since_start_pct") is not None:
        start, end = st.get("first_date"), st.get("last_date")
        period = f" from {start} to {end}" if start and end else ""
        parts.append(f"Since-start CAGR: {st['cagr_since_start_pct']:+.2f}%{period}. Total return over the same history was {st.get('return_since_start_pct'):+.2f}%." if st.get("return_since_start_pct") is not None
                     else f"Since-start CAGR: {st['cagr_since_start_pct']:+.2f}%{period}.")
    if facts.get("risk_tags"):
        parts.append("Risks: " + " ".join(facts["risk_tags"][:3]))
    if facts.get("unavailable"):
        parts.append("Not available right now: " + "; ".join(facts["unavailable"]) + ".")
    parts.append("This is not investment advice.")
    return "\n\n".join(parts)


def direct_answer(facts: dict, question: str) -> str | None:
    """Answer high-confidence numeric questions directly from fetched facts, without needing a model round trip."""
    ql = question.lower()
    if re.search(r"\b(target|fair value|should i buy|should i sell|buy|sell|hold)\b", ql):
        return None
    i, q, st = facts["instrument"], facts["quote"], facts.get("return_and_risk_stats", {})
    name = q.get("name") or i["name"]
    as_of = str(q.get("as_of") or st.get("last_date") or "")[:10]
    if re.search(r"\bcagr\b|compound annual", ql) and re.search(r"since start|inception|launch|start", ql):
        cagr = st.get("cagr_since_start_pct")
        if cagr is None:
            return None
        start, end = st.get("first_date"), st.get("last_date")
        total = st.get("return_since_start_pct")
        line = f"{name}'s CAGR since the available history starts is {cagr:+.2f}%"
        if start and end:
            line += f", measured from {start} to {end}"
        line += "."
        if total is not None:
            line += f" The total return over that same period is {total:+.2f}%."
        return line + "\n\nThis is not investment advice."
    if re.search(r"\b(returns?|performance)\b", ql):
        bits = [f"{lab} {st[k]:+.2f}%" for k, lab in (("return_1y_pct", "1-year return"), ("cagr_3y_pct", "3-year CAGR"),
                                                       ("cagr_5y_pct", "5-year CAGR"), ("cagr_since_start_pct", "since-start CAGR"))
                if st.get(k) is not None]
        if bits:
            date_note = f" as of {as_of}" if as_of else ""
            return f"For {name}{date_note}: " + "; ".join(bits) + f". {I.CAVEAT}\n\nThis is not investment advice."
    # A target/forecast is not a request for today's quote.
    if re.search(r"\b(nav|price|level|quote)\b", ql) and not re.search(r"\b(target|forecast|predict|future|next)\b", ql) and q.get("price") is not None:
        label = "NAV" if i["type"] == "mutual_fund" else "yield" if q.get("yield") is not None else "price"
        rupee = "₹" if i["currency"] == "INR" and label != "yield" else ""
        unit = "%" if label == "yield" else (f" {i['currency']}" if i["currency"] and i["currency"] != "INR" else "")
        move = f", {q['change_pct']:+.2f}% versus the previous reading" if q.get("change_pct") is not None else ""
        date_note = f" as of {as_of}" if as_of else ""
        return f"{name}'s latest {label} is {rupee}{_f(q['price'], 4 if abs(q['price']) < 1 else 2)}{unit}{move}{date_note}.\n\nThis is not investment advice."
    return None
