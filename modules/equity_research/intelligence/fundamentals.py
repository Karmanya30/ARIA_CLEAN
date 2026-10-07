"""
Fundamental analysis: is the business getting stronger, are the profits real, does it create value, can it fund the growth
the forecast assumes, what would it be worth on its book and excess returns, and what the news says about its future.

Deterministic, like the rest of the report: every score and value is arithmetic on the statements already in the ledger,
recorded there with its formula, and a test that cannot be run says so instead of guessing.

- Piotroski F-score (Piotroski 2000, "Value Investing: The Use of Historical Financial Statement Information"): nine
  pass/fail signals of profitability, balance-sheet strength and efficiency.
- Earnings quality: cash conversion and the Sloan (1996) accruals ratio.
- Value creation: ROIC against WACC.
- Fundamental growth (Damodaran): growth a company can fund = reinvestment rate x return on capital (for lenders:
  ROE x retention). Checks the forecast's growth against what the business actually reinvests.
- Owner earnings (Buffett, 1986 letter): profit + depreciation - capex - working-capital build.
- Residual income model (Edwards-Bell-Ohlson; as used in ai-hedge-fund, MIT): book value + discounted excess returns.
- Investor lenses (lenses.py): Graham, Buffett, Lynch, Greenblatt, EVA and a technical read, then a six-pillar scorecard and
  an overlay that reads it against the valuation call.
- Sentiment with FinBERT (Araci 2019; ProsusAI/finBERT, Apache-2.0): every recent headline, and the sentences of the latest
  earnings-call transcript (management's tone, plus the forward-looking statements quoted verbatim by theme). Where FinBERT is
  not installed, headlines fall back to fixed keyword rules and the call is quoted unscored.

Every headline figure is also registered on the analysis facts, so the written commentary and the bull/bear debate are shown it
as evidence they can cite.
"""
from __future__ import annotations

import re
from datetime import date

from modules.equity_research.intelligence import lenses, sentiment
from modules.equity_research.intelligence.analysis import Analysis, fy, median_recent
from modules.equity_research.intelligence.data import Snapshot
from modules.equity_research.intelligence.facts import CALCULATED, Ledger, fmt
from modules.equity_research.intelligence.valuation import NotApplicable, Valuation, residual_income

SOURCE = "ARIA fundamental analysis (screener.in statements)"
PIOTROSKI_STRONG, PIOTROSKI_WEAK = 7, 3  # of 9: Piotroski's high (8-9) and low (0-2) groups, widened by one each way for missing signals
GROWTH_TOLERANCE = 0.04  # forecast growth within +/-4pp of fundamental growth counts as consistent
REINVEST_YEARS = 3


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def analyze_fundamentals(snap: Snapshot, an: Analysis, val: Valuation, ledger: Ledger) -> dict:
    if not an.latest:
        return {"available": False, "reason": "no annual statements"}
    out = {"available": True, "piotroski": _piotroski(snap, an, ledger), "quality": _quality(an, ledger), "value_creation": _value_creation(an, val, ledger),
           "growth_check": _growth_check(snap, an, val, ledger), "owner_earnings": _owner_earnings(snap, an, ledger),
           "residual_income": _rim(snap, an, val, ledger),
           "lenses": {"graham": lenses.graham(snap, an, ledger), "buffett": lenses.buffett(snap, an, ledger), "lynch": lenses.lynch(snap, an, ledger),
                      "greenblatt": lenses.greenblatt(snap, an, val, ledger)},
           "technical": lenses.technical(an), "news_signals": news_signals(snap.news), "concall": concall_signals(snap.concall),
           "documents": snap.documents}
    for key, label, node, method in (("news_net", "News sentiment (net, FinBERT)", out["news_signals"], "recency-weighted mean of (positive - negative) probability across recent headlines"),
                                     ("call_tone", "Earnings-call tone (net, FinBERT)", out["concall"], "mean of (positive - negative) probability across the call's sentences")):
        if node.get("net") is not None:
            an.facts[key] = ledger.add(label, node["net"], "", node.get("period") or "recent", "FinBERT (ProsusAI/finBERT) on " + ("recent headlines" if key == "news_net" else f"the {node.get('period')} earnings-call transcript"),
                                       CALCULATED, method=method)
    out["scorecard"] = lenses.scorecard(snap, an, val, out)
    out["intelligence"] = intel = lenses.intelligence(out, val)
    if intel["score"] is not None:
        lenses._reg(ledger, an, "intelligence_score", "Intelligence score", intel["score"], "/100", "today",
                    f"{intel['band']}: weighted blend of the scorecard pillars, valuation upside and news/call tone; {len(intel['divergences'])} divergence(s) flagged")
    an.fundamentals = out  # the report reads it from here; the pipeline computes it before the commentary so it can cite it
    return out


# ── Piotroski F-score ───────────────────────────────────────────────────────
def _piotroski(snap: Snapshot, an: Analysis, ledger: Ledger) -> dict:
    if snap.is_financial:
        return {"available": False, "reason": "The F-score was built for operating companies; a lender's leverage, cash flow and margins mean something else."}
    s, years = an.series, an.years
    if len(years) < 2:
        return {"available": False, "reason": "needs two fiscal years"}
    L, P = years[-1], years[-2]
    g = lambda k, c: s.get(k, {}).get(c)  # noqa: E731
    roa = lambda c: _div(g("pat", c), g("total_assets", c))  # noqa: E731
    lev = lambda c: _div(g("borrowings", c), g("total_assets", c))  # noqa: E731
    turn = lambda c: _div(g("revenue", c), g("total_assets", c))  # noqa: E731

    def test(group, name, a, b, op, show):
        if a is None or b is None:
            return {"group": group, "test": name, "passed": None, "detail": "not available in the statements"}
        return {"group": group, "test": name, "passed": bool(op(a, b)), "detail": show(a, b)}

    pct = lambda a, b: f"{a:.1%} vs {b:.1%}"  # noqa: E731
    cr = lambda a, b: f"{fmt(a, '₹ Cr')} vs {fmt(b, '₹ Cr')}"  # noqa: E731
    signals = [
        test("Profitability", f"Return on assets is positive ({fy(L)})", roa(L), 0.0, lambda a, b: a > b, lambda a, b: f"ROA {a:.1%}"),
        test("Profitability", f"Operating cash flow is positive ({fy(L)})", g("cfo", L), 0.0, lambda a, b: a > b, lambda a, b: f"CFO {fmt(a, '₹ Cr')}"),
        test("Profitability", f"Return on assets improved ({fy(L)} vs {fy(P)})", roa(L), roa(P), lambda a, b: a > b, pct),
        test("Profitability", "Operating cash flow exceeds net profit (low accruals)", g("cfo", L), g("pat", L), lambda a, b: a > b, cr),
        test("Leverage and liquidity", "Leverage fell (borrowings / total assets)", lev(L), lev(P), lambda a, b: a < b, pct),
        {"group": "Leverage and liquidity", "test": "Current ratio improved", "passed": None,
         "detail": "needs current assets and liabilities for two years; screener.in does not itemise them"},
        test("Leverage and liquidity", "No new shares issued (equity capital not up)", g("equity_capital", L), g("equity_capital", P), lambda a, b: a <= b * 1.001, cr),
        test("Operating efficiency", "Margin improved (operating margin, the gross-margin proxy)", g("opm", L), g("opm", P), lambda a, b: a > b, pct),
        test("Operating efficiency", "Asset turnover improved (revenue / total assets)", turn(L), turn(P), lambda a, b: a > b, lambda a, b: f"{a:.2f}x vs {b:.2f}x"),
    ]
    tested = [x for x in signals if x["passed"] is not None]
    score = sum(1 for x in tested if x["passed"])
    if len(tested) < 6:
        return {"available": False, "reason": f"only {len(tested)} of 9 signals are testable", "signals": signals}
    verdict = "strong" if score >= PIOTROSKI_STRONG else ("weak" if score <= PIOTROSKI_WEAK else "middling")
    fact = an.facts["piotroski"] = ledger.add("Piotroski F-score", score, f"of {len(tested)}", fy(L), SOURCE, CALCULATED,
                                              method=f"{verdict}: one point per passed signal; {9 - len(tested)} of the 9 signals could not be tested")
    return {"available": True, "score": score, "tested": len(tested), "verdict": verdict, "signals": signals, "fact": fact.id}


# ── earnings quality ────────────────────────────────────────────────────────
def _quality(an: Analysis, ledger: Ledger) -> dict:
    s, years = an.series, an.years
    L = years[-1]
    conv = median_recent([s["cfo_pat"].get(c) for c in years])
    out: dict = {"cash_conversion": conv}
    if len(years) > 1:
        ta = [s["total_assets"].get(c) for c in years[-2:]]
        pat, cfo = s["pat"].get(L), s["cfo"].get(L)
        if None not in ta and pat is not None and cfo is not None:
            acc = (pat - cfo) / ((ta[0] + ta[1]) / 2)
            out["accruals"] = acc
            an.facts["accruals"] = ledger.add("Accruals ratio (Sloan)", acc * 100, "%", fy(L), SOURCE, CALCULATED,
                                              method="(net profit - operating cash flow) / average total assets; negative = profits backed by cash")
            out["accruals_fact"] = an.facts["accruals"].id
    if conv is not None:
        out["verdict"] = "cash-backed" if conv >= 0.9 else ("partly cash-backed" if conv >= 0.6 else "weakly cash-backed")
    return out


# ── value creation ──────────────────────────────────────────────────────────
def _value_creation(an: Analysis, val: Valuation, ledger: Ledger) -> dict:
    roic, wacc = an.facts.get("roic"), val.facts.get("wacc")
    if not roic or not wacc:
        return {"available": False, "reason": "needs both ROIC and WACC"}
    spread = roic.value - wacc.value
    f = an.facts["roic_spread"] = ledger.add("ROIC - WACC spread", spread, "pp", roic.period, SOURCE, CALCULATED, inputs=[roic, wacc],
                                             method="return on invested capital minus the weighted cost of capital; positive = each rupee invested earns more than it costs")
    return {"available": True, "roic": roic.value, "wacc": wacc.value, "spread": spread, "creates_value": spread > 0, "fact": f.id}


# ── fundamental growth vs the forecast ──────────────────────────────────────
def _growth_check(snap: Snapshot, an: Analysis, val: Valuation, ledger: Ledger) -> dict:
    s, years = an.series, an.years
    L = years[-1]
    if snap.is_financial:
        roe, payout = s["roe"].get(L), s["payout"].get(L)
        model = val.ddm_inputs.growth[0] if val.ddm_inputs else None
        if roe is None or payout is None:
            return {"available": False, "reason": "needs ROE and dividend payout"}
        fundamental, how = roe * (1 - payout), "ROE x (1 - payout): the growth retained profits can fund without new capital"
        parts = {"roe": roe, "retention": 1 - payout}
    else:
        roic = an.facts.get("roic")
        window = years[-REINVEST_YEARS - 1:]  # one extra year for the first working-capital change
        nwc = {c: s["nwc_pct"][c] * s["revenue"][c] for c in window if s["nwc_pct"].get(c) is not None and s["revenue"].get(c)}
        reinvest = nopat = 0.0
        used = []
        for p, c in zip(window, window[1:]):
            ebit, capex, dep, tax = s["ebit"].get(c), s["capex"].get(c), s["dep"].get(c), s["tax_rate"].get(c)
            if None in (ebit, capex, dep) or p not in nwc or c not in nwc:
                continue
            tax = tax if tax is not None and 0 <= tax <= 0.45 else 0.2517
            reinvest += capex - dep + (nwc[c] - nwc[p])
            nopat += ebit * (1 - tax)
            used.append(c)
        if roic is None or len(used) < 2 or nopat <= 0:
            return {"available": False, "reason": "needs ROIC and at least two years of EBIT, capex, depreciation and working capital"}
        rate = reinvest / nopat
        fundamental = rate * roic.value / 100 if reinvest > 0 else None
        how = (f"reinvestment rate x ROIC, over {fy(used[0])}–{fy(used[-1])} (summed, because one year of working capital can swing a lot): "
               "reinvestment = capex - depreciation + increase in working capital, over NOPAT")
        parts = {"reinvestment_rate": rate, "roic": roic.value / 100, "reinvestment": reinvest, "nopat": nopat, "years": len(used)}
        model = val.dcf_inputs.growth[0] if val.dcf_inputs else None
    if fundamental is None:  # net reinvestment <= 0: no growth number to record
        return {"available": True, "fundamental": None, "model": model, "how": how, **parts,
                "note": "the business has been releasing capital over these years (working capital falling and/or capex below depreciation), so "
                        "reinvestment x ROIC cannot say what growth it can fund; its growth is being financed by customers' and suppliers' money, "
                        "which cannot grow forever"}
    f = an.facts["fundamental_growth"] = ledger.add("Fundamental growth", fundamental * 100, "%", fy(L), SOURCE, CALCULATED, method=how)
    out = {"available": True, "fundamental": fundamental, "model": model, "how": how, **parts, "fact": f.id}
    if model is not None:
        gap = model - fundamental
        out["verdict"] = ("consistent with what the business reinvests" if abs(gap) <= GROWTH_TOLERANCE else
                          "ahead of what current reinvestment supports: it needs higher returns on capital or more capital" if gap > 0 else
                          "below what current reinvestment could fund: the forecast is conservative on this measure")
    return out


# ── owner earnings ──────────────────────────────────────────────────────────
def _owner_earnings(snap: Snapshot, an: Analysis, ledger: Ledger) -> dict:
    if snap.is_financial:
        return {"available": False, "reason": "not meaningful for a lender (its working capital is its loan book)"}
    s, years = an.series, an.years
    L = years[-1]
    pat, dep, capex = s["pat"].get(L), s["dep"].get(L), s["capex"].get(L)
    nwc = [s["nwc_pct"].get(c) * s["revenue"][c] if s["nwc_pct"].get(c) is not None and s["revenue"].get(c) else None for c in years[-2:]]
    mcap = an.facts.get("market_cap")
    if None in (pat, dep, capex) or len(nwc) < 2 or None in nwc:
        return {"available": False, "reason": "needs net profit, depreciation, capex and working capital for two years"}
    oe = pat + dep - capex - (nwc[1] - nwc[0])
    out = {"available": True, "value": oe, "pat": pat, "dep": dep, "capex": capex, "nwc_change": nwc[1] - nwc[0]}
    f = an.facts["owner_earnings"] = ledger.add("Owner earnings", oe, "₹ Cr", fy(L), SOURCE, CALCULATED,
                                                method="net profit + depreciation - total capex - increase in working capital (all capex treated as needed: conservative)")
    out["fact"] = f.id
    if mcap and mcap.value > 0:
        out["yield"] = oe / mcap.value
        an.facts["oe_yield"] = ledger.add("Owner-earnings yield", oe / mcap.value * 100, "%", "today", SOURCE, CALCULATED, inputs=[f, mcap], method="owner earnings / market capitalisation")
    return out


# ── residual income model ───────────────────────────────────────────────────
def _rim(snap: Snapshot, an: Analysis, val: Valuation, ledger: Ledger) -> dict:
    s, L = an.series, an.latest
    nw, coe_f = s["net_worth"].get(L), val.facts.get("coe")
    shares_cr = snap.shares / 1e7 if snap.shares else None
    roe = median_recent([s["roe"].get(c) for c in an.years])
    payout = s["payout"].get(L)
    if None in (nw, coe_f, shares_cr, roe):
        return {"available": False, "reason": "needs net worth, shares, ROE and the cost of equity"}
    payout = min(max(payout or 0.0, 0.0), 1.0)
    try:
        r = residual_income(nw / shares_cr, roe, coe_f.value / 100, payout)
    except NotApplicable as exc:
        return {"available": False, "reason": str(exc)}
    f = an.facts["rim_value"] = ledger.add("Residual income value per share", r["per_share"], "₹", "today", SOURCE, CALCULATED, inputs=[coe_f],
                                           method=f"book value per share + PV of (ROE - cost of equity) x book over 10 years; ROE {roe:.1%} (3-year median) fading to the "
                                                  f"{coe_f.value:.1f}% cost of equity, retaining {1 - payout:.0%} of profit")
    up = (r["per_share"] / snap.price - 1) if snap.price else None
    reading = ("" if up is None else
               "the price asks for returns well above the cost of equity for much longer than 10 years: it is paying for growth and franchise that "
               "today's returns on book alone do not show" if up < -0.4 else
               "book value plus excess returns roughly supports the price" if up < 0.15 else
               "book value plus excess returns is above the price")
    return {"available": True, **r, "roe": roe, "coe": coe_f.value / 100, "payout": payout, "upside": up, "reading": reading, "fact": f.id}


# ── forward-looking signals in the news ─────────────────────────────────────
_CATEGORIES = (  # first match wins, most specific first
    ("Orders and contracts", r"\b(order|orders|order book|orderbook|contract|contracts|bags|bagged|wins?|won|secures?|l1 bidder|tender)\b"),
    ("Guidance and outlook", r"\b(guidance|outlook|targets?|expects?|forecasts?|projects?|sees|aims?|plans? to|roadmap)\b"),
    ("Capacity and capex", r"\b(capex|capacity|plant|factory|expansion|expands?|commission(?:ed|s)?|greenfield|brownfield|new unit|invest(?:s|ment)?)\b"),
    ("M&A and stakes", r"\b(acquir\w*|acquisition|merger|merge|stake|takeover|buyout|divest\w*|demerger|joint venture|jv)\b"),
    ("Management and governance", r"\b(ceo|cfo|md|cmd|chairman|managing director|resign\w*|appoint\w*|board|promoter|pledge\w*|auditor)\b"),
    ("Regulatory and legal", r"\b(sebi|rbi|penalty|probe|raid|notice|court|tribunal|ban|licen[cs]e|approval|gst|cci|lawsuit|fine)\b"),
    ("Capital return", r"\b(dividend|buyback|bonus|split)\b"),
    ("Results", r"\b(q[1-4]|quarter\w*|results?|net profit|revenue|earnings|ebitda|margin)\b"),
)


NEWS_HALF_LIFE_DAYS = 14  # a headline's weight in the tone halves every two weeks


def _age_days(item: dict) -> int:
    try:
        return max(0, (date.today() - date.fromisoformat(str(item.get("date", ""))[:10])).days)
    except ValueError:
        return 0


def news_signals(news: list[dict], scorer=None) -> dict:
    """Sort the company's recent headlines into fundamental themes (keyword rules) and score their tone with FinBERT. Without
    FinBERT the direction falls back to fixed keyword rules and no tone number is produced."""
    news = news or []
    scores = (scorer or sentiment.score)([n.get("title", "") for n in news]) if news else None
    items, weighted, total = [], 0.0, 0.0
    for i, n in enumerate(news):
        title = n.get("title", "")
        cat = next((c for c, rx in _CATEGORIES if re.search(rx, title, re.I)), "Other")
        if scores:
            net = scores[i]["net"]
            items.append({**n, "category": cat, "direction": sentiment.label(net), "net": net})
            w = 0.5 ** (_age_days(n) / NEWS_HALF_LIFE_DAYS)
            weighted, total = weighted + w * net, total + w
        else:
            up, down = bool(sentiment._UP.search(title)), bool(sentiment._DOWN.search(title))
            items.append({**n, "category": cat, "direction": "mixed" if up and down else ("positive" if up else "negative" if down else "neutral"), "net": None})
    summary: dict[str, dict] = {}
    for it in items:
        row = summary.setdefault(it["category"], {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0})
        row[it["direction"]] += 1
    method = ("Headlines (title, outlet, date): the tone of each is scored by FinBERT (Araci 2019), a language model trained on financial text, as the probability of "
              "positive minus negative (-1 to +1); the theme is set by keyword rules. Only the headline is read, not the article, so it is a pointer, not evidence of the outcome."
              if scores else
              "Headlines (title, outlet, date) sorted into themes and a direction by fixed keyword rules (FinBERT is not installed, so no tone score); "
              "the full article is not read, so a headline is a pointer for the reader, not evidence of the outcome.")
    return {"items": items, "summary": summary, "net": weighted / total if scores and total else None, "scored": len(items) if scores else 0, "method": method}


# ── the latest earnings call ────────────────────────────────────────────────
_CALL_THEMES = (
    ("Outlook and guidance", re.compile(r"\b(guidance|outlook|expect\w*|target\w*|confident|confidence|visibility|on track|trajectory|momentum|next (?:year|quarter)|FY\s?\d{2})\b", re.I)),
    ("Orders and pipeline", re.compile(r"\b(order (?:book|inflow|intake|prospects?)|pipeline|backlog|bids?|bidding|tenders?|awarded|L1)\b", re.I)),
    ("Margins and costs", re.compile(r"\b(margins?|cost|costs|inflation|commodity|pricing)\b", re.I)),
    ("Capex and capacity", re.compile(r"\b(capex|capital expenditure|capacity|expansion|invest\w*|plants?)\b", re.I)),
    ("Risks and headwinds", re.compile(r"\b(headwinds?|challeng\w*|pressures?|delays?|uncertain\w*|slow\w*|volatil\w*|geopolitic\w*|weak\w*|concerns?|risks?)\b", re.I)),
)
CALL_MAX_SCORED, CALL_PER_THEME = 120, 3


def _spread(items: list, n: int) -> list:
    """n items spread evenly across the list (all of them when there are fewer)."""
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def concall_signals(concall: dict | None, scorer=None) -> dict:
    """What management said on the latest earnings call: the tone of the whole call (FinBERT on its sentences) and, by theme,
    the sentences that speak to outlook, orders, margins, capacity and risks, quoted verbatim with their own tone. Quotes are the
    company's words from its published transcript, not paraphrase."""
    if not concall or not concall.get("sentences"):
        return {"available": False, "reason": "no earnings-call transcript could be read for this company (none listed on screener.in, or the PDF was not readable)"}
    sentences = concall["sentences"]
    themed = [x for x in sentences if any(rx.search(x) for _, rx in _CALL_THEMES)]
    pool = _spread(themed, CALL_MAX_SCORED * 2 // 3)
    pool += _spread([x for x in sentences if x not in set(pool)], CALL_MAX_SCORED - len(pool))
    scores = (scorer or sentiment.score)(pool)
    by_text = {t: sc for t, sc in zip(pool, scores)} if scores else {}
    themes: dict[str, list[dict]] = {}
    for name, rx in _CALL_THEMES:
        hits = [x for x in pool if rx.search(x)]
        # numbers make a sentence informative; for risks the most negative ones lead, otherwise the most decisive tone
        key = (lambda x: (bool(re.search(r"\d", x)), -by_text[x]["net"] if name == "Risks and headwinds" else abs(by_text[x]["net"]))) if scores else \
              (lambda x: (bool(re.search(r"\d", x)), len(x)))
        quotes = sorted(hits, key=key, reverse=True)[:CALL_PER_THEME]
        if quotes:
            themes[name] = [{"text": q[:320], "label": sentiment.label(by_text[q]["net"]) if scores else None, "net": by_text[q]["net"] if scores else None} for q in quotes]
    nets = [sc["net"] for sc in scores] if scores else []
    out = {"available": True, "period": concall.get("period"), "url": concall.get("url"), "n_sentences": len(sentences), "scored": len(nets),
           "net": sum(nets) / len(nets) if nets else None, "themes": themes,
           "positive_share": sum(1 for n in nets if n >= sentiment.THRESHOLD) / len(nets) if nets else None,
           "negative_share": sum(1 for n in nets if n <= -sentiment.THRESHOLD) / len(nets) if nets else None}
    out["method"] = (f"{len(nets)} of the call's {len(sentences)} sentences (all those on outlook, orders, margins, capacity and risks, plus an even sample of the rest) scored by FinBERT; "
                     "tone is the mean of positive minus negative probability (-1 to +1). Quotes are verbatim from the published transcript." if nets else
                     "FinBERT is not installed, so the call is quoted by theme but its tone is not scored. Quotes are verbatim from the published transcript.")
    return out
