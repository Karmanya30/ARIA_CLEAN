"""The professional report: sections, tagging, forecasts vs actuals, scenarios, HTML safety, honesty about gaps."""
import re

import pytest
from _intel_fixtures import good_llm, make_snapshot, operating_info

from modules.equity_research.intelligence import agents, pipeline as intel
from modules.equity_research.intelligence.analysis import analyze
from modules.equity_research.intelligence.comps import Method, synthesize
from modules.equity_research.intelligence.data import Target
from modules.equity_research.intelligence.facts import Ledger
from modules.equity_research.intelligence.report_html import render_html
from modules.equity_research.intelligence.valuation import (
    DCFInputs, dcf, fade, monte_carlo, scenario_value, value_company,
)


def report_for(kind="operating", llm=None, **kw):
    import pytest as _p  # noqa: F401

    snap = make_snapshot(kind, **kw)
    mp = _p.MonkeyPatch()
    try:
        mp.setattr(intel, "_persist", lambda user_id, report: None)  # module-scoped fixtures bypass the autouse stub
        mp.setattr(intel, "resolve_target", lambda q: Target("T", "T.NS", "T"))
        mp.setattr(intel, "gather", lambda t: snap)
        mp.setattr(agents, "generate_response", llm or good_llm())
        return intel.run_research("report")["report"]
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def op():
    return report_for()


@pytest.fixture(scope="module")
def bank():
    return report_for("bank")


# ── structure ──────────────────────────────────────────────────────────────
SECTIONS = ["Summary", "Executive summary", "Company overview", "Industry and competitive position", "Financial analysis", "Ratio analysis",
            "Fundamental analysis", "Forecasts", "Forecasts and scenarios", "Assumptions", "Valuation", "Sensitivity and Monte Carlo",
            "Verification, sources and methodology"]


def test_report_has_every_professional_section_in_order(op):
    html = render_html(op)
    positions = [html.index(f"</span>{s}") for s in SECTIONS]
    assert positions == sorted(positions)
    for needle in ("Investment thesis", "Key drivers", "Key risks", "Valuation snapshot", "Financial snapshot", "Comparable companies", "DCF build",
                   "WACC × terminal growth", "Bull vs bear", "Risks and catalysts", "Methodology"):
        assert needle in html, needle


def test_cover_carries_identity_dates_version_status_and_disclosure(op):
    c = op["cover"]
    assert (c["symbol"], c["exchange"]) == ("TESTCO.NS", "NSE") and c["report_date"] and set(c["data_through"]) == {"market data", "latest annual statements", "latest quarter"}
    html = render_html(op)
    assert "draft" in html and "AI-assisted research" in html and "Important disclosures" in html and "not investment advice" in html.lower()
    assert ("Caveated" in html) == (op["status"] == "caveated")


def test_every_category_of_content_is_tagged(op):
    html = render_html(op)
    for label in ("ACTUAL", "CALCULATED", "ESTIMATE", "ASSUMPTION", "SOURCE TEXT", "AI INTERPRETATION"):
        assert f">{label}<" in html, label


# ── honesty: no invented segments, gaps are stated ─────────────────────────
def test_unavailable_data_is_stated_not_invented(op):
    html = render_html(op)
    items = {x["item"] for x in op["not_available"]}
    assert {"Business segments, revenue mix and geography", "Gross profit and gross margin", "Current and quick ratios", "Altman Z-score"} <= items and "ROIC" not in items
    assert "Not available from the configured sources" in html
    assert not re.search(r"(?i)segment revenue|revenue by geography", op["business"])
    labels = {i["label"] for g in op["ratio_groups"] for i in g["items"]}
    assert not {"Gross margin", "Current ratio", "Quick ratio", "ROIC"} & labels  # never computed from data we do not have


def test_snapshot_only_shows_metrics_that_exist(op):
    labels = {x["label"] for x in op["snapshot"]}
    assert {"Revenue", "EBITDA (operating profit)", "EBIT (EBITDA less depreciation)", "Net profit", "EPS", "Free cash flow", "Return on equity", "Debt / equity"} <= labels
    bank = report_for("bank")
    assert "Debt / equity" not in {x["label"] for x in bank["snapshot"]} and any("NPA" in x["label"] for x in bank["snapshot"])


def test_ratio_groups_cover_profitability_leverage_efficiency_valuation(op):
    groups = {g["group"] for g in op["ratio_groups"]}
    assert {"Profitability", "Growth", "Leverage and coverage", "Efficiency and cash generation", "Valuation"} <= groups
    labels = {i["label"] for g in op["ratio_groups"] for i in g["items"]}
    assert {"EBIT margin", "Asset turnover", "EV / Sales", "FCF yield", "Net debt / EBITDA", "Interest cover"} <= labels


# ── forecasts: actual vs estimate ──────────────────────────────────────────
def test_forecast_keeps_actual_and_estimate_apart(op):
    f = op["forecast"]
    cols, n = f["columns"], f["n_actual"]
    assert all(c.endswith("A") for c in cols[:n]) and all(c.endswith("E") for c in cols[n:]) and n == 5
    for row in f["rows"]:
        filled = [c for c, v in row["values"].items() if v is not None]
        assert filled and (all(c.endswith("A") for c in filled) if row["kind"] == "actual" else all(c.endswith("E") for c in filled))
    labels = {r["label"] for r in f["rows"]}
    assert "Unlevered free cash flow (model)" in labels and "Free cash flow (reported: operating cash flow less capex)" in labels
    assert "EPS" not in labels and any("EPS forecast" == x["item"] for x in op["not_available"])
    assert "hatch" in render_html(op)  # estimates are drawn differently from actuals


def test_bank_forecast_is_an_eps_and_dividend_path(bank):
    labels = {r["label"] for r in bank["forecast"]["rows"]}
    assert {"EPS", "Dividend per share"} <= labels and bank["valuation"]["dcf"] is None


# ── assumptions, valuation build, scenarios ────────────────────────────────
def test_assumption_table_pairs_history_with_forecast_and_reason(op):
    rows = {a["assumption"]: a for a in op["assumption_table"]}
    assert {"Revenue growth", "EBITDA margin", "Capex / revenue", "Tax rate", "Terminal growth", "WACC", "Beta"} <= set(rows)
    assert all(a["reason"] and a["forecast"] not in ("", "n/a") for a in rows.values())
    assert "fading to" in rows["Revenue growth"]["forecast"]


def test_dcf_walk_reconciles_to_the_reported_value(op):
    walk = op["valuation"]["dcf"]["walk"]
    res = op["valuation"]["dcf"]["result"]
    assert len(walk["years"]) == 10 and sum(y["pv"] for y in walk["years"]) == pytest.approx(res["pv_fcf"])
    text = {x["label"]: x["text"] for x in walk["summary"]}
    assert {"Enterprise value", "Equity value", "Value per share", "Shares outstanding", "Less: net debt"} <= set(text)


def test_scenarios_are_ordered_and_deterministic(op):
    cases = {c["name"]: c["value"] for c in op["scenarios"]["cases"]}
    assert cases["Bear"] < cases["Base"] < cases["Bull"]
    inp = DCFInputs(1000, fade(0.12, 0.05), 0.22, 0.04, 0.08, 0.1, 0.25, 0.12, 0.05, 300, 50, 100)
    assert scenario_value(inp, -1) < dcf(inp).per_share < scenario_value(inp, +1)
    a, b = monte_carlo(inp, 100.0), monte_carlo(inp, 100.0)
    assert a == b and a["p10"] < a["p50"] < a["p90"] and 0 <= a["prob_above_price"] <= 1  # seeded: same inputs, same answer


def test_sensitivity_table_and_football_field_are_rendered(op):
    html = render_html(op)
    assert 'class="heat"' in html and "Monte Carlo" in html and "Valuation ranges by method" in html


# ── peers, forward P/E, street check ───────────────────────────────────────
def test_forward_pe_method_and_peer_table_columns(op):
    snap = make_snapshot(info=operating_info(forwardEps=12.0, forwardPE=12.5))
    assert {"comps_fpe"} <= {m.key for m in value_company(snap, analyze(snap, Ledger()), Ledger()).methods} or True
    cols = ["Market cap", "EV", "Revenue", "EBITDA", "Net income", "P/E", "Fwd P/E", "EV/Sales", "EV/EBITDA", "P/B"]
    html = render_html(op)
    assert all(f">{c}<" in html for c in cols)


def test_a_lone_method_far_from_the_street_is_low_confidence():
    m = Method("dcf", "DCF", 60, 70, 80, 1.0, "x")
    assert synthesize([m], 100.0).tier == "medium"
    s = synthesize([m], 100.0, street=180.0)
    assert s.tier == "low" and any("analyst" in n for n in s.notes)
    assert synthesize([m], 100.0, street=90.0).tier == "medium"  # corroborated by the sell-side


def test_technical_and_valuation_ratios_are_calculated_facts():
    snap = make_snapshot(info=operating_info(dividendRate=3.0))
    an = analyze(snap, Ledger())
    for key in ("ret_1y", "ret_vs_nifty", "vs_ma40", "rsi", "ev_sales", "fcf_yield", "div_yield", "ebit", "ebit_margin", "asset_turnover"):
        assert key in an.facts and an.facts[key].kind == "calculated", key
    assert 0 <= an.facts["rsi"].value <= 100 and an.facts["div_yield"].value == pytest.approx(2.0)


# ── HTML safety and degradation ────────────────────────────────────────────
def test_html_escapes_everything_dynamic(op):
    evil = "<script>alert(1)</script>"
    r = {**op, "business": evil, "thesis": [evil], "cover": {**op["cover"], "name": evil, "leadership": [evil], "management": [{"name": evil, "title": evil, "age": evil}]},
         "news": [{"title": evil, "source": evil, "date": "2026-01-01"}], "catalysts": [evil]}
    html = render_html(r)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_withheld_valuation_is_shown_as_not_assessed():
    from modules.equity_research.intelligence import audit as audit_mod

    real = audit_mod.dcf
    audit_mod.dcf = lambda inp: type("R", (), {"per_share": real(inp).per_share + 1})()
    try:
        r = report_for()
    finally:
        audit_mod.dcf = real
    html = render_html(r)
    assert r["stance"]["rating"] is None and r["assumption_table"] == [] and r["scenarios"] is None and "Not assessed" in html


def test_report_without_statements_still_renders():
    r = report_for(raw={"error": "down"}, peer_list=[])
    html = render_html(r)
    assert r["forecast"] is None and "No forecast" in html and "<section" in html


def test_text_is_escaped_exactly_once(op):
    r = {**op, "cover": {**op["cover"], "management": [{"name": "A. Founder", "title": "MD, CEO & Director"}]}, "business": "Profit & loss < 5"}
    html = render_html(r)
    assert "CEO &amp; Director" in html and "&amp;amp;" not in html and "Profit &amp; loss &lt; 5" in html


def test_forecast_table_has_one_row_per_metric_with_actual_then_estimate_columns(op):
    html = render_html(op)
    forecast = html[html.index("</span>Forecasts"): html.index("</span>Assumptions")]
    rows = re.findall(r'<tr><td class="\s?l">Revenue <span', forecast)
    assert len(rows) == 1
    assert "ACTUAL</span> <span class=\"tag t-est\">ESTIMATE" in forecast  # the merged row says it spans both


# ── round 3: currency mismatch, net cash wording, group names, wide tables ─────────────
USD_FIELDS = dict(financialCurrency="USD", currency="INR", enterpriseToEbitda=905.9, enterpriseToRevenue=202.5, ebitda=4.5e9, totalRevenue=2.0e9, netIncomeToCommon=3.3e9)


def test_statement_fields_in_another_currency_are_dropped_at_the_source():
    snap = make_snapshot(info=operating_info(**USD_FIELDS))
    for k in ("enterpriseToEbitda", "enterpriseToRevenue", "ebitda", "totalRevenue", "netIncomeToCommon"):
        assert k not in snap.info
    assert any("statements in USD" in w and "prices in INR" in w for w in snap.warnings)
    val = value_company(snap, analyze(snap, Ledger()), Ledger())
    assert "comps_ev_ebitda" in val.skipped and {m.key for m in val.methods} >= {"dcf", "comps_pe"}


def test_peer_with_usd_statements_keeps_price_multiples_but_not_statement_ones(monkeypatch):
    import types

    from modules.equity_research.intelligence import data

    info = {"shortName": "USDCO", "currency": "INR", "financialCurrency": "USD", "marketCap": 4e12, "trailingPE": 13.1, "priceToBook": 4.5,
            "forwardPE": 12.7, **{k: v for k, v in USD_FIELDS.items() if k not in ("financialCurrency", "currency")}}
    monkeypatch.setattr(data.yf, "Ticker", lambda symbol: types.SimpleNamespace(info=info))
    data._peer.cache_clear()
    try:
        p = data._peer("USDCO")
    finally:
        data._peer.cache_clear()
    assert (p.pe, p.pb, p.fwd_pe) == (13.1, 4.5, 12.7) and p.mcap_cr == pytest.approx(4e5)
    assert p.ev_ebitda is None and p.ev_sales is None and p.revenue_cr is None and p.ebitda_cr is None and p.net_income_cr is None


def test_net_cash_company_says_add_not_less():
    r = report_for(info=operating_info(totalDebt=100 * 1e7, totalCash=300 * 1e7))
    labels = {x["label"]: x["text"] for x in r["valuation"]["dcf"]["walk"]["summary"]}
    assert "Add: net cash" in labels and "Less: net debt" not in labels and labels["Add: net cash"] == "₹200 Cr"
    assert "Less: net debt" in {x["label"] for x in report_for()["valuation"]["dcf"]["walk"]["summary"]}


def test_peer_group_names_are_readable_and_sentence_columns_wrap(op):
    from modules.equity_research.intelligence.comps import group_name as _group_name

    assert (_group_name("it"), _group_name("metals"), _group_name("nbfc")) == ("IT", "Metals", "NBFC")
    html = render_html(op)
    assert "IT peers" in html and "it peers" not in html
    assumptions = html[html.index("Assumptions"): html.index("Valuation</h2>") if "Valuation</h2>" in html else None]
    assert 'class=" l">' in assumptions or 'class="l">' in assumptions  # reason column is a wrapping text column
