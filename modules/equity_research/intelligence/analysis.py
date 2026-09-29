"""
Deterministic financial-statement analysis.

Turns the screener.in / Yahoo data on a ``Snapshot`` into ledger facts, multi-year
tables and rule-based risk flags. No LLM is involved: every figure here is
calculated from published statement rows, so the narrative layer can only cite it.

Two layouts, because screener presents banks/NBFCs differently (Revenue /
Interest / Financing Profit / Deposits / NPAs instead of Sales / Operating Profit):
``snap.is_financial`` selects the branch.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from modules.equity_research.intelligence.data import Snapshot, _currency_mismatch, annual_cols, row
from modules.equity_research.intelligence.facts import CALCULATED, RAW, Fact, Ledger, Table, fmt

SCREENER = "screener.in"
YAHOO = "Yahoo Finance"

# Risk-flag thresholds (rules of thumb, stated in the flag text so they can be challenged).
_HIGH_LEVERAGE_DE = 1.0
_THIN_INTEREST_COVER = 3.0
_WEAK_CASH_CONVERSION = 0.7
_MARGIN_COMPRESSION_PP = 3.0
_HIGH_VOLATILITY = 35.0  # % annualised, from weekly returns
_DEEP_DRAWDOWN = 40.0  # % over the 5-year weekly history
_NPA_WATCH = 1.0  # % net NPA
_WEAK_BANK_ROE = 12.0  # %
_PLEDGE_WATCH = 25.0  # % of the promoters' holding pledged
_PROMOTER_EXIT_PP = 2.0  # fall in promoter holding over four quarters, percentage points
ALTMAN_ZONES = (1.81, 2.99)  # original public-company model: distress below, safe above


@dataclass(frozen=True)
class Risk:
    category: str  # business | financial | valuation | market | sector | regulatory | execution | data-quality
    severity: str  # low | medium | high
    title: str
    detail: str
    facts: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"category": self.category, "severity": self.severity, "title": self.title,
                "detail": self.detail, "facts": list(self.facts)}


@dataclass
class Analysis:
    years: list[str] = field(default_factory=list)  # fiscal-year columns, oldest -> newest
    latest: str | None = None  # latest fiscal-year column, e.g. "Mar 2026"
    series: dict[str, dict[str, float | None]] = field(default_factory=dict)  # per-year, natural units (margins as fractions)
    ttm: dict[str, float | None] = field(default_factory=dict)
    facts: dict[str, Fact] = field(default_factory=dict)  # headline facts by key
    tables: list[Table] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    dupont: dict = field(default_factory=dict)  # factor values by year, for the deterministic commentary
    attributable: float = 1.0  # share of screener's net profit attributable to shareholders (minorities excluded)
    unavailable: dict[str, str] = field(default_factory=dict)  # optional measure -> why it could not be computed
    competitive: dict = field(default_factory=dict)  # the company beside its listed peers: rows, ranks, revenue share


# ── helpers ────────────────────────────────────────────────────────────────
def fy(col: str | None) -> str:
    """'Mar 2026' -> 'FY2026'; other year-ends keep their label ('Dec 2025')."""
    if not col:
        return ""
    return f"FY{col.split()[-1]}" if col.startswith("Mar ") else col


def _div(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0) else None


def _yoy(cur: float | None, prev: float | None) -> float | None:
    return cur / prev - 1 if cur is not None and prev is not None and prev > 0 else None


def cagr(values: list[float | None], n: int) -> float | None:
    """Compound annual growth over the last ``n`` intervals; None if either end is missing or not positive."""
    if len(values) <= n:
        return None
    first, last = values[-1 - n], values[-1]
    if first is None or last is None or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / n) - 1


def median_recent(values: list[float | None], n: int = 3) -> float | None:
    recent = [v for v in values[-n:] if v is not None]
    return statistics.median(recent) if recent else None


def _per_year(fn, years: list[str]) -> dict[str, float | None]:
    return {c: fn(c, years[i - 1] if i else None) for i, c in enumerate(years)}


def _values(series: dict[str, float | None], years: list[str]) -> list[float | None]:
    return [series.get(c) for c in years]


# ── the analysis ───────────────────────────────────────────────────────────
def analyze(snap: Snapshot, ledger: Ledger) -> Analysis:
    out = Analysis()
    pl, bs, cf, ratios = (snap.tables.get(k, {"cols": [], "rows": {}}) for k in ("pl", "bs", "cf", "ratios"))
    basis = snap.view
    src = f"{SCREENER} ({basis})"

    revenue = row(pl, "Sales", "Revenue")
    years = [c for c in annual_cols(pl) if revenue.get(c) is not None]
    if not years:
        ledger.miss("Financial statements", "no annual statement data (screener.in unavailable)")
        _market_facts(snap, ledger, out)
        return out
    out.years, out.latest = years, years[-1]
    L, P = years[-1], (years[-2] if len(years) > 1 else None)
    per = fy(L)

    # Banks: screener's consolidated "Financing Profit" excludes fee/other income (HDFC Bank shows
    # -Rs 40,511 Cr against a Rs 102,141 Cr pre-tax profit), so it is not a comparable earnings line.
    ebitda_row = row(pl, "Profit before tax") if snap.is_financial else row(pl, "Operating Profit")
    dep, interest = row(pl, "Depreciation"), row(pl, "Interest")
    pat, eps, payout, tax_pct = row(pl, "Net Profit"), row(pl, "EPS in Rs"), row(pl, "Dividend Payout %"), row(pl, "Tax %")
    eq_cap, reserves = row(bs, "Equity Capital", "Share Capital"), row(bs, "Reserves")
    borrowings, assets, deposits = row(bs, "Borrowings", "Borrowing"), row(bs, "Total Assets"), row(bs, "Deposits")
    cfo, fcf_row = row(cf, "Cash from Operating Activity"), row(cf, "Free Cash Flow")
    wc_days, roce = row(ratios, "Working Capital Days"), row(ratios, "ROCE %")

    def add(key: str, label: str, value: float | None, unit: str, period: str, kind: str, *,
            method: str = "", inputs=(), source: str = src) -> Fact | None:
        if value is None or not math.isfinite(value):
            ledger.miss(f"{label} ({period})" if period else label, "not derivable from the available statements")
            return None
        out.facts[key] = ledger.add(label, value, unit, period, source, kind, method=method, inputs=inputs)
        return out.facts[key]

    # per-year derived series (natural units; margins/ratios as fractions)
    s = out.series
    s["revenue"], s["ebitda"], s["pat"], s["eps"] = ({c: d.get(c) for c in years} for d in (revenue, ebitda_row, pat, eps))
    s["dep"], s["interest"] = ({c: d.get(c) for c in years} for d in (dep, interest))
    s["payout"] = {c: (payout[c] / 100 if payout.get(c) is not None else None) for c in years}
    s["tax_rate"] = {c: (tax_pct[c] / 100 if tax_pct.get(c) is not None else None) for c in years}
    s["net_worth"] = {c: (eq_cap[c] + reserves[c] if eq_cap.get(c) is not None and reserves.get(c) is not None else None) for c in years}
    s["borrowings"] = {c: borrowings.get(c) for c in years}
    s["opm"] = {c: _div(ebitda_row.get(c), revenue.get(c)) for c in years}
    s["da_pct"] = {c: _div(dep.get(c), revenue.get(c)) for c in years}
    s["net_margin"] = {c: _div(pat.get(c), revenue.get(c)) for c in years}
    s["rev_growth"] = _per_year(lambda c, p: _yoy(revenue.get(c), revenue.get(p)) if p else None, years)
    s["pat_growth"] = _per_year(lambda c, p: _yoy(pat.get(c), pat.get(p)) if p else None, years)
    # Consolidated "Net Profit" is before minority interest (Reliance: EPS x shares is 84% of it), but net
    # worth here is the shareholders' own. Scale profit to the attributable share, measured on the latest
    # year (EPS x shares / net profit), so ROE compares like with like.
    shares_cr = snap.shares / 1e7 if snap.shares else None
    attrib = (eps.get(L) * shares_cr / pat[L]) if shares_cr and eps.get(L) and pat.get(L) and pat[L] > 0 else 1.0
    attrib = attrib if 0.5 <= attrib < 0.99 else 1.0
    out.attributable = attrib
    s["roe"] = _per_year(
        lambda c, p: _div((pat.get(c) * attrib if pat.get(c) is not None else None),
                          (statistics.mean([s["net_worth"][c], s["net_worth"][p]])
                           if p and s["net_worth"].get(p) and s["net_worth"].get(c) else s["net_worth"].get(c))), years)
    s["de"] = {c: _div(borrowings.get(c), s["net_worth"].get(c)) for c in years}
    s["cfo"] = {c: cfo.get(c) for c in years}
    s["fcf"] = {c: fcf_row.get(c) for c in years}
    s["capex"] = {c: (cfo[c] - fcf_row[c] if cfo.get(c) is not None and fcf_row.get(c) is not None else None) for c in years}
    s["capex_pct"] = {c: _div(s["capex"][c], revenue.get(c)) for c in years}
    s["cfo_pat"] = {c: _div(cfo.get(c), pat.get(c)) for c in years}
    s["fcf_margin"] = {c: _div(fcf_row.get(c), revenue.get(c)) for c in years}
    s["nwc_pct"] = {c: (wc_days[c] / 365 if wc_days.get(c) is not None else None) for c in years}
    s["wc_days"] = {c: wc_days.get(c) for c in years}
    s["total_assets"] = {c: assets.get(c) for c in years}
    s["ebit"] = {c: (ebitda_row[c] - dep[c] if ebitda_row.get(c) is not None and dep.get(c) is not None else None) for c in years}
    s["roce"] = {c: (roce[c] / 100 if roce.get(c) is not None else None) for c in years}
    s["interest_cover"] = {
        c: (_div(ebitda_row[c] - dep[c], interest[c]) if ebitda_row.get(c) is not None and dep.get(c) is not None and (interest.get(c) or 0) > 0 else None)
        for c in years
    }
    if deposits:
        s["deposits"] = {c: deposits.get(c) for c in years}
        s["leverage"] = {c: _div(assets.get(c), s["net_worth"].get(c)) for c in years}

    # trailing twelve months (screener's P&L TTM column)
    out.ttm = {"revenue": revenue.get("TTM"), "ebitda": ebitda_row.get("TTM"), "pat": pat.get("TTM"), "eps": eps.get("TTM")}

    # ── headline facts ────────────────────────────────────────────────────
    rev_l = add("revenue", "Revenue", revenue[L], "₹ Cr", per, RAW)
    add("revenue_ttm", "Revenue (TTM)", out.ttm["revenue"], "₹ Cr", "TTM", RAW)
    ebitda_label = "Profit before tax" if snap.is_financial else "EBITDA (operating profit)"
    ebitda_l = add("ebitda", ebitda_label, ebitda_row.get(L), "₹ Cr", per, RAW)
    pat_l = add("pat", "Net profit", pat.get(L), "₹ Cr", per, RAW,
                method="as published; before minority interest" if out.attributable < 1 else "")
    eps_l = add("eps", "EPS", eps.get(L), "₹", per, RAW)
    add("eps_ttm", "EPS (TTM)", out.ttm["eps"], "₹", "TTM", RAW)
    add("payout", "Dividend payout", s["payout"][L] * 100 if s["payout"][L] is not None else None, "%", per, RAW)

    rev_v, pat_v, eps_v = _values(s["revenue"], years), _values(s["pat"], years), _values(s["eps"], years)
    add("rev_growth", "Revenue growth (YoY)", _pct(s["rev_growth"][L]), "%", per, CALCULATED,
        method=f"{per} vs {fy(P)} revenue", inputs=[f for f in (rev_l,) if f])
    add("rev_cagr3", "Revenue CAGR (3y)", _pct(cagr(rev_v, 3)), "%", f"{fy(years[-4]) if len(years) > 3 else ''}–{per}", CALCULATED, method="compound growth of annual revenue")
    add("rev_cagr5", "Revenue CAGR (5y)", _pct(cagr(rev_v, 5)), "%", f"{fy(years[-6]) if len(years) > 5 else ''}–{per}", CALCULATED, method="compound growth of annual revenue")
    add("pat_growth", "Net profit growth (YoY)", _pct(s["pat_growth"][L]), "%", per, CALCULATED, method=f"{per} vs {fy(P)} net profit", inputs=[f for f in (pat_l,) if f])
    add("pat_cagr3", "Net profit CAGR (3y)", _pct(cagr(pat_v, 3)), "%", f"{fy(years[-4]) if len(years) > 3 else ''}–{per}", CALCULATED, method="compound growth of annual net profit")
    add("eps_cagr3", "EPS CAGR (3y)", _pct(cagr(eps_v, 3)), "%", f"{fy(years[-4]) if len(years) > 3 else ''}–{per}", CALCULATED, method="compound growth of annual EPS")
    add("eps_cagr5", "EPS CAGR (5y)", _pct(cagr(eps_v, 5)), "%", f"{fy(years[-6]) if len(years) > 5 else ''}–{per}", CALCULATED, method="compound growth of annual EPS")
    add("opm", "EBITDA margin" if not snap.is_financial else "Pre-tax margin", _pct(s["opm"][L]), "%", per, CALCULATED,
        method="operating profit / revenue" if not snap.is_financial else "profit before tax / revenue", inputs=[f for f in (ebitda_l, rev_l) if f])
    add("net_margin", "Net margin", _pct(s["net_margin"][L]), "%", per, CALCULATED, method="net profit / revenue", inputs=[f for f in (pat_l, rev_l) if f])
    add("roe", "Return on equity", _pct(s["roe"][L]), "%", per, CALCULATED,
        method="net profit / average net worth (equity capital + reserves)"
        + (f", net profit scaled to the {out.attributable:.0%} attributable to shareholders" if out.attributable < 1 else ""))
    add("roe3", "Return on equity (3y median)", _pct(median_recent(_values(s["roe"], years))), "%", f"3y to {per}", CALCULATED, method="median of annual ROE")
    add("net_worth", "Net worth", s["net_worth"].get(L), "₹ Cr", per, CALCULATED, method="equity capital + reserves")
    add("borrowings", "Borrowings", borrowings.get(L), "₹ Cr", per, RAW)

    if snap.is_financial:
        _financial_facts(snap, ledger, out, add, per, L, P)
    else:
        _operating_facts(snap, ledger, out, add, per, L)

    _quarterly_facts(snap, out, add)
    _market_facts(snap, ledger, out)
    _valuation_ratios(snap, ledger, out)
    _tables(snap, out, src)
    _ownership(snap, ledger, out)
    _altman(snap, ledger, out)
    _competitive(snap, ledger, out)
    _risks(snap, out, ledger)
    return out


def _pct(fraction: float | None) -> float | None:
    return fraction * 100 if fraction is not None else None


def _operating_facts(snap, ledger, out: Analysis, add, per: str, L: str) -> None:
    s = out.series
    ebitda_f, dep_v = out.facts.get("ebitda"), out.series["dep"].get(L)
    if ebitda_f and dep_v is not None:
        ebit_f = add("ebit", "EBIT (EBITDA less depreciation)", ebitda_f.value - dep_v, "₹ Cr", per, CALCULATED, method="operating profit - depreciation", inputs=[ebitda_f])
        rev_f = out.facts.get("revenue")
        if ebit_f and rev_f:
            add("ebit_margin", "EBIT margin", ebit_f.value / rev_f.value * 100, "%", per, CALCULATED, method="EBIT / revenue", inputs=[ebit_f, rev_f])
    ta = row(snap.tables.get("bs", {"cols": [], "rows": {}}), "Total Assets")
    ta_l, ta_p = ta.get(L), (ta.get(out.years[-2]) if len(out.years) > 1 else None)
    if ta_l and out.facts.get("revenue"):
        avg = (ta_l + ta_p) / 2 if ta_p else ta_l
        add("asset_turnover", "Asset turnover", out.facts["revenue"].value / avg, "x", per, CALCULATED, method="revenue / average total assets")
    add("de", "Debt / equity", s["de"][L], "x", per, CALCULATED, method="borrowings / net worth (equity capital + reserves)")
    add("roce", "Return on capital employed", _pct(s["roce"][L]), "%", per, RAW, method="as published by screener.in")
    add("interest_cover", "Interest cover", s["interest_cover"][L], "x", per, CALCULATED, method="(operating profit - depreciation) / interest")
    add("cfo", "Operating cash flow", s["cfo"][L], "₹ Cr", per, RAW)
    add("fcf", "Free cash flow", s["fcf"][L], "₹ Cr", per, RAW, method="as published by screener.in (operating cash flow less capex)")
    add("capex_pct", "Capex / revenue", _pct(s["capex_pct"][L]), "%", per, CALCULATED, method="operating cash flow - free cash flow, over revenue")
    add("cfo_pat", "Cash conversion (CFO / net profit)", s["cfo_pat"][L], "x", per, CALCULATED, method="operating cash flow / net profit")
    add("fcf_margin", "FCF margin", _pct(s["fcf_margin"][L]), "%", per, CALCULATED, method="free cash flow / revenue")
    add("wc_days", "Working-capital days", (s["nwc_pct"][L] * 365) if s["nwc_pct"][L] is not None else None, "days", per, RAW, method="as published by screener.in")
    gm = snap.info.get("grossMargins")
    if isinstance(gm, (int, float)) and not isinstance(gm, bool) and 0 < gm < 1:
        out.facts["gross_margin"] = ledger.add("Gross margin", gm * 100, "%", "latest", YAHOO, RAW, method="as reported by Yahoo Finance (trailing)")
    cash = (snap.info.get("totalCash") or 0) / 1e7
    nw_l, debt_l, ebit_f = s["net_worth"].get(L), s["borrowings"].get(L), out.facts.get("ebit")
    if ebit_f and nw_l is not None and debt_l is not None and nw_l + debt_l - cash > 0:
        tax_r = s["tax_rate"].get(L)
        tax_r = tax_r if tax_r is not None and 0 <= tax_r <= 0.45 else 0.2517
        add("roic", "Return on invested capital (ROIC)", ebit_f.value * (1 - tax_r) / (nw_l + debt_l - cash) * 100, "%", per, CALCULATED,
            method="EBIT x (1 - tax rate) / (net worth + borrowings - cash); closing balances", inputs=[ebit_f])
    nd, ebitda = snap.net_debt_cr, out.facts.get("ebitda")
    if nd is not None:
        nd_fact = ledger.add("Net debt", nd, "₹ Cr", "latest", f"{YAHOO} (total debt - total cash)", CALCULATED, method="total debt - total cash, consolidated")
        out.facts["net_debt"] = nd_fact
        if ebitda:
            add("net_debt_ebitda", "Net debt / EBITDA", nd / ebitda.value, "x", per, CALCULATED, method="net debt / latest-year EBITDA",
                inputs=[nd_fact, ebitda], source="ARIA analysis")


def _financial_facts(snap, ledger, out: Analysis, add, per: str, L: str, P: str | None) -> None:
    s = out.series
    if "leverage" in s:
        add("leverage", "Leverage (assets / net worth)", s["leverage"][L], "x", per, CALCULATED, method="total assets / net worth")
    if "deposits" in s and P:
        add("deposit_growth", "Deposit growth (YoY)", _pct(_yoy(s["deposits"].get(L), s["deposits"].get(P))), "%", per, CALCULATED, method=f"{per} vs {fy(P)} deposits")
    for key, label, name in (("gross_npa", "Gross NPA", "Gross NPA %"), ("net_npa", "Net NPA", "Net NPA %")):
        q = snap.tables.get("quarterly", {"cols": [], "rows": {}})
        r = row(q, name)
        cols = [c for c in q.get("cols", []) if r.get(c) is not None]
        if cols:
            add(key, f"{label} (latest quarter)", r[cols[-1]], "%", cols[-1], RAW)


def _quarterly_facts(snap: Snapshot, out: Analysis, add) -> None:
    q = snap.tables.get("quarterly")
    if not q or len(q["cols"]) < 5:
        return
    cols = q["cols"]
    last, year_ago = cols[-1], cols[-5]
    rev, pat = row(q, "Sales", "Revenue"), row(q, "Net Profit")
    add("q_rev_growth", "Revenue growth (latest quarter, YoY)", _pct(_yoy(rev.get(last), rev.get(year_ago))), "%", last, CALCULATED, method=f"{last} vs {year_ago}")
    add("q_pat_growth", "Net profit growth (latest quarter, YoY)", _pct(_yoy(pat.get(last), pat.get(year_ago))), "%", last, CALCULATED, method=f"{last} vs {year_ago}")
    if not snap.is_financial:
        op = row(q, "Operating Profit")
        now, then = _div(op.get(last), rev.get(last)), _div(op.get(year_ago), rev.get(year_ago))
        if now is not None and then is not None:
            add("q_margin_change", "EBITDA margin change (latest quarter, YoY)", (now - then) * 100, "pp", last, CALCULATED, method=f"{last} vs {year_ago} operating margin")


def _market_facts(snap: Snapshot, ledger: Ledger, out: Analysis) -> None:
    """Price, size, market multiples, street targets and price-risk statistics (Yahoo)."""
    info, F = snap.info, out.facts

    def put(key: str, label: str, value: float | None, unit: str, period: str, kind: str = RAW, *, method: str = "", source: str = YAHOO) -> None:
        if value is not None and math.isfinite(value):
            F[key] = ledger.add(label, value, unit, period, source, kind, method=method)
        else:
            ledger.miss(label, "not provided by the data source")

    as_of = f"as of {snap.as_of}"
    put("price", "Share price", snap.price, "₹", as_of)
    put("market_cap", "Market capitalisation", snap.market_cap_cr, "₹ Cr", as_of)
    put("shares", "Shares outstanding", snap.shares / 1e7 if snap.shares else None, "Cr shares", as_of)
    for key, label, name, unit in (
        ("pe", "P/E (trailing)", "trailingPE", "x"), ("pb", "P/B", "priceToBook", "x"),
        ("ev_ebitda", "EV / EBITDA", "enterpriseToEbitda", "x"),
        ("current_ratio", "Current ratio", "currentRatio", "x"), ("quick_ratio", "Quick ratio", "quickRatio", "x"),
        ("high_52w", "52-week high", "fiftyTwoWeekHigh", "₹"), ("low_52w", "52-week low", "fiftyTwoWeekLow", "₹"),
        ("target_mean", "Analyst target (mean)", "targetMeanPrice", "₹"), ("target_high", "Analyst target (high)", "targetHighPrice", "₹"),
        ("target_low", "Analyst target (low)", "targetLowPrice", "₹"), ("analysts", "Analysts covering", "numberOfAnalystOpinions", ""),
    ):
        if key in ("current_ratio", "quick_ratio") and snap.is_financial:
            continue  # not meaningful for a lender
        if key == "ev_ebitda" and snap.is_financial:
            continue  # enterprise value / EBITDA is not defined for a bank
        raw = info.get(name)
        put(key, label, float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None, unit, as_of)
    # price-risk statistics from the 5-year weekly history
    closes = snap.closes
    if len(closes) > 52:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        put("volatility", "Price volatility (annualised)", statistics.pstdev(rets) * math.sqrt(52) * 100, "%", "5y weekly", CALCULATED,
            method="standard deviation of weekly returns x sqrt(52)", source="ARIA analysis")
        peak, worst = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            worst = min(worst, c / peak - 1)
        put("max_drawdown", "Maximum drawdown", worst * 100, "%", "5y weekly", CALCULATED, method="largest peak-to-trough fall in weekly closes", source="ARIA analysis")
    if len(closes) > 53:
        tech = "ARIA analysis (Yahoo prices)"
        r1 = closes[-1] / closes[-53] - 1
        put("ret_1y", "1-year price return", r1 * 100, "%", "52 weeks", CALCULATED, method="latest weekly close / close 52 weeks earlier - 1", source=tech)
        if len(snap.index_returns) >= 52:
            idx = 1.0
            for r in snap.index_returns[-52:]:
                idx *= 1 + r
            put("ret_vs_nifty", "1-year return vs Nifty 50", (r1 - (idx - 1)) * 100, "pp", "52 weeks", CALCULATED, method="stock 52-week return minus Nifty 50 52-week return", source=tech)
        put("vs_ma40", "Price vs 40-week average", (closes[-1] / statistics.fmean(closes[-40:]) - 1) * 100, "%", "40 weeks", CALCULATED, method="latest close / mean of last 40 weekly closes - 1", source=tech)
        changes = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
        gain, loss = sum(c for c in changes if c > 0) / 14, -sum(c for c in changes if c < 0) / 14
        put("rsi", "Weekly RSI (14)", 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss), "", "14 weeks", CALCULATED, method="relative strength index on 14 weekly closes (simple averages)", source=tech)


def _valuation_ratios(snap: Snapshot, ledger: Ledger, out: Analysis) -> None:
    """Ratios that combine statement figures with market data (EV/Sales, FCF yield, dividend yield)."""
    F, put = out.facts, None

    def add(key: str, label: str, value: float, unit: str, method: str, inputs) -> None:
        F[key] = ledger.add(label, value, unit, f"as of {snap.as_of}", "ARIA analysis", CALCULATED, method=method, inputs=inputs)

    if "market_cap" in F and out.ttm.get("revenue") and not snap.is_financial:
        ev = F["market_cap"].value + (snap.net_debt_cr or 0.0) + (snap.nci_cr or 0.0)
        add("ev_sales", "EV / Sales", ev / out.ttm["revenue"], "x", "(market cap + net debt + minority interest) / TTM revenue", [F["market_cap"]])
    if "market_cap" in F and "fcf" in F and F["market_cap"].value > 0:
        add("fcf_yield", "FCF yield", F["fcf"].value / F["market_cap"].value * 100, "%", "latest-year free cash flow / market cap", [F["fcf"], F["market_cap"]])
    dps, price = snap.info.get("dividendRate"), snap.price
    if isinstance(dps, (int, float)) and not isinstance(dps, bool) and dps > 0 and price:
        add("div_yield", "Dividend yield", dps / price * 100, "%", "annual dividend per share / share price", [F["price"]] if "price" in F else [])


def _tables(snap: Snapshot, out: Analysis, src: str) -> None:
    years = out.years[-6:]
    s = out.series
    labels = [fy(c) for c in years]

    def rows(spec: list[tuple[str, str, str, str]]) -> list[dict]:
        result = []
        for label, unit, kind, key in spec:
            if key not in s:
                continue
            scale = 100 if unit == "%" else 1
            result.append({"label": label, "unit": unit, "kind": kind,
                           "values": {fy(c): (s[key][c] * scale if s[key].get(c) is not None else None) for c in years}})
        return result

    if snap.is_financial:
        out.tables.append(Table("Income and returns", labels, rows([
            ("Revenue (total income)", "₹ Cr", RAW, "revenue"), ("Profit before tax", "₹ Cr", RAW, "ebitda"),
            ("Net profit", "₹ Cr", RAW, "pat"), ("EPS", "₹", RAW, "eps"), ("Revenue growth", "%", CALCULATED, "rev_growth"),
            ("Net profit growth", "%", CALCULATED, "pat_growth"), ("Return on equity", "%", CALCULATED, "roe"),
            ("Dividend payout", "%", RAW, "payout")]), src))
        out.tables.append(Table("Balance sheet", labels, rows([
            ("Net worth", "₹ Cr", CALCULATED, "net_worth"), ("Deposits", "₹ Cr", RAW, "deposits"),
            ("Borrowings", "₹ Cr", RAW, "borrowings"), ("Leverage (assets / net worth)", "x", CALCULATED, "leverage")]), src))
    else:
        out.tables.append(Table("Income and margins", labels, rows([
            ("Revenue", "₹ Cr", RAW, "revenue"), ("EBITDA", "₹ Cr", RAW, "ebitda"), ("EBITDA margin", "%", CALCULATED, "opm"),
            ("EBIT", "₹ Cr", CALCULATED, "ebit"),
            ("Net profit", "₹ Cr", RAW, "pat"), ("Net margin", "%", CALCULATED, "net_margin"), ("EPS", "₹", RAW, "eps"),
            ("Revenue growth", "%", CALCULATED, "rev_growth"), ("Net profit growth", "%", CALCULATED, "pat_growth")]), src))
        out.tables.append(Table("Balance sheet", labels, rows([
            ("Net worth (equity capital + reserves)", "₹ Cr", CALCULATED, "net_worth"), ("Borrowings", "₹ Cr", RAW, "borrowings"),
            ("Total assets", "₹ Cr", RAW, "total_assets"), ("Working-capital days", "days", RAW, "wc_days"),
            ("Debt / equity", "x", CALCULATED, "de")]), src))
        out.tables.append(Table("Returns, leverage and cash flow", labels, rows([
            ("Return on equity", "%", CALCULATED, "roe"), ("Return on capital employed", "%", RAW, "roce"),
            ("Debt / equity", "x", CALCULATED, "de"), ("Interest cover", "x", CALCULATED, "interest_cover"),
            ("Operating cash flow", "₹ Cr", RAW, "cfo"), ("Capex", "₹ Cr", CALCULATED, "capex"),
            ("Free cash flow", "₹ Cr", RAW, "fcf"), ("Cash conversion (CFO / net profit)", "x", CALCULATED, "cfo_pat")]), src))

    q = snap.tables.get("quarterly")
    if q and q["cols"]:
        qcols = q["cols"][-6:]
        spec = ([("Revenue", "Sales", "Revenue"), ("Net profit", "Net Profit"), ("Gross NPA %", "Gross NPA %"), ("Net NPA %", "Net NPA %")]
                if snap.is_financial else [("Revenue", "Sales", "Revenue"), ("Operating profit", "Operating Profit"), ("Net profit", "Net Profit"), ("EPS", "EPS in Rs")])
        qrows = []
        for label, *names in spec:
            r = row(q, *names)
            if r:
                unit = "%" if "NPA" in label else ("₹" if label == "EPS" else "₹ Cr")
                qrows.append({"label": label, "unit": unit, "kind": RAW, "values": {c: r.get(c) for c in qcols}})
        if qrows:
            out.tables.append(Table("Recent quarters", qcols, qrows, src))
    _extra_tables(snap, out, src)


def _extra_tables(snap: Snapshot, out: Analysis, src: str) -> None:
    """DuPont ROE decomposition, common-size statements and the working-capital cycle: all arithmetic on
    statement rows already in the snapshot."""
    pl, bs, ra = (snap.tables.get(k, {"cols": [], "rows": {}}) for k in ("pl", "bs", "ratios"))
    years, s = out.years[-6:], out.series
    labels = [fy(c) for c in years]
    rev, ta, nw = s["revenue"], s["total_assets"], s["net_worth"]

    def line(label: str, unit: str, values: dict, kind: str = CALCULATED) -> dict | None:
        if not any(v is not None for v in values.values()):
            return None
        return {"label": label, "unit": unit, "kind": kind, "values": {fy(c): values.get(c) for c in years}}

    def add(title: str, rows: list, source: str = src) -> None:
        rows = [r for r in rows if r]
        if rows:
            out.tables.append(Table(title, labels, rows, source))

    # DuPont: needs the prior year for average assets / equity
    pbt, interest = row(pl, "Profit before tax"), row(pl, "Interest")
    keys = ("nm", "tax", "int", "ebit", "turn", "mult", "roe", "roa")
    d: dict[str, dict] = {k: {} for k in keys}
    for c in years:
        i = out.years.index(c)
        if i == 0:
            continue
        p = out.years[i - 1]
        pat, r = s["pat"].get(c), rev.get(c)
        if pat is None or not r or not (ta.get(c) and ta.get(p) and nw.get(c) and nw.get(p)):
            continue
        avg_ta, avg_eq = (ta[c] + ta[p]) / 2, (nw[c] + nw[p]) / 2
        if avg_eq <= 0:
            continue
        pa = pat * out.attributable
        d["nm"][c], d["turn"][c], d["mult"][c] = pa / r * 100, r / avg_ta, avg_ta / avg_eq
        d["roa"][c], d["roe"][c] = pa / avg_ta * 100, pa / avg_eq * 100
        b, it = pbt.get(c), interest.get(c)
        if not snap.is_financial and b and it is not None and b + it:
            d["tax"][c], d["int"][c], d["ebit"][c] = pa / b * 100, b / (b + it) * 100, (b + it) / r * 100
    if snap.is_financial:
        spec = [("Net margin (A)", "%", "nm"), ("Asset turnover (B)", "x", "turn"), ("Equity multiplier (C)", "x", "mult"),
                ("Return on equity (A x B x C)", "%", "roe"), ("Return on assets", "%", "roa")]
    else:
        spec = [("Tax and minority burden (A)", "%", "tax"), ("Interest burden (B)", "%", "int"), ("EBIT margin (C)", "%", "ebit"),
                ("Asset turnover (D)", "x", "turn"), ("Equity multiplier (E)", "x", "mult"),
                ("Return on equity (A x B x C x D x E)", "%", "roe"), ("Return on assets", "%", "roa")]
        if not d["tax"]:  # PBT / interest missing: fall back to the three-step form
            spec = [("Net margin (A)", "%", "nm"), ("Asset turnover (B)", "x", "turn"), ("Equity multiplier (C)", "x", "mult"),
                    ("Return on equity (A x B x C)", "%", "roe"), ("Return on assets", "%", "roa")]
    add("DuPont analysis (ROE decomposition)", [line(label, unit, d[k]) for label, unit, k in spec],
        src + "; EBIT = profit before tax + interest; net profit attributable to shareholders; averages of opening and closing balances")
    out.dupont = {"spec": spec, "values": d}

    # common-size statements
    inc = [("Operating expenses", ("Expenses",)), ("Operating profit (EBITDA)", ("Operating Profit",)), ("Other income", ("Other Income",)),
           ("Depreciation", ("Depreciation",)), ("Interest", ("Interest",)), ("Profit before tax", ("Profit before tax",)), ("Net profit", ("Net Profit",))]
    add("Common-size income statement (% of revenue)",
        [line(label, "%", {c: (r_[c] / rev[c] * 100 if r_.get(c) is not None and rev.get(c) else None) for c in years})
         for label, names in inc for r_ in [row(pl, *names)] if r_])
    bal = [("Net worth (equity capital + reserves)", None), ("Deposits", ("Deposits",)), ("Borrowings", ("Borrowings", "Borrowing")),
           ("Other liabilities", ("Other Liabilities",)), ("Fixed assets", ("Fixed Assets",)), ("Capital work in progress", ("CWIP",)),
           ("Investments", ("Investments",)), ("Other assets", ("Other Assets",))]
    brows = []
    for label, names in bal:
        r_ = nw if names is None else row(bs, *names)
        if r_:
            brows.append(line(label, "%", {c: (r_[c] / ta[c] * 100 if r_.get(c) is not None and ta.get(c) else None) for c in years}))
    add("Common-size balance sheet (% of total assets)", brows)

    # working-capital cycle as published by screener.in
    wc = [("Debtor days", ("Debtor Days",)), ("Inventory days", ("Inventory Days",)), ("Payable days", ("Days Payable",)),
          ("Cash conversion cycle", ("Cash Conversion Cycle",)), ("Working-capital days", ("Working Capital Days",))]
    add("Working-capital cycle (days)", [line(label, "days", {c: r_.get(c) for c in years}, RAW) for label, names in wc for r_ in [row(ra, *names)] if r_], src)


def _ownership(snap: Snapshot, ledger: Ledger, out: Analysis) -> None:
    """Shareholding pattern over the last eight quarters (screener.in, from the companies' exchange filings) and the
    promoter pledge that screener.in flags when it is material."""
    shp = snap.tables.get("shp", {"cols": [], "rows": {}})
    cols = shp["cols"][-8:]
    src = f"{SCREENER} (quarterly shareholding filings)"
    rows = []
    for key, label in (("Promoters", "Promoters"), ("FIIs", "Foreign institutions (FIIs)"), ("DIIs", "Domestic institutions (DIIs)"),
                       ("Government", "Government"), ("Public", "Public"), ("Others", "Others")):
        r = row(shp, key)
        if any(r.get(c) is not None for c in cols):
            rows.append({"label": label, "unit": "%", "kind": RAW, "values": {c: r.get(c) for c in cols}})
            last = [c for c in cols if r.get(c) is not None]
            if key in ("Promoters", "FIIs", "DIIs") and last:
                slug = key.lower()
                out.facts[f"{slug}_holding"] = ledger.add(f"{label} holding", r[last[-1]], "%", last[-1], src, RAW)
                year_ago = shp["cols"][shp["cols"].index(last[-1]) - 4] if shp["cols"].index(last[-1]) >= 4 else None
                if year_ago and r.get(year_ago) is not None:
                    out.facts[f"{slug}_change"] = ledger.add(f"{label} holding change (4 quarters)", r[last[-1]] - r[year_ago], "pp", f"{year_ago} to {last[-1]}",
                                                             src, CALCULATED, method="latest holding minus holding four quarters earlier")
    if rows:
        out.tables.append(Table("Shareholding pattern (% of shares)", cols, rows, src))
    if snap.pledged_pct is not None:
        out.facts["pledged"] = ledger.add("Promoter holding pledged", snap.pledged_pct, "%", "latest", f"{SCREENER} (automated remarks)", RAW,
                                          method="share of the promoters' own holding that is pledged, as flagged by screener.in")


def _altman(snap: Snapshot, ledger: Ledger, out: Analysis) -> None:
    """Altman Z-score (original public-company model) for non-financial companies. Current assets and liabilities and
    retained earnings come from Yahoo Finance's balance sheet (screener.in does not itemise them); EBIT and sales come
    from screener.in for the same fiscal year. The two sources must agree on total assets within 15%, or the score is
    not computed -- mixing a different basis or currency would give a confident wrong number."""
    if snap.is_financial or not out.latest:
        return
    ys, s = snap.yf_statements, out.series

    def skip(reason: str) -> None:
        out.unavailable["Altman Z-score"] = reason

    if _currency_mismatch(snap.info):
        return skip(f"Yahoo Finance reports this company's balance sheet in {snap.info.get('financialCurrency')}, which cannot be combined with rupee figures.")
    if not ys or not ys.get("rows"):
        return skip("Needs current assets and liabilities and retained earnings; Yahoo Finance's balance sheet was not available.")
    col = datetime.strptime(ys["as_of"], "%Y-%m-%d").strftime("%b %Y")
    if col not in out.years:
        return skip(f"Yahoo Finance's latest balance sheet ({ys['as_of']}) does not match a fiscal year in the screener.in statements.")
    r = {k: v / 1e7 for k, v in ys["rows"].items()}  # rupees -> crore, like screener.in
    wc = r.get("Working Capital")
    if wc is None and "Current Assets" in r and "Current Liabilities" in r:
        wc = r["Current Assets"] - r["Current Liabilities"]
    ta, re_, tl = r.get("Total Assets"), r.get("Retained Earnings"), r.get("Total Liabilities Net Minority Interest")
    ebit, sales, mcap = s["ebit"].get(col), s["revenue"].get(col), out.facts.get("market_cap")
    if None in (wc, ta, re_, tl, ebit, sales, mcap) or not ta or not tl:
        return skip("One of its inputs (working capital, retained earnings, total liabilities, EBIT, sales or market value) is missing.")
    ta_s = s["total_assets"].get(col)
    if ta_s and not 0.85 <= ta / ta_s <= 1.15:
        return skip(f"Yahoo Finance and screener.in disagree on {fy(col)} total assets by more than 15%, so their figures cannot be combined.")
    z = 1.2 * wc / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * mcap.value / tl + 1.0 * sales / ta
    zone = "distress" if z < ALTMAN_ZONES[0] else ("grey" if z <= ALTMAN_ZONES[1] else "safe")
    out.facts["altman_z"] = ledger.add(
        "Altman Z-score", z, "", fy(col), f"ARIA analysis ({YAHOO} balance sheet; {SCREENER} EBIT and sales)", CALCULATED, inputs=[mcap],
        method=f"{zone} zone. 1.2 x working capital + 1.4 x retained earnings + 3.3 x EBIT + 1.0 x sales, each over total assets, "
               f"+ 0.6 x market cap / total liabilities; distress below {ALTMAN_ZONES[0]}, safe above {ALTMAN_ZONES[1]}. "
               "A statistical screen built on listed manufacturers")


def _competitive(snap: Snapshot, ledger: Ledger, out: Analysis) -> None:
    """The company beside its listed peers on the same Yahoo Finance trailing figures: ranks and its share of the peer
    set's combined revenue (a peer-set share, not an industry market share)."""
    if not snap.peers:
        return
    me = snap.as_peer()
    rows = [{"symbol": p.symbol, "name": p.name, "subject": p is me, "mcap_cr": p.mcap_cr, "revenue_cr": p.revenue_cr,
             "rev_growth": p.rev_growth, "op_margin": p.op_margin, "roe": p.roe} for p in (me, *snap.peers)]
    ranks = {}
    for key in ("mcap_cr", "revenue_cr", "rev_growth", "op_margin", "roe"):
        vals = sorted((x[key] for x in rows if x[key] is not None), reverse=True)
        if rows[0][key] is not None and len(vals) >= 3:
            ranks[key] = {"rank": vals.index(rows[0][key]) + 1, "of": len(vals)}
    revs = [x["revenue_cr"] for x in rows if x["revenue_cr"]]
    out.competitive = {"group": snap.peer_group, "rows": rows, "ranks": ranks, "revenue_share": None,
                       "revenue_peers": len(revs) - (1 if me.revenue_cr else 0), "peers": len(snap.peers)}
    if me.revenue_cr and len(revs) >= 3:
        share = me.revenue_cr / sum(revs)
        out.competitive["revenue_share"] = share
        out.facts["peer_rev_share"] = ledger.add(
            "Share of peer-set revenue", share * 100, "%", "trailing 12 months", f"ARIA analysis ({YAHOO} peer data)", CALCULATED,
            method=f"company revenue / combined revenue of the company and its {len(revs) - 1} listed peers with data; not an industry market share")


def dupont_note(out: Analysis) -> str:
    """Plain-English reading of the DuPont table: how ROE moved and which factor drove most of it (log shares,
    so the factors' contributions add to 100%). Empty when the maths is not meaningful (non-positive factors)."""
    spec, d = out.dupont.get("spec"), out.dupont.get("values")
    if not spec:
        return ""
    cols = [c for c in out.years if d["roe"].get(c) is not None]
    if len(cols) < 2:
        return ""
    a, b = cols[0], cols[-1]
    factors = [(label, unit, k) for label, unit, k in spec if k not in ("roe", "roa")]
    if d["roe"][a] <= 0 or d["roe"][b] <= 0 or any((d[k].get(a) or 0) <= 0 or (d[k].get(b) or 0) <= 0 for _, _, k in factors):
        return f"Return on equity moved from {fmt(d['roe'][a], '%')} in {fy(a)} to {fmt(d['roe'][b], '%')} in {fy(b)}."
    total = math.log(d["roe"][b] / d["roe"][a])
    text = f"Return on equity moved from {fmt(d['roe'][a], '%')} in {fy(a)} to {fmt(d['roe'][b], '%')} in {fy(b)}."
    if abs(total) < 0.02:
        return text + " It was essentially flat."
    shares = sorted(((math.log(d[k][b] / d[k][a]) / total, label.split(" (")[0].lower().replace("ebit", "EBIT")) for label, _, k in factors), reverse=True)
    drivers = [x for x in shares if x[0] > 0.05][:2]
    offsets = [x for x in shares if x[0] < -0.05]
    text += f" The change came mainly from {drivers[0][1]} (about {drivers[0][0] * 100:.0f}% of it)"
    if len(drivers) > 1:
        text += f" and {drivers[1][1]} ({drivers[1][0] * 100:.0f}%)"
    if offsets:
        text += ", partly offset by " + " and ".join(f"{name} (working against it by about {abs(sh) * 100:.0f}%)" for sh, name in offsets)
    return text + "."


def _risks(snap: Snapshot, out: Analysis, ledger: Ledger) -> None:
    F, s, L = out.facts, out.series, out.latest
    if not L:
        return

    def flag(category: str, severity: str, title: str, detail: str, *keys: str) -> None:
        out.risks.append(Risk(category, severity, title, detail, tuple(F[k].id for k in keys if k in F)))

    def val(key: str) -> float | None:
        return F[key].value if key in F else None

    if not snap.is_financial:
        if (de := val("de")) is not None and de > _HIGH_LEVERAGE_DE:
            flag("financial", "medium", "Leverage above 1x equity", f"Borrowings are {fmt(de, 'x')} net worth (flag threshold {_HIGH_LEVERAGE_DE:.1f}x).", "de")
        if (ic := val("interest_cover")) is not None and ic < _THIN_INTEREST_COVER:
            flag("financial", "high" if ic < 1.5 else "medium", "Thin interest cover",
                 f"Operating profit after depreciation covers interest {fmt(ic, 'x')} (threshold {_THIN_INTEREST_COVER:.0f}x).", "interest_cover")
        conv = median_recent(_values(s["cfo_pat"], out.years))
        if conv is not None and conv < _WEAK_CASH_CONVERSION:
            flag("financial", "medium", "Weak cash conversion",
                 f"Operating cash flow has been {fmt(conv, 'x')} net profit over the last 3 years (threshold {_WEAK_CASH_CONVERSION:.1f}x).", "cfo_pat")
        recent_fcf = [v for v in _values(s["fcf"], out.years)[-3:] if v is not None]
        if len(recent_fcf) >= 2 and sum(1 for v in recent_fcf if v < 0) >= 2:
            flag("financial", "medium", "Negative free cash flow", "Free cash flow was negative in at least 2 of the last 3 years.", "fcf")
        margins = _values(s["opm"], out.years)
        base = median_recent(margins[:-1]) if len(margins) > 3 else None
        if base is not None and s["opm"][L] is not None and (base - s["opm"][L]) * 100 > _MARGIN_COMPRESSION_PP:
            gap = ledger.add("EBITDA margin below prior 3y median", (base - s["opm"][L]) * 100, "pp", fy(L), "ARIA analysis", CALCULATED,
                             method="prior 3-year median EBITDA margin minus latest", inputs=[F["opm"]])
            F["margin_gap"] = gap
            flag("business", "medium", "Margin compression", f"EBITDA margin is {gap.text} below its prior 3-year median.", "margin_gap")
    else:
        if (npa := val("net_npa")) is not None and npa > _NPA_WATCH:
            flag("financial", "high" if npa > 3 else "medium", "Elevated net NPAs", f"Net NPA is {fmt(npa, '%')} of advances (watch level {_NPA_WATCH:.0f}%).", "net_npa")
        if (roe := val("roe")) is not None and roe < _WEAK_BANK_ROE:
            flag("financial", "medium", "Sub-par return on equity", f"ROE is {fmt(roe, '%')} (threshold {_WEAK_BANK_ROE:.0f}%).", "roe")
    if (p := val("pledged")) is not None and p >= _PLEDGE_WATCH:
        flag("market", "high" if p >= 50 else "medium", "Promoter shares pledged",
             f"Promoters have pledged {fmt(p, '%')} of their holding (watch level {_PLEDGE_WATCH:.0f}%); a sharp price fall can force lenders to sell.", "pledged")
    if (c := val("promoters_change")) is not None and c <= -_PROMOTER_EXIT_PP:
        flag("market", "medium", "Promoter holding falling", f"Promoters' stake fell {fmt(abs(c), 'pp')} over the last four quarters.", "promoters_change")
    if (z := val("altman_z")) is not None and z < ALTMAN_ZONES[0]:
        flag("financial", "medium", "Altman Z-score in the distress zone",
             f"The Z-score is {fmt(z, '')} (distress zone below {ALTMAN_ZONES[0]}); it is a statistical screen, not a forecast, and fits manufacturers best.", "altman_z")
    if (g := val("rev_growth")) is not None and g < 0:
        flag("business", "medium", "Revenue contracted", f"Revenue fell {fmt(abs(g), '%')} year on year.", "rev_growth")
    if (g := val("pat_growth")) is not None and g < 0:
        flag("business", "medium", "Profit declined", f"Net profit fell {fmt(abs(g), '%')} year on year.", "pat_growth")
    if (v := val("volatility")) is not None and v > _HIGH_VOLATILITY:
        flag("market", "medium", "High price volatility", f"Annualised volatility is {fmt(v, '%')} (threshold {_HIGH_VOLATILITY:.0f}%).", "volatility")
    if (d := val("max_drawdown")) is not None and d < -_DEEP_DRAWDOWN:
        flag("market", "medium", "Deep historical drawdown", f"The stock has fallen as much as {fmt(abs(d), '%')} peak-to-trough in the last 5 years.", "max_drawdown")
