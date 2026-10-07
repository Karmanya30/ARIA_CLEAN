"""
Report assembly: turns the analysis, valuation, audit, narrative and debate into

- ``build_report``      a structured, JSON-serialisable report (what the UI renders),
- ``to_markdown``       the same report as readable markdown,
- ``summary_response``  ARIA's 4-section "Insight / Analysis / Recommendation / Risk"
                        text -- the ``response`` field that TTS, the Tavus avatar and the
                        existing ResponseCard already consume.

Every number in the summary comes from a ledger fact's ``.text``; nothing is typed by hand
or by the model.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

from modules.equity_research.intelligence.agents import Debate, Narrative
from modules.equity_research.intelligence.analysis import Analysis, dupont_note, fy
from modules.equity_research.intelligence.audit import Audit
from modules.equity_research.intelligence.data import Snapshot, _currency_mismatch
from modules.equity_research.intelligence.facts import Fact, Ledger, fmt
from modules.equity_research.intelligence import lenses
from modules.equity_research.intelligence.fundamentals import analyze_fundamentals
from modules.equity_research.intelligence.valuation import (
    SCENARIO_WEIGHTS, Valuation, ddm_scenario_detail, scenario_detail, weighted_value,
)

DISCLAIMER = (
    "Automated, model-generated research for educational purposes. It is not investment advice or a recommendation to "
    "buy or sell any security, and ARIA is not a SEBI-registered research analyst or investment adviser. Figures come from "
    "the sources listed and may be delayed, incomplete or wrong; verify before acting."
)
_SEVERITY = {"high": 0, "medium": 1, "low": 2}


def _stance(val: Valuation, audit: Audit) -> dict:
    syn = val.synthesis
    if syn is None or audit.withhold_valuation:
        why = [f.message for f in audit.findings if f.severity == "blocked"] or [f"{k}: {v}" for k, v in val.skipped.items()]
        return {"rating": None, "stance": "Not assessed", "fair_value": None, "low": None, "high": None, "upside_pct": None,
                "confidence": None, "withheld": True, "price": syn.price if syn else None, "notes": why}
    return {"rating": syn.rating, "stance": syn.stance, "fair_value": syn.central, "low": syn.low, "high": syn.high,
            "upside_pct": syn.upside * 100, "confidence": syn.tier, "withheld": syn.withheld, "price": syn.price, "notes": list(syn.notes)}


def _valuation_block(snap: Snapshot, an: Analysis, val: Valuation, audit: Audit, narr: Narrative) -> dict:
    blocked = audit.withhold_valuation
    F = an.facts
    block: dict = {
        "text": narr.valuation,
        "methods": [] if blocked else [m.to_dict() for m in val.methods],
        "skipped": val.skipped, "notes": val.notes, "comps": val.comps,
        "cost_of_capital": {k: (v * 100 if k != "beta" else v) for k, v in val.coc.items()} if val.coc and not blocked else {},
        "street": {k: (F[k].value if k in F else None) for k in ("target_mean", "target_high", "target_low", "analysts")},
        "dcf": None, "ddm": None,
    }
    if val.dcf_result and not blocked:
        block["dcf"] = {"inputs": {**asdict(val.dcf_inputs), "growth": list(val.dcf_inputs.growth)}, "result": asdict(val.dcf_result),
                        "walk": _dcf_walk(val, snap, an),
                        "sensitivity": val.dcf_extra.get("prices") and {k: val.dcf_extra[k] for k in ("wacc_values", "tg_values", "prices")},
                        "margin_swing": val.dcf_extra.get("margin_swing"), "reverse": val.dcf_extra.get("reverse"),
                        "implied_wacc": val.dcf_extra.get("implied_wacc"), "lbo": val.dcf_extra.get("lbo")}
    if val.ddm_result and not blocked:
        block["ddm"] = {"inputs": {**asdict(val.ddm_inputs), "growth": list(val.ddm_inputs.growth)}, "result": asdict(val.ddm_result)}
    return block


def build_report(snap: Snapshot, an: Analysis, val: Valuation, audit: Audit, narr: Narrative, deb: Debate, ledger: Ledger,
                 kind: str = "equity_research") -> dict:
    fund = an.fundamentals if an.fundamentals is not None else analyze_fundamentals(snap, an, val, ledger)
    if fund.get("scorecard"):  # the valuation may have been withheld by the audit since the scorecard was first read
        fund["scorecard"]["overlay"] = lenses.overlay(fund["scorecard"]["pillars"], val)
        fund["intelligence"] = lenses.intelligence(fund, val)
    stance = _stance(val, audit)
    if (overlay := (fund.get("scorecard") or {}).get("overlay")):
        stance["notes"] = [*stance["notes"], overlay["reading"]]
        stance["quality_overlay"] = overlay
    risks = [{**r.to_dict(), "origin": "rule"} for r in sorted([*an.risks, *val.risks], key=lambda r: _SEVERITY[r.severity])]
    risks += _fundamental_risks(fund)
    risks += [{"category": r["category"], "severity": "", "title": "", "detail": r["text"], "facts": [], "origin": "llm"} for r in narr.risks]
    by_source: dict[str, dict] = {}
    for f in ledger:
        entry = by_source.setdefault(f.source, {"source": f.source, "count": 0, "kinds": {}})
        entry["count"] += 1
        entry["kinds"][f.kind] = entry["kinds"].get(f.kind, 0) + 1
    judge = deb.judge
    return {
        "title": f"{snap.name} ({snap.target.symbol}) - equity research",
        "kind": kind,
        "dupont_note": dupont_note(an),
        "cover": _cover(snap, an),
        "snapshot": _pick(an.facts, _SNAPSHOT),
        "ratio_groups": [{"group": g, "items": _pick(an.facts, keys)} for g, keys in _RATIO_GROUPS if _pick(an.facts, keys)],
        "forecast": _forecast(snap, an, val),
        "assumption_table": [] if audit.withhold_valuation else _assumption_rows(an, val),
        "scenarios": None if audit.withhold_valuation else _scenarios(val, snap.price, an),
        "fundamentals": fund,
        "drivers": _drivers(an, narr),
        "not_available": _not_available(snap, an, val),
        "ownership": {**{k: an.facts[k].value for k in _OWNERSHIP if k in an.facts}, "pledged_pct": snap.pledged_pct},
        "competitive": an.competitive or None,
        "company": {"name": snap.name, "symbol": snap.target.symbol, "sector": snap.info.get("sector"), "industry": snap.info.get("industry"),
                    "price": snap.price, "market_cap_cr": snap.market_cap_cr, "as_of": snap.as_of, "basis": snap.view},
        "status": audit.status,
        "stance": stance,
        "thesis": narr.thesis,
        "business": narr.business,
        "financials": {"text": narr.financial, "tables": [t.to_dict() for t in an.tables]},
        "valuation": _valuation_block(snap, an, val, audit, narr),
        "risks": risks,
        "catalysts": narr.catalysts,
        "news": snap.news,
        "wiki": snap.wiki,
        "debate": {**deb.to_dict(), "aligned": None if not judge or val.synthesis is None or audit.withhold_valuation else judge["call"] == val.synthesis.rating},
        "assumptions": [f.to_dict() for f in ledger if f.tag == "model_input"],
        "facts": ledger.to_dicts(),
        "audit": audit.to_dict(),
        "sources": sorted(by_source.values(), key=lambda s: -s["count"]),
        "narrative_origin": narr.origin,
        "disclaimer": DISCLAIMER,
    }



# ── report sections beyond the analysis itself ─────────────────────────────
_SNAPSHOT = ("revenue", "rev_growth", "ebitda", "opm", "ebit", "pat", "eps", "fcf", "roe", "roce", "net_debt", "de", "net_debt_ebitda",
             "leverage", "gross_npa", "net_npa")
_RATIO_GROUPS = (
    ("Profitability", ("gross_margin", "opm", "ebit_margin", "net_margin", "roe", "roe3", "roce", "roic")),
    ("Growth", ("rev_growth", "rev_cagr3", "rev_cagr5", "pat_growth", "pat_cagr3", "eps_cagr3", "eps_cagr5", "q_rev_growth", "q_pat_growth", "q_margin_change")),
    ("Liquidity and working capital", ("current_ratio", "quick_ratio", "wc_days")),
    ("Leverage and coverage", ("de", "net_debt", "net_debt_ebitda", "interest_cover", "leverage", "altman_z")),
    ("Efficiency and cash generation", ("asset_turnover", "cfo_pat", "capex_pct", "fcf", "fcf_margin")),
    ("Asset quality (lenders)", ("gross_npa", "net_npa", "deposit_growth")),
    ("Valuation", ("pe", "pb", "ev_ebitda", "ev_sales", "fcf_yield", "div_yield")),
    ("Price behaviour", ("ret_1y", "ret_vs_nifty", "vs_ma40", "rsi", "volatility", "max_drawdown", "high_52w", "low_52w")),
)


_OWNERSHIP = ("promoters_holding", "promoters_change", "fiis_holding", "fiis_change", "diis_holding", "diis_change")


def _management(snap: Snapshot) -> list[dict]:
    """Key officers from Yahoo Finance. Pay is shown only when Yahoo's figures are in rupees throughout."""
    rupees = snap.info.get("currency") in (None, "INR") and not _currency_mismatch(snap.info)
    out = []
    for o in (snap.info.get("companyOfficers") or [])[:6]:
        name, pay = " ".join(str(o.get("name") or "").split()), o.get("totalPay")
        if name:
            out.append({"name": name, "title": " ".join(str(o.get("title") or "").split()), "age": o.get("age"),
                        "pay_cr": pay / 1e7 if rupees and isinstance(pay, (int, float)) and pay > 0 else None, "pay_year": o.get("fiscalYear")})
    return out


def _row(f: Fact) -> dict:
    return {"id": f.id, "label": f.label, "text": f.text, "period": f.period, "kind": f.kind, "source": f.source, "method": f.method}


def _pick(facts: dict[str, Fact], keys) -> list[dict]:
    return [_row(facts[k]) for k in keys if k in facts]


def _t(facts: dict[str, Fact], key: str) -> str:
    return facts[key].text if key in facts else "n/a"


def _pct(x) -> float | None:
    return x * 100 if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _cover(snap: Snapshot, an: Analysis) -> dict:
    quarters = snap.tables.get("quarterly", {}).get("cols", [])
    return {
        "name": snap.name, "symbol": snap.target.symbol, "exchange": snap.exchange, "sector": snap.info.get("sector"),
        "industry": snap.info.get("industry"), "price": snap.price, "market_cap_cr": snap.market_cap_cr,
        "report_date": date.today().isoformat(),
        "data_through": {"market data": snap.as_of, "latest annual statements": fy(an.latest) or "n/a",
                         "latest quarter": quarters[-1] if quarters else "n/a"},
        "ownership": {"insiders": _pct(snap.info.get("heldPercentInsiders")), "institutions": _pct(snap.info.get("heldPercentInstitutions"))},
        "street_rating": snap.info.get("recommendationKey"),
        "basis": snap.view, "employees": snap.info.get("fullTimeEmployees"), "website": snap.info.get("website"),
        "leadership": [f"{o.get('name', '').strip()} ({o.get('title', '').strip()})" for o in (snap.info.get("companyOfficers") or [])[:4] if o.get("name")],
        "management": _management(snap),
        "ai_disclosure": "AI-assisted research: every figure is computed by code from the sources listed; the language model only writes "
                         "prose that cites those figures. Sections are tagged by what they are.",
    }


def _forecast(snap: Snapshot, an: Analysis, val: Valuation) -> dict | None:
    """Actual columns (up to 5 fiscal years) beside the model's 12-month estimate periods. A row is either
    reported (actual columns only) or modelled (estimate columns only): the two are never mixed in one row."""
    if not an.latest or not (val.dcf_result or val.ddm_result):
        return None
    hist = an.years[-5:]
    hist_labels = [f"{fy(c)}A" for c in hist]
    quarters = snap.tables.get("quarterly", {}).get("cols", [])
    base = quarters[-1] if an.ttm.get("revenue") and quarters else an.latest
    month, year = base.split()
    s = an.series

    def hist_row(label, key, unit, scale=1.0, kind="actual"):
        return {"label": label, "unit": unit, "kind": kind, "values": {c: (s[key][h] * scale if s[key].get(h) is not None else None) for c, h in zip(hist_labels, hist)}}

    rows: list[dict] = []
    if val.dcf_result:
        res, inp = val.dcf_result, val.dcf_inputs
        n = min(5, len(res.revenue))
        est = [f"{month} {int(year) + i + 1}E" for i in range(n)]
        da = [r * inp.da_pct for r in res.revenue[:n]]
        ebit = [e - d for e, d in zip(res.ebitda[:n], da)]

        def est_row(label, values, unit):
            return {"label": label, "unit": unit, "kind": "estimate", "values": dict(zip(est, values))}

        rows = [
            hist_row("Revenue", "revenue", "₹ Cr"), est_row("Revenue", res.revenue[:n], "₹ Cr"),
            hist_row("Revenue growth", "rev_growth", "%", 100), est_row("Revenue growth", [g * 100 for g in inp.growth[:n]], "%"),
            hist_row("EBITDA", "ebitda", "₹ Cr"), est_row("EBITDA", res.ebitda[:n], "₹ Cr"),
            hist_row("EBITDA margin", "opm", "%", 100), est_row("EBITDA margin", [inp.ebitda_margin * 100] * n, "%"),
            hist_row("EBIT", "ebit", "₹ Cr"), est_row("EBIT", ebit, "₹ Cr"),
            hist_row("Free cash flow (reported: operating cash flow less capex)", "fcf", "₹ Cr"),
            est_row("Unlevered free cash flow (model)", res.fcf[:n], "₹ Cr"),
        ]
        note = ("Estimate periods are the 12-month periods after the trailing-twelve-month base (to "
                f"{base}). Estimates are the DCF's own projection; EPS is not forecast because that needs other-income and "
                "financing assumptions the sources do not provide.")
    else:
        inp = val.ddm_inputs
        n = 5
        est = [f"{month} {int(year) + i + 1}E" for i in range(n)]
        eps, path = inp.eps0, []
        for g in inp.growth[:n]:
            eps *= 1 + g
            path.append(eps)
        rows = [hist_row("EPS", "eps", "₹"), {"label": "EPS", "unit": "₹", "kind": "estimate", "values": dict(zip(est, path))},
                {"label": "EPS growth", "unit": "%", "kind": "estimate", "values": dict(zip(est, [g * 100 for g in inp.growth[:n]]))},
                {"label": "Dividend per share", "unit": "₹", "kind": "estimate", "values": dict(zip(est, val.ddm_result.dividends[:n]))},
                hist_row("Net profit", "pat", "₹ Cr")]
        note = f"Estimates are the DDM's EPS and dividend path from the trailing-twelve-month EPS base (to {base})."
    return {"columns": hist_labels + est, "n_actual": len(hist_labels), "rows": rows, "note": note}


def _assumption_rows(an: Analysis, val: Valuation) -> list[dict]:
    F, V, s, L = an.facts, val.facts, an.series, an.latest
    pct = lambda key: fmt(s[key][L] * 100, "%") if L and key in s and s[key].get(L) is not None else "n/a"  # noqa: E731
    rows = []

    def add(name, hist, forecast, fact):
        if fact is not None:
            rows.append({"assumption": name, "historical": hist, "forecast": forecast, "reason": fact.method, "fact": fact.id, "kind": fact.kind})

    if val.dcf_result:
        add("Revenue growth", f"{_t(F, 'rev_growth')} latest year; {_t(F, 'rev_cagr3')} 3-year CAGR",
            f"{_t(V, 'g1')} in year 1, fading to {_t(V, 'tg')} by year 10", V.get("g1"))
        add("EBITDA margin", f"{_t(F, 'opm')} latest year", f"{_t(V, 'margin')} held flat", V.get("margin"))
        add("Depreciation / revenue", pct("da_pct"), _t(V, "da"), V.get("da"))
        add("Capex / revenue", _t(F, "capex_pct"), f"{_t(V, 'capex')} in the growth phase, scaling down with growth to maintenance", V.get("capex"))
        add("Working capital / revenue", _t(F, "wc_days"), f"{_t(V, 'nwc')} of revenue, scaling with revenue growth", V.get("nwc"))
        add("Tax rate", pct("tax_rate"), _t(V, "tax"), V.get("tax"))
        add("Terminal growth", "n/a (configured)", _t(V, "tg"), V.get("tg"))
        add("Beta", "regression on Nifty 50", _t(V, "beta"), V.get("beta"))
        add("Cost of equity", "n/a", _t(V, "coe"), V.get("coe"))
        add("WACC", "n/a", _t(V, "wacc"), V.get("wacc"))
        add("Net debt", _t(F, "net_debt"), _t(V, "net_debt"), V.get("net_debt"))
    elif val.ddm_result:
        add("EPS growth", f"{_t(F, 'eps_cagr3')} 3-year CAGR", f"{_t(V, 'g1')} in year 1, fading to {_t(V, 'tg')} by year 10", V.get("g1"))
        add("Dividend payout", _t(F, "payout"), _t(V, "payout"), V.get("payout"))
        add("Long-run ROE", _t(F, "roe"), _t(V, "roe_t"), V.get("roe_t"))
        add("Terminal growth", "n/a (configured)", _t(V, "tg"), V.get("tg"))
        add("Beta", "regression on Nifty 50", _t(V, "beta"), V.get("beta"))
        add("Cost of equity", "n/a", _t(V, "coe"), V.get("coe"))
        add("Book value per share", "latest", _t(V, "bvps"), V.get("bvps"))
    return rows


def _scenarios(val: Valuation, price: float | None, an: Analysis | None = None) -> dict | None:
    """Bear / base / bull, each worked through in full: its assumptions, the history it starts from, every forecast line,
    the discounting and the bridge to value per share; then the three side by side and their probability-weighted value."""
    if not val.scenarios:
        return None
    what = {"bear": "growth and margin -2pp, WACC +1pp, terminal growth -0.5pp", "base": "the model's central assumptions",
            "bull": "growth and margin +2pp, WACC -1pp, terminal growth +0.5pp"} if val.dcf_result else \
           {"bear": "EPS growth -2pp, cost of equity +1pp", "base": "the model's central assumptions", "bull": "EPS growth +2pp, cost of equity -1pp"}
    detail = (lambda d: scenario_detail(val.dcf_inputs, d)) if val.dcf_result else (lambda d: ddm_scenario_detail(val.ddm_inputs, d))
    cases = [{"name": n.title(), "key": n, "value": val.scenarios.get(n), "assumptions": what[n], "weight": SCENARIO_WEIGHTS[n],
              "upside_pct": (val.scenarios[n] / price - 1) * 100 if val.scenarios.get(n) and price else None, "detail": detail(d)}
             for n, d in (("bear", -1), ("base", 0), ("bull", 1))]
    weighted = weighted_value(val.scenarios)
    history = None
    if an and an.years:
        hist = an.years[-3:]
        keys = ("revenue", "rev_growth", "ebitda", "opm", "ebit", "pat") if val.dcf_result else ("eps", "pat", "payout", "roe")
        history = {"columns": [f"{fy(c)}A" for c in hist], "rows": {k: [an.series.get(k, {}).get(c) for c in hist] for k in keys}}
    return {"cases": cases, "monte_carlo": val.monte_carlo, "model": "DCF" if val.dcf_result else "DDM", "history": history,
            "weighted": weighted, "weighted_upside_pct": (weighted / price - 1) * 100 if weighted and price else None,
            "weights": SCENARIO_WEIGHTS}


def _dcf_walk(val: Valuation, snap: Snapshot, an: Analysis) -> dict | None:
    if not val.dcf_result:
        return None
    res, inp = val.dcf_result, val.dcf_inputs
    quarters = snap.tables.get("quarterly", {}).get("cols", [])
    month, year = (quarters[-1] if an.ttm.get("revenue") and quarters else an.latest).split()
    years = [{"period": f"{month} {int(year) + i + 1}E", "revenue": res.revenue[i], "ebitda": res.ebitda[i], "fcf": res.fcf[i],
              "discount_factor": 1 / (1 + inp.wacc) ** (i + 1), "pv": res.fcf[i] / (1 + inp.wacc) ** (i + 1)} for i in range(len(res.fcf))]
    summary = [("PV of explicit-period free cash flow", res.pv_fcf, "₹ Cr"), ("Steady-state free cash flow", res.terminal_fcf, "₹ Cr"),
               ("Terminal value (undiscounted)", res.terminal_value, "₹ Cr"), ("PV of terminal value", res.pv_terminal, "₹ Cr"),
               ("Enterprise value", res.enterprise_value, "₹ Cr"),
               ("Less: net debt" if inp.net_debt >= 0 else "Add: net cash", -inp.net_debt, "₹ Cr"), ("Less: minority interest", -inp.nci, "₹ Cr"),
               ("Equity value", res.equity_value, "₹ Cr"), ("Shares outstanding", inp.shares_cr, "Cr shares"), ("Value per share", res.per_share, "₹"),
               ("Terminal value share of EV", res.tv_share * 100, "%")]
    n = len(res.fcf)
    summary.insert(4, ("Implied terminal EV/EBITDA (perpetuity method)", res.terminal_value / res.ebitda[-1], "x"))
    med = (val.comps or {}).get("medians", {}).get("ev_ebitda")
    check = None
    if med:  # cross-check only (never blended): terminal value from the peer-median EV/EBITDA instead of perpetual growth
        ev = res.pv_fcf + med * res.ebitda[-1] / (1 + inp.wacc) ** n
        check = {"multiple": med, "per_share": (ev - inp.net_debt - inp.nci) / inp.shares_cr}
    return {"years": years, "summary": [{"label": a, "text": fmt(b, u)} for a, b, u in summary], "exit_check": check}


def _not_available(snap: Snapshot, an: Analysis, val: Valuation) -> list[dict]:
    items = [
        *([("Altman Z-score", an.unavailable["Altman Z-score"])] if "Altman Z-score" in an.unavailable else []),
        *([("Shareholding history", "screener.in's shareholding table was not available; only Yahoo Finance's latest insider and institutional percentages are shown.")]
          if not any(t.title.startswith("Shareholding") for t in an.tables) else []),
        ("Business segments, revenue mix and geography", "The configured sources (screener.in, Yahoo Finance) report company totals only; no segment or geographic split is available, so none is shown."),
        ("Customer and end-market exposure", "Not disclosed in the configured sources."),
        *([("Gross profit and gross margin", "Not reported for this company by the configured sources.")] if "gross_margin" not in an.facts else []),
        *([("Current and quick ratios", "Not reported for this company by the configured sources; working-capital days are shown instead.")] if "current_ratio" not in an.facts and not snap.is_financial else []),
        *([("ROIC", "Could not be computed: EBIT, net worth or borrowings missing.")] if "roic" not in an.facts and not snap.is_financial else []),
        ("Industry size, industry-wide market shares and regulatory environment", "Not available from the configured sources; the company's share of its listed "
         "peer set's revenue is shown instead, and no industry statistics are asserted."),
        ("Precedent transactions and sum-of-the-parts valuation", "These need deal or segment data that the configured sources do not provide."),
    ]
    if val.dcf_result:
        items.append(("EPS forecast", "Not produced: a consistent earnings forecast needs other-income and financing assumptions the sources do not provide."))
        lb = val.dcf_extra.get("lbo")
        if lb and lb["per_share"] is None:
            items.append(("LBO cross-check", f"Not binding: {lb['reason']}."))
    for key, why in val.skipped.items():
        items.append((f"Valuation method '{key}'", why))
    return [{"item": a, "reason": b} for a, b in items]


def _drivers(an: Analysis, narr: Narrative) -> list[dict]:
    F = an.facts
    out = [{"text": f"Revenue growth: {_t(F, 'rev_growth')} last year, {_t(F, 'rev_cagr3')} a year over three years.", "origin": "calculated"}] if "rev_growth" in F else []
    if "opm" in F:
        out.append({"text": f"Margin: {F['opm'].label} of {_t(F, 'opm')}; a 2pp move materially changes the DCF value.", "origin": "calculated"})
    if "q_rev_growth" in F:
        out.append({"text": f"Recent momentum: latest-quarter revenue {_t(F, 'q_rev_growth')} and net profit {_t(F, 'q_pat_growth')} year on year.", "origin": "calculated"})
    out += [{"text": c, "origin": "ai"} for c in narr.catalysts]
    return out


# ── the ARIA 4-section summary ─────────────────────────────────────────────
def summary_response(snap: Snapshot, an: Analysis, val: Valuation, audit: Audit, deb: Debate) -> str:
    f, v, syn = an.facts, val.facts, val.synthesis
    T = lambda d, k: d[k].text if k in d else "n/a"  # noqa: E731
    live = syn is not None and not audit.withhold_valuation
    if live and syn.central is not None:
        insight = (f"{snap.name}: the model's fair value is {T(v, 'fair_value')} against a share price of {T(f, 'price')} "
                   f"({T(v, 'upside')}), which reads as {syn.stance.lower()} at {syn.tier.replace('_', ' ')} confidence.")
    elif live:
        insight = (f"{snap.name}: no single fair value could be defended, but the valuation range of {T(v, 'range_low')} to {T(v, 'range_high')} "
                   f"against a share price of {T(f, 'price')} reads as {syn.stance.lower()} ({syn.tier.replace('_', ' ')} confidence).")
    else:
        insight = f"{snap.name}: a fair value could not be computed from the data available."

    bits = []
    if "revenue" in f:
        bits.append(f"revenue {T(f, 'revenue')} in {f['revenue'].period}" + (f" ({T(f, 'rev_growth')} year on year)" if "rev_growth" in f else ""))
    if "opm" in f:
        bits.append(f"{f['opm'].label} {T(f, 'opm')}")
    if "roe" in f:
        bits.append(f"ROE {T(f, 'roe')}")
    if "de" in f:
        bits.append(f"debt/equity {T(f, 'de')}")
    if "net_npa" in f:
        bits.append(f"net NPA {T(f, 'net_npa')}")
    analysis = ("Fundamentals: " + ", ".join(bits) + "." if bits else "Financial statement data was limited.")
    if (it := (an.fundamentals or {}).get("intelligence")) and it["score"] is not None:
        analysis += f" Intelligence score {it['score']}/100 ({it['band']})" + (f"; watch: {it['divergences'][0]['text'].lower()}" if it["divergences"] else "") + "."
    if live:
        analysis += " Valuation methods: " + ", ".join(f"{m.label} {fmt(m.mid, '₹')}" for m in syn.methods) + "."

    if live:
        rec = f"Model-implied rating: {syn.rating} (general research, not personalised advice)."
    else:
        rec = "No valuation-based rating is given because the fair value could not be verified."
    if deb.judge:
        rec += f" The bull/bear judge leans {deb.judge['call']}" + (f"; the deciding question: {deb.judge['swing_factor']}" if deb.judge.get("swing_factor") else ".")

    top = sorted([*an.risks, *val.risks], key=lambda r: _SEVERITY[r.severity])[:2]
    risk = " ".join(f"{r.title}: {r.detail}" for r in top) or "No rule-based risk flags were raised."
    if audit.status == "caveated":
        risk += " The report carries data-quality caveats; see the verification section."
    return f"Insight: {insight}\nAnalysis: {analysis}\nRecommendation: {rec}\nRisk: {risk}"


# ── markdown ───────────────────────────────────────────────────────────────
def _md_table(columns: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "| " + " | ".join(columns) + " |\n|" + "|".join("---" for _ in columns) + "|\n"
    return head + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"


def to_markdown(report: dict) -> str:
    c, s, val = report["company"], report["stance"], report["valuation"]
    out = [f"# {report['title']}", "",
           f"Price {fmt(c['price'], '₹')} · Market cap {fmt(c['market_cap_cr'], '₹ Cr')} · {c['sector'] or ''} / {c['industry'] or ''} · "
           f"{c['basis']} statements · as of {c['as_of']} · verification: **{report['status']}**", ""]
    if s["rating"]:
        fv = f"fair value {fmt(s['fair_value'], '₹')}" if s["fair_value"] is not None else f"range {fmt(s['low'], '₹')}-{fmt(s['high'], '₹')} (point estimate withheld)"
        out += [f"**{s['stance']}** - model-implied rating {s['rating']}, {fv}, {fmt(s['upside_pct'], '%')} vs price, {s['confidence'].replace('_', ' ')} confidence.", ""]
    else:
        out += ["**Valuation not assessed.** " + " ".join(s["notes"]), ""]
    if report["thesis"]:
        out += ["## Investment thesis", *[f"- {b}" for b in report["thesis"]], ""]
    out += ["## Business", report["business"], "", "## Financial analysis", report["financials"]["text"], ""]
    for t in report["financials"]["tables"]:
        out += [f"**{t['title']}** ({t['source']})", "",
                _md_table([""] + t["columns"], [[r["label"]] + [fmt(r["values"].get(col), r["unit"]) for col in t["columns"]] for r in t["rows"]])]
    out += ["## Valuation", val["text"], ""]
    if val["methods"]:
        out += [_md_table(["Method", "Low", "Mid", "High", "Basis"], [[m["label"], fmt(m["low"], "₹"), fmt(m["mid"], "₹"), fmt(m["high"], "₹"), m["basis"]] for m in val["methods"]])]
    out += [f"- {n}" for n in val["notes"] + s["notes"]]
    out += [f"- {k}: not run - {why}" for k, why in val["skipped"].items()] + [""]
    lb = (val.get("dcf") or {}).get("lbo")
    if lb and lb.get("per_share") is not None:
        out += [f"- LBO cross-check (not blended): a buyer borrowing {lb['leverage']:g}x EBITDA could pay up to {fmt(lb['entry_multiple'], 'x')} EBITDA, "
                f"about {fmt(lb['per_share'], '₹')} a share, for a {lb['irr']:.0%} return over {lb['years']} years.", ""]
    if val["comps"]:
        out += ["**Peer multiples** (" + str(val["comps"]["group"]) + " peers; blank = not available or excluded)", "",
                _md_table(["Peer", "P/E", "P/B", "EV/EBITDA"], [[p["name"], *[("" if p[k] is None or k in p["excluded"] else fmt(p[k], "x")) for k in ("pe", "pb", "ev_ebitda")]] for p in val["comps"]["peers"]])]
    out += _md_scenarios(report.get("scenarios")) + _md_fundamentals(report.get("fundamentals"))
    d = report["debate"]
    if d["bull"] or d["bear"]:
        out += ["## Bull vs bear"]
        for title, args in (("Bull case", d["bull"]), ("Bear case", d["bear"])):
            out += [f"**{title}**"] + [f"- {a['claim']} _(" + "; ".join(f"{e['label']} {e['value']}" for e in a["evidence"]) + ")_" for a in args] + [""]
        if d["judge"]:
            j = d["judge"]
            out += [f"**Judge:** {j['call']} (conviction {j['conviction']:.0%}). Swing factor: {j['swing_factor']} What would change the call: {j['change_my_mind']}", ""]
    out += ["## Risks"] + [f"- [{r['category']}] " + (f"**{r['title']}** " if r["title"] else "") + r["detail"] for r in report["risks"]] + [""]
    if report["catalysts"]:
        out += ["## Catalysts"] + [f"- {x}" for x in report["catalysts"]] + [""]
    if report["news"]:
        out += ["## Recent headlines"] + [f"- {n['date']} - {n['title']} ({n['source']})" for n in report["news"]] + [""]
    out += ["## Assumptions", _md_table(["Assumption", "Value", "Basis"], [[a["label"], a["text"], a["method"]] for a in report["assumptions"]]),
            "## Verification"] + [f"- {'✓' if k['status'] == 'pass' else '⚠'} {k['title']}" + ("" if k["status"] == "pass" else ": " + " ".join(k["findings"])) for k in report["audit"]["checks"]]
    out += ["", "## Sources", *[f"- {x['source']}: {x['count']} figures" for x in report["sources"]], "", f"_{report['disclaimer']}_"]
    return "\n".join(out)


def _md_scenarios(sc: dict | None) -> list[str]:
    if not sc:
        return []
    out = ["## Scenarios", _md_table(["", "Bear", "Base", "Bull"], [
        ["Value per share"] + [fmt(c["value"], "₹") for c in sc["cases"]],
        ["vs price"] + [fmt(c["upside_pct"], "%") for c in sc["cases"]],
        ["What changes"] + [c["assumptions"] for c in sc["cases"]],
        ["Weight"] + [f"{c['weight']:.0%}" for c in sc["cases"]]])]
    if sc.get("weighted"):
        out.append(f"Probability-weighted value: **{fmt(sc['weighted'], '₹')}**" + (f" ({fmt(sc['weighted_upside_pct'], '%')} vs price)" if sc.get("weighted_upside_pct") is not None else "")
                   + ". The full year-by-year build of each case is in the HTML/PDF report.")
    return out + [""]


def _md_fundamentals(f: dict | None) -> list[str]:
    if not f or not f.get("available"):
        return []
    out = ["## Fundamental analysis"]
    if sc := f.get("scorecard"):
        out.append(f"**{sc['overlay']['reading']}**")
        if (it := f.get("intelligence")) and it["score"] is not None:
            out.append(f"- Intelligence score: **{it['score']}/100 ({it['band']})**" + "".join(f"; {d['text'].lower()}" for d in it["divergences"]))
        out += [f"- {x['name']}: **{x['rating']}**" for x in sc["pillars"]]
    L = f.get("lenses") or {}
    for key, name in (("graham", "Graham defensive tests"), ("buffett", "Buffett consistency tests")):
        if (x := L.get(key) or {}).get("available"):
            out.append(f"- {name}: {x['score']} of {x['tested']} pass")
    if (g := L.get("graham") or {}).get("number") is not None:
        out.append(f"- Graham number {fmt(g['number'], '₹')} (margin of safety {g['margin_of_safety']:+.0%})")
    if (ly := L.get("lynch") or {}).get("available"):
        out.append(f"- Lynch PEG {ly['peg']:.2f}: {ly['reading']}")
    p = f["piotroski"]
    if p.get("available"):
        out.append(f"- Piotroski F-score: **{p['score']} of {p['tested']}** tested signals ({p['verdict']})")
    if (q := f["quality"]).get("cash_conversion") is not None:
        out.append(f"- Cash conversion (3-year median): {fmt(q['cash_conversion'], 'x')} ({q.get('verdict', '')})")
    if (v := f["value_creation"]).get("available"):
        out.append(f"- ROIC {fmt(v['roic'], '%')} vs WACC {fmt(v['wacc'], '%')}: {v['spread']:+.1f}pp ({'creates value' if v['creates_value'] else 'below its cost of capital'})")
    if (g := f["growth_check"]).get("available"):
        out.append(f"- Fundamental growth not meaningful: {g['note']}" if g["fundamental"] is None else
                   f"- Fundamental growth {fmt(g['fundamental'] * 100, '%')}" + (f" vs forecast {fmt(g['model'] * 100, '%')}: {g['verdict']}" if g.get("model") is not None else ""))
    if (o := f["owner_earnings"]).get("available"):
        out.append(f"- Owner earnings {fmt(o['value'], '₹ Cr')}" + (f" ({o['yield']:.1%} of market value)" if o.get("yield") is not None else ""))
    if (r := f["residual_income"]).get("available"):
        out.append(f"- Residual income value {fmt(r['per_share'], '₹')} per share" + (f" ({fmt(r['upside'] * 100, '%')} vs price)" if r.get("upside") is not None else ""))
    ns = f["news_signals"]
    if ns["items"]:
        out.append("- News themes: " + "; ".join(f"{cat} {c['positive']}+/{c['negative']}-" for cat, c in ns["summary"].items()))
    if f["news_signals"].get("net") is not None:
        out.append(f"- News tone (FinBERT): {f['news_signals']['net']:+.2f} across {f['news_signals']['scored']} headlines")
    if (c := f.get("concall") or {}).get("available") and c.get("net") is not None:
        out.append(f"- Earnings call {c['period']} tone (FinBERT): {c['net']:+.2f} ({c['positive_share']:.0%} positive, {c['negative_share']:.0%} negative sentences)")
    return out + [""]


_PILLAR_CATEGORY = {"Quality": "financial", "Valuation lenses": "valuation", "Growth": "business", "Financial safety": "financial", "Technical": "market", "Sentiment": "market"}


def _fundamental_risks(fund: dict) -> list[dict]:
    """A weak pillar of the scorecard is a risk in its own right: shown with the specific readings that made it weak."""
    out = []
    for p in (fund.get("scorecard") or {}).get("pillars", []):
        if p["rating"] == "weak":
            bad = [r["text"] for r in p["reasons"] if r["sign"] < 0]
            out.append({"category": _PILLAR_CATEGORY.get(p["name"], "financial"), "severity": "medium", "title": f"{p['name']} is weak on the scorecard",
                        "detail": "; ".join(bad) + ".", "facts": [], "origin": "rule"})
    for d in (fund.get("intelligence") or {}).get("divergences", []):
        if d["severity"] == "high":
            out.append({"category": "financial", "severity": "high", "title": d["text"], "detail": d["evidence"] + ".", "facts": [], "origin": "rule"})
    return out
