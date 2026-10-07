"""
Classic investor frameworks, computed from the company's own statements, plus the scorecard that weighs everything.

Each lens asks a different question of the same numbers, with the thresholds its author published (the pass marks are
the framework's, not ARIA's, and the report shows them next to every result):

- Graham ("The Intelligent Investor", 1949/1973): the Graham number sqrt(22.5 x EPS x book value per share) as a price
  ceiling, and the defensive-investor checklist (modest P/E and P/B, a profit and dividend record, steady growth, modest debt).
- Buffett (Berkshire letters, 1977-): consistent high returns on equity, debt repayable from a few years' profit, free
  cash flow every year, compounding earnings, and the retained-earnings test (each rupee retained should add earnings).
- Lynch ("One Up on Wall Street", 1989): the PEG ratio, P/E divided by earnings growth, and his growth categories.
- Greenblatt ("The Little Book That Beats the Market", 2005): earnings yield (EBIT / enterprise value) together with
  return on capital: cheap and good.
- Economic value added (Stern Stewart): (ROIC - WACC) x invested capital, the rupees earned above the cost of capital.
- Technical read: trend, relative strength and momentum from the weekly price facts already on the ledger.

The scorecard turns these, with the Piotroski score, cash conversion, ROIC against WACC, safety checks and sentiment,
into six pillars (quality, valuation, growth, safety, technical, sentiment), each strong / mixed / weak by stated rules.
The overlay reads them against the valuation call. It never changes a number, the fair value or the rating: it tells the
reader how much weight the call deserves. Idea of investor-style lenses as in ai-hedge-fund (MIT); implementations here are independent.
"""
from __future__ import annotations

import math
import statistics

from config import settings
from modules.equity_research.intelligence.analysis import Analysis, cagr, fy
from modules.equity_research.intelligence.data import Snapshot
from modules.equity_research.intelligence.facts import CALCULATED, Ledger, fmt
from modules.equity_research.intelligence.valuation import Valuation

SOURCE = "ARIA fundamental analysis (screener.in statements, Yahoo Finance price)"
RIM_DEEP_DISCOUNT = -0.4  # residual-income value this far below the price: the price rests on growth the book does not show
SENTIMENT_EDGE = 0.25  # net sentiment (positive minus negative probability) beyond which a source counts as positive / negative


def _reg(ledger: Ledger, an: Analysis, key: str, label: str, value: float, unit: str, period: str, method: str, inputs=()):
    """Record a figure on the audited ledger AND on the analysis facts, which is what the written commentary and the
    bull/bear debate are shown as evidence."""
    fact = ledger.add(label, value, unit, period, SOURCE, CALCULATED, inputs=[i for i in inputs if i], method=method)
    an.facts[key] = fact
    return fact


def _check(name: str, ok: bool | None, detail: str) -> dict:
    return {"test": name, "passed": ok, "detail": detail}


def _known(series: dict, years: list[str]) -> list[float]:
    return [series[c] for c in years if series.get(c) is not None]


def _score(tests: list[dict]) -> tuple[int, int]:
    tested = [t for t in tests if t["passed"] is not None]
    return sum(1 for t in tested if t["passed"]), len(tested)


def _basics(snap: Snapshot, an: Analysis) -> dict:
    s, L = an.series, an.latest
    shares_cr = snap.shares / 1e7 if snap.shares else None
    nw = s["net_worth"].get(L)
    eps = an.ttm.get("eps") or s["eps"].get(L)
    return {"price": snap.price, "eps": eps, "bvps": nw / shares_cr if nw and shares_cr else None,
            "pe": snap.price / eps if snap.price and eps and eps > 0 else None}


# ── Graham ──────────────────────────────────────────────────────────────────
def graham(snap: Snapshot, an: Analysis, ledger: Ledger) -> dict:
    b, s, years = _basics(snap, an), an.series, an.years[-10:]
    price, eps, bvps, pe = b["price"], b["eps"], b["bvps"], b["pe"]
    if not price or eps is None or bvps is None:
        return {"available": False, "reason": "needs the price, earnings per share and book value per share"}
    pb = price / bvps if bvps > 0 else None
    out: dict = {"available": True, "eps": eps, "bvps": bvps}
    if eps > 0 and bvps > 0:
        gn = math.sqrt(22.5 * eps * bvps)
        out.update(number=gn, margin_of_safety=1 - price / gn)
        out["fact"] = _reg(ledger, an, "graham_number", "Graham number", gn, "₹", "today",
                           f"sqrt(22.5 x EPS {eps:.2f} x book value per share {bvps:.2f}): the highest price a defensive investor should pay; "
                           f"the price is {price / gn:.1f}x it").id
    eps_hist, payouts = _known(s["eps"], years), _known(s["payout"], years)
    n = min(len(an.years) - 1, 10)
    g = cagr([s["eps"].get(c) for c in an.years], n) if n >= 3 else None
    tests = [
        _check("P/E at most 15", None if pe is None else pe <= 15, "loss-making" if pe is None else f"{pe:.1f}x"),
        _check("P/B at most 1.5, or P/E x P/B at most 22.5", None if pb is None or pe is None else (pb <= 1.5 or pe * pb <= 22.5),
               "n/a" if pb is None or pe is None else f"P/B {pb:.1f}x, P/E x P/B {pe * pb:.1f}"),
        _check(f"Profit in each of the last {len(eps_hist)} years", None if len(eps_hist) < 5 else all(e > 0 for e in eps_hist),
               "fewer than 5 years of history" if len(eps_hist) < 5 else f"{sum(1 for e in eps_hist if e > 0)} of {len(eps_hist)} years"),
        _check(f"Dividend paid in each of the last {len(payouts)} years", None if len(payouts) < 5 else all(p > 0 for p in payouts),
               "fewer than 5 years of history" if len(payouts) < 5 else f"{sum(1 for p in payouts if p > 0)} of {len(payouts)} years"),
        _check(f"EPS growth of at least 3% a year over {n} years (Graham: a third in ten)", None if g is None else g >= 0.03,
               "needs 3+ years of positive EPS" if g is None else f"{g:.1%} a year"),
    ]
    if not snap.is_financial:
        de = s["de"].get(an.latest)
        tests.append(_check("Borrowings no more than net worth", None if de is None else de <= 1.0, "n/a" if de is None else f"{de:.2f}x"))
    out["tests"] = tests
    out["score"], out["tested"] = _score(tests)
    return out


# ── Buffett ─────────────────────────────────────────────────────────────────
def buffett(snap: Snapshot, an: Analysis, ledger: Ledger) -> dict:
    s, years = an.series, an.years[-10:]
    L = an.latest
    roe, fcf, opm = _known(s["roe"], years), _known(s["fcf"], years), _known(s["opm"], years)
    tests = [
        _check("Return on equity of 15% or more in at least 80% of years", None if len(roe) < 5 else sum(1 for r in roe if r >= 0.15) / len(roe) >= 0.8,
               "fewer than 5 years of ROE" if len(roe) < 5 else f"{sum(1 for r in roe if r >= 0.15)} of {len(roe)} years"),
        _check("Free cash flow positive in at least 80% of years", None if len(fcf) < 5 else sum(1 for f in fcf if f > 0) / len(fcf) >= 0.8,
               "fewer than 5 years" if len(fcf) < 5 else f"{sum(1 for f in fcf if f > 0)} of {len(fcf)} years"),
        _check("Operating margin steady (standard deviation at most 4pp)", None if len(opm) < 5 else statistics.pstdev(opm) <= 0.04,
               "fewer than 5 years" if len(opm) < 5 else f"{statistics.pstdev(opm) * 100:.1f}pp over {len(opm)} years"),
    ]
    pat, bor = s["pat"].get(L), s["borrowings"].get(L)
    if not snap.is_financial:
        tests.append(_check("Debt repayable from 3 years of profit", None if pat is None or bor is None or pat <= 0 else bor <= 3 * pat,
                            "n/a" if pat is None or bor is None or pat <= 0 else f"{bor / pat:.1f} years of profit"))
    n = min(5, len(an.years) - 1)
    g = cagr([s["eps"].get(c) for c in an.years], n) if n >= 3 else None
    tests.append(_check(f"EPS compounding at 8% or more a year over {n} years", None if g is None else g >= 0.08, "needs 3+ years" if g is None else f"{g:.1%} a year"))
    # the retained-earnings test: the profit the business keeps should come back as more profit
    win = an.years[-n - 1:] if n >= 3 else []
    kept = [s["pat"][c] * (1 - s["payout"][c]) for c in win[1:] if s["pat"].get(c) is not None and s["payout"].get(c) is not None]
    if win and len(kept) == n and sum(kept) > 0 and s["pat"].get(win[0]) is not None and pat is not None:
        added = (pat - s["pat"][win[0]]) / sum(kept)
        tests.append(_check("Retained earnings test: each rupee kept adds 15 paise or more of annual profit", added >= 0.15,
                            f"profit rose {fmt(pat - s['pat'][win[0]], '₹ Cr')} on {fmt(sum(kept), '₹ Cr')} retained over {n} years ({added:.0%})"))
    out = {"available": True, "tests": tests}
    out["score"], out["tested"] = _score(tests)
    if out["tested"] < 3:
        return {"available": False, "reason": "fewer than 3 of the tests could be run on the available history"}
    out["fact"] = _reg(ledger, an, "buffett_score", "Buffett quality checks passed", out["score"], f"of {out['tested']}", fy(L),
                       "consistency tests of return on equity, cash flow, margin, debt, earnings growth and retained earnings").id
    return out


# ── Lynch ───────────────────────────────────────────────────────────────────
def lynch(snap: Snapshot, an: Analysis, ledger: Ledger) -> dict:
    pe = _basics(snap, an)["pe"]
    s = an.series
    g = cagr([s["eps"].get(c) for c in an.years], 3) if len(an.years) > 3 else None
    if pe is None or g is None or g <= 0:
        return {"available": False, "reason": "needs a positive P/E and positive 3-year EPS growth"}
    peg = pe / (g * 100)
    cat = "slow grower" if g < 0.10 else ("stalwart" if g <= 0.20 else "fast grower")
    reading = "attractive (Lynch: a PEG below 1)" if peg < 1 else ("fair" if peg <= 2 else "expensive for its growth (Lynch: above 2)")
    return {"available": True, "pe": pe, "growth": g, "peg": peg, "category": cat, "reading": reading,
            "fact": _reg(ledger, an, "peg", "PEG ratio (Lynch)", peg, "x", "today", f"P/E {pe:.1f}x divided by 3-year EPS growth {g:.1%} (as a whole number): {cat}").id}


# ── Greenblatt and EVA ──────────────────────────────────────────────────────
def greenblatt(snap: Snapshot, an: Analysis, val: Valuation, ledger: Ledger) -> dict:
    ebit, roic, mcap = an.facts.get("ebit"), an.facts.get("roic"), snap.market_cap_cr
    if snap.is_financial:
        return {"available": False, "reason": "enterprise value and EBIT are not defined for a lender"}
    if not ebit or not roic or not mcap:
        return {"available": False, "reason": "needs EBIT, ROIC and market capitalisation"}
    ev = mcap + (snap.net_debt_cr or 0.0) + (snap.nci_cr or 0.0)
    ey, rf = ebit.value / ev, settings.FI_RISK_FREE_RATE
    good = roic.value >= 15
    cheap = ey >= rf
    verdict = ("a good business at a fair price: the 'magic formula' profile" if good and cheap else
               "a good business at a rich price: earnings yield is below the risk-free rate" if good else
               "cheap on earnings but with ordinary returns on capital" if cheap else "neither cheap nor high-return")
    out = {"available": True, "earnings_yield": ey, "ev": ev, "roic": roic.value / 100, "risk_free": rf, "verdict": verdict}
    out["fact"] = _reg(ledger, an, "earnings_yield", "Earnings yield (EBIT / EV)", ey * 100, "%", "today",
                       f"{fy(an.latest)} EBIT over enterprise value (market cap + net debt + minority interest); risk-free rate {rf:.2%}", [ebit]).id
    wacc = val.facts.get("wacc")
    nw, bor, cash = an.series["net_worth"].get(an.latest), an.series["borrowings"].get(an.latest), (snap.info.get("totalCash") or 0) / 1e7
    if wacc and nw is not None and bor is not None and nw + bor - cash > 0:
        ic = nw + bor - cash
        eva = (roic.value - wacc.value) / 100 * ic
        out["eva"] = {"value": eva, "invested_capital": ic, "spread": roic.value - wacc.value, "fact": _reg(
            ledger, an, "eva", "Economic value added (EVA)", eva, "₹ Cr", fy(an.latest),
            f"(ROIC {roic.value:.1f}% - WACC {wacc.value:.1f}%) x invested capital {fmt(ic, '₹ Cr')} (net worth + borrowings - cash)", [roic, wacc]).id}
    return out


# ── technical read ──────────────────────────────────────────────────────────
def technical(an: Analysis) -> dict:
    F = an.facts
    rows = []
    if (ma := F.get("vs_ma40")) is not None:
        up = ma.value > 0
        rows.append({"measure": "Price vs 40-week average", "value": fmt(ma.value, "%"), "sign": 1 if up else -1,
                     "reading": "uptrend: above its average" if up else "downtrend: below its average", "fact": ma.id})
    if (rel := F.get("ret_vs_nifty")) is not None:
        out = rel.value > 0
        rows.append({"measure": "1-year return vs Nifty 50", "value": f"{rel.value:+.1f}pp", "sign": 1 if out else -1,
                     "reading": "outperforming the market" if out else "lagging the market", "fact": rel.id})
    if (rsi := F.get("rsi")) is not None:  # context: a stretched or oversold reading is a caution, not a score
        rows.append({"measure": "Weekly RSI (14)", "value": f"{rsi.value:.0f}", "sign": None, "fact": rsi.id,
                     "reading": "stretched (above 70)" if rsi.value > 70 else ("oversold (below 30)" if rsi.value < 30 else "neither stretched nor oversold")})
    price, hi, lo = F.get("price"), F.get("high_52w"), F.get("low_52w")
    if price and hi and lo and hi.value > lo.value:
        pos = (price.value - lo.value) / (hi.value - lo.value)
        rows.append({"measure": "Position in 52-week range", "value": f"{pos:.0%}", "sign": None, "fact": price.id,
                     "reading": "near the high" if pos > 0.8 else ("near the low" if pos < 0.2 else "mid-range")})
    for key, label in (("max_drawdown", "Maximum drawdown (5y)"), ("volatility", "Volatility (annualised)")):
        if (f := F.get(key)) is not None:
            rows.append({"measure": label, "value": fmt(f.value, "%"), "reading": "", "sign": None, "fact": f.id})
    return {"available": bool(rows), "rows": rows}


# ── the scorecard ───────────────────────────────────────────────────────────
def _pillar(name: str, notes: list[tuple[int, str]]) -> dict:
    """notes: (+1 | -1 | 0, reason). Strong at +2 or more, weak at -1 or less (a single clear negative is enough to call it weak
    when nothing offsets it), mixed otherwise; no notes means no evidence."""
    pts = sum(p for p, _ in notes)
    if not notes:
        return {"name": name, "rating": "n/a", "points": 0, "reasons": []}
    return {"name": name, "rating": "strong" if pts >= 2 else ("weak" if pts <= -1 else "mixed"), "points": pts,
            "reasons": [{"sign": p, "text": t} for p, t in notes]}


def scorecard(snap: Snapshot, an: Analysis, val: Valuation, f: dict) -> dict:
    F, rf = an.facts, settings.FI_RISK_FREE_RATE
    q: list[tuple[int, str]] = []
    if (p := f["piotroski"]).get("available"):
        q.append((1 if p["verdict"] == "strong" else -1 if p["verdict"] == "weak" else 0, f"Piotroski F-score {p['score']} of {p['tested']} ({p['verdict']})"))
    if (c := f["quality"].get("cash_conversion")) is not None:
        q.append((1 if c >= 0.9 else -1 if c < 0.6 else 0, f"cash conversion {c:.1f}x net profit ({f['quality'].get('verdict', '')})"))
    if (v := f["value_creation"]).get("available"):
        q.append((1 if v["spread"] > 0 else -1, f"ROIC {v['roic']:.1f}% vs WACC {v['wacc']:.1f}% ({v['spread']:+.1f}pp)"))
    if (b := f["lenses"]["buffett"]).get("available"):
        q.append((1 if b["score"] >= b["tested"] - 1 else -1 if b["score"] <= b["tested"] // 2 - 1 else 0, f"Buffett consistency tests {b['score']} of {b['tested']}"))

    val_n: list[tuple[int, str]] = []
    if (g := f["lenses"]["graham"]).get("margin_of_safety") is not None:
        mos = g["margin_of_safety"]
        val_n.append((1 if mos > 0 else -1 if mos < -0.5 else 0, f"price is {'below' if mos > 0 else 'above'} the Graham number ({-mos:+.0%} vs it)"))
    if (ly := f["lenses"]["lynch"]).get("available"):
        val_n.append((1 if ly["peg"] < 1 else -1 if ly["peg"] > 2 else 0, f"PEG {ly['peg']:.1f} ({ly['category']})"))
    if (gb := f["lenses"]["greenblatt"]).get("available"):
        val_n.append((1 if gb["earnings_yield"] >= rf + 0.02 else -1 if gb["earnings_yield"] < rf else 0,
                      f"earnings yield {gb['earnings_yield']:.1%} vs risk-free {rf:.2%}"))
    if (r := f["residual_income"]).get("upside") is not None:
        val_n.append((1 if r["upside"] > 0 else -1 if r["upside"] < RIM_DEEP_DISCOUNT else 0, f"residual-income value {r['upside']:+.0%} vs price"))

    gr: list[tuple[int, str]] = []
    if (e := F.get("eps_cagr3")) is not None:
        gr.append((1 if e.value >= 10 else -1 if e.value < 0 else 0, f"EPS 3-year CAGR {e.value:.1f}%"))
    if (e := F.get("rev_cagr3")) is not None:
        gr.append((1 if e.value >= 10 else -1 if e.value < 0 else 0, f"revenue 3-year CAGR {e.value:.1f}%"))
    if (gc := f["growth_check"]).get("available") and gc.get("model") is not None:
        if gc.get("fundamental") is None:
            gr.append((0, "forecast growth cannot be checked against reinvestment (the business is releasing capital)"))
        else:
            ok = abs(gc["model"] - gc["fundamental"]) <= 0.04
            gr.append((1 if ok else -1 if gc["model"] > gc["fundamental"] else 0, f"forecast growth {gc['model']:.1%} vs {gc['fundamental']:.1%} that reinvestment funds"))

    sf: list[tuple[int, str]] = []
    if (z := F.get("altman_z")) is not None:
        zone = z.method.split(" zone")[0] if "zone" in z.method else ""
        sf.append((-1 if zone == "distress" else 1 if zone == "safe" else 0, f"Altman Z-score {z.value:.1f} ({zone or 'n/a'} zone)"))
    s, L = an.series, an.latest
    if not snap.is_financial:
        if (ic := s["interest_cover"].get(L)) is not None:
            sf.append((1 if ic >= 3 else -1 if ic < 1.5 else 0, f"interest cover {ic:.1f}x"))
        if (de := s["de"].get(L)) is not None:
            sf.append((1 if de <= 1 else -1 if de > 2 else 0, f"borrowings {de:.2f}x net worth"))
    elif (roe3 := F.get("roe3")) is not None and (coe := val.facts.get("coe")) is not None:
        sf.append((1 if roe3.value > coe.value else -1, f"3-year ROE {roe3.value:.1f}% vs cost of equity {coe.value:.1f}%"))

    tech = [(r["sign"], f"{r['measure']} {r['value']}: {r['reading']}") for r in f["technical"]["rows"] if r.get("sign") is not None]

    sent: list[tuple[int, str]] = []
    news, call = f["news_signals"], f["concall"]
    if news.get("net") is not None:
        sent.append((1 if news["net"] >= SENTIMENT_EDGE else -1 if news["net"] <= -SENTIMENT_EDGE else 0, f"news tone {news['net']:+.2f} across {news['scored']} headlines"))
    if call.get("available") and call.get("net") is not None:
        sent.append((1 if call["net"] >= SENTIMENT_EDGE else -1 if call["net"] <= -SENTIMENT_EDGE else 0, f"earnings-call tone {call['net']:+.2f} ({call['period']})"))

    pillars = [_pillar("Quality", q), _pillar("Valuation lenses", val_n), _pillar("Growth", gr), _pillar("Financial safety", sf),
               _pillar("Technical", tech), _pillar("Sentiment", sent)]
    return {"pillars": pillars, "overlay": overlay(pillars, val)}


def overlay(pillars: list[dict], val: Valuation) -> dict:
    """Read the pillars against the valuation call. Never changes the call: says how much weight it deserves."""
    rated = [p for p in pillars if p["rating"] != "n/a"]
    weak, strong = [p for p in rated if p["rating"] == "weak"], [p for p in rated if p["rating"] == "strong"]
    syn = val.synthesis
    call = f"The valuation model's call is {syn.rating}" if syn and not val.withheld_by_audit else "No valuation call was made"
    if len(weak) >= 2 or (weak and len(rated) <= 3):
        tone, text = "concern", f"{call}, but {len(weak)} of {len(rated)} fundamental pillars are weak ({', '.join(p['name'].lower() for p in weak)}): treat it with lower conviction."
    elif len(strong) >= 3 and not weak:
        tone, text = "support", f"{call}, and {len(strong)} of {len(rated)} fundamental pillars are strong ({', '.join(p['name'].lower() for p in strong)}): the fundamentals support it."
    else:
        tone, text = "mixed", f"{call}; the fundamentals are mixed ({len(strong)} strong, {len(weak)} weak of {len(rated)} pillars): the call stands on valuation alone."
    return {"tone": tone, "reading": text, "weak": [p["name"] for p in weak], "strong": [p["name"] for p in strong]}


# ── the intelligence score ──────────────────────────────────────────────────
INTEL_WEIGHTS = (("Quality", 25), ("Financial safety", 15), ("Growth", 15), ("Valuation lenses", 10), ("Valuation upside", 15), ("Technical", 10), ("Tone", 10))
_PILLAR_VALUE = {"strong": 1.0, "mixed": 0.5, "weak": 0.0}  # n/a is dropped and the other weights renormalised
UPSIDE_STRONG = 0.15  # upside at or above this, with weak fundamentals, is a possible value trap


def intelligence(f: dict, val: Valuation) -> dict:
    """One 0-100 score from the scorecard pillars, the valuation upside and the news/call tone, plus the places where those
    sources disagree with each other (the divergences are the useful part: they are what to look at before trusting the score)."""
    pillars = f["scorecard"]["pillars"]
    rating = {p["name"]: p["rating"] for p in pillars}
    value: dict[str, float | None] = {n: _PILLAR_VALUE.get(r) for n, r in rating.items()}
    syn = val.synthesis
    up = syn.upside if syn and not val.withheld_by_audit else None
    value["Valuation upside"] = None if up is None else min(max(up, -0.3), 0.3) / 0.6 + 0.5
    news, call = (f.get("news_signals") or {}).get("net"), (f.get("concall") or {}).get("net")
    nets = [n for n in (news, call) if n is not None]
    value["Tone"] = (sum(nets) / len(nets) + 1) / 2 if nets else value.get("Sentiment")
    comps = [{"name": n, "weight": w, "value": value.get(n)} for n, w in INTEL_WEIGHTS]
    live = [c for c in comps if c["value"] is not None]
    total = sum(c["weight"] for c in live)
    score = round(100 * sum(c["weight"] * c["value"] for c in live) / total) if total else None
    band = None if score is None else "strong" if score >= 70 else "mixed" if score >= 45 else "weak"

    pos, neg = any(n >= SENTIMENT_EDGE for n in nets), any(n <= -SENTIMENT_EDGE for n in nets)
    cash = (f.get("quality") or {}).get("cash_conversion")
    quality_weak = rating.get("Quality") == "weak" or (f.get("piotroski") or {}).get("verdict") == "weak"
    gc = f.get("growth_check") or {}
    # a value trap is cheap because the business is deteriorating: count the business pillars only (cheapness and price action are the symptom, not the cause)
    weak_n = sum(1 for k in ("Quality", "Growth", "Financial safety") if rating.get(k) == "weak")
    divs: list[dict] = []

    def hit(id_: str, severity: str, text: str, evidence: str) -> None:
        divs.append({"id": id_, "severity": severity, "text": text, "evidence": evidence})

    if pos and cash is not None and cash < 0.6:
        hit("tone_vs_cash", "high", "Positive tone but weak cash conversion", f"tone {max(nets):+.2f} while operating cash flow is {cash:.1f}x net profit")
    if pos and quality_weak:
        hit("tone_vs_quality", "high", "Positive tone but weak earnings quality", f"tone {max(nets):+.2f} while the Quality pillar or the Piotroski score is weak")
    if news is not None and call is not None and news * call < 0 and abs(news - call) > SENTIMENT_EDGE:
        hit("call_vs_news", "medium", "Management upbeat, press negative" if call > 0 else "Management cautious, press positive", f"call {call:+.2f} vs news {news:+.2f}")
    if call is not None and call >= SENTIMENT_EDGE and gc.get("model") is not None and gc.get("fundamental") is not None and gc["model"] > gc["fundamental"] + 0.04:
        hit("guidance_unfunded", "medium", "Upbeat call, but the forecast growth is ahead of what reinvestment funds", f"forecast {gc['model']:.1%} vs {gc['fundamental']:.1%} fundable")
    if up is not None and up >= UPSIDE_STRONG and weak_n >= 2:
        hit("value_trap", "high", "Large upside but the business pillars are weak: a possible value trap", f"upside {up:+.0%} with {weak_n} of quality, growth and safety weak")
    tech, qual = rating.get("Technical"), rating.get("Quality")
    if tech == "weak" and qual == "strong":
        hit("price_vs_fundamentals", "low", "Market lagging fundamentals", "technical read is weak while quality is strong")
    elif tech == "strong" and qual == "weak":
        hit("price_vs_fundamentals", "low", "Momentum ahead of fundamentals", "technical read is strong while quality is weak")
    if neg and qual == "strong" and rating.get("Financial safety") == "strong":
        hit("contrarian", "low", "Negative tone on a strong, safe business: a possible contrarian setup", f"tone {min(nets):+.2f} while quality and financial safety are strong")
    return {"score": score, "band": band, "coverage": total / 100, "low_evidence": total < 50, "components": comps, "divergences": divs}
