"""Ownership history and pledge, Altman Z, peer benchmarking, management, the LBO cross-check and fund category ranks.
Known answers on the offline fixtures; no network."""
import pytest
from _intel_fixtures import QUARTERS, good_llm, make_snapshot, operating_info, operating_raw

from modules.equity_research.intelligence import agents, fund, pipeline as intel
from modules.equity_research.intelligence.analysis import analyze
from modules.equity_research.intelligence.data import Peer, Target
from modules.equity_research.intelligence.facts import Ledger
from modules.equity_research.intelligence.report_html import render_html
from modules.equity_research.intelligence.valuation import LBO_TARGET_IRR, LBO_YEARS, DCFInputs, dcf, fade, lbo


def _raw_with_shareholding(promoters=(55.0,) * 9 + (54.0, 53.5, 52.5, 52.0), pledged=None):
    shp = {"__columns__": QUARTERS, "Promoters": {q: f"{v:.2f}%" for q, v in zip(QUARTERS, promoters)},
           "FIIs": {q: "20.00%" for q in QUARTERS}, "DIIs": {q: "15.00%" for q in QUARTERS}, "Public": {q: "10.00%" for q in QUARTERS}}
    return {**operating_raw(), "shareholding": shp, "pledged_pct": pledged}


def _report(snap):
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(intel, "_persist", lambda user_id, report: None)
        mp.setattr(intel, "resolve_target", lambda q: Target("T", "T.NS", "T"))
        mp.setattr(intel, "gather", lambda t: snap)
        mp.setattr(agents, "generate_response", good_llm())
        return intel.run_research("report")["report"]
    finally:
        mp.undo()


# Yahoo balance sheet matching the fixture's FY2026 screener figures (total assets 2,700 Cr).
YF_BS = {"as_of": "2026-03-31", "rows": {"Total Assets": 2700e7, "Working Capital": 500e7, "Retained Earnings": 1200e7,
                                         "Total Liabilities Net Minority Interest": 1200e7, "Minority Interest": 50e7}}


def test_shareholding_history_pledge_and_promoter_trend_are_facts_flags_and_shown():
    snap = make_snapshot(raw=_raw_with_shareholding(pledged=62.5))
    an = analyze(snap, Ledger())
    assert an.facts["promoters_holding"].value == 52.0 and an.facts["promoters_change"].value == pytest.approx(-3.0)
    assert an.facts["pledged"].value == 62.5
    flags = {r.title: r.severity for r in an.risks}
    assert flags["Promoter shares pledged"] == "high" and "Promoter holding falling" in flags
    rep = _report(snap)
    html = render_html(rep)
    company = html[html.index("Company overview"): html.index("Industry and competitive position")]
    assert "Shareholding pattern" in company and "pledged 62.5%" in company and "promoters -3.00pp" in company
    assert "Shareholding pattern" not in html[html.index("</span>Financial analysis"): html.index("</span>Ratio analysis")]
    assert "Shareholding history" not in {x["item"] for x in rep["not_available"]}
    quiet = render_html(_report(make_snapshot(raw=_raw_with_shareholding(promoters=(55.0,) * 13))))
    assert "No promoter pledge is flagged" in quiet and "Promoter holding falling" not in quiet


def test_altman_z_known_answer_and_refusals():
    snap = make_snapshot()
    snap.yf_statements = YF_BS
    an = analyze(snap, Ledger())
    ebit, sales = an.series["ebit"]["Mar 2026"], an.series["revenue"]["Mar 2026"]
    want = 1.2 * 500 / 2700 + 1.4 * 1200 / 2700 + 3.3 * ebit / 2700 + 0.6 * an.facts["market_cap"].value / 1200 + sales / 2700
    z = an.facts["altman_z"]
    assert z.value == pytest.approx(want) and z.method.startswith("safe zone") and "Altman Z-score" not in an.unavailable
    snap.yf_statements = {**YF_BS, "rows": {**YF_BS["rows"], "Total Assets": 5000e7}}  # different basis or currency: never mixed
    assert "altman_z" not in analyze(snap, Ledger()).facts and "disagree" in analyze(snap, Ledger()).unavailable["Altman Z-score"]
    weak = make_snapshot(info=operating_info(marketCap=100e7))
    weak.yf_statements = {**YF_BS, "rows": {**YF_BS["rows"], "Working Capital": -500e7, "Retained Earnings": -1000e7}}
    an = analyze(weak, Ledger())
    assert an.facts["altman_z"].value < 1.81 and "Altman Z-score in the distress zone" in {r.title for r in an.risks}
    bank = make_snapshot("bank")
    bank.yf_statements = YF_BS
    assert "altman_z" not in analyze(bank, Ledger()).facts  # not meaningful for a lender


def test_company_is_benchmarked_against_its_peers_with_a_peer_set_revenue_share():
    peers = [Peer("P1", "Peer One", 20, 3, 12, mcap_cr=20000, revenue_cr=3000, op_margin=0.25, roe=0.2),
             Peer("P2", "Peer Two", 22, 4, 14, mcap_cr=9000, revenue_cr=1000, op_margin=0.15, roe=0.1),
             Peer("P3", "Peer Three", 24, 5, 16, mcap_cr=5000, revenue_cr=None, op_margin=0.30, roe=0.3)]
    snap = make_snapshot(info=operating_info(totalRevenue=2000e7, operatingMargins=0.20, returnOnEquity=0.18), peer_list=peers)
    an = analyze(snap, Ledger())
    cp = an.competitive
    assert cp["rows"][0]["subject"] and cp["revenue_share"] == pytest.approx(2000 / 6000)
    assert cp["ranks"]["revenue_cr"] == {"rank": 2, "of": 3} and cp["ranks"]["op_margin"] == {"rank": 3, "of": 4}
    assert an.facts["peer_rev_share"].value == pytest.approx(100 / 3) and "not an industry market share" in an.facts["peer_rev_share"].method
    html = render_html(_report(snap))
    assert "Competitive position vs listed peers" in html and "<b>Testco Limited</b>" in html and "the 2 of 3 peers with revenue data" in html
    assert "No comparable peer set" not in html


def test_management_table_shows_pay_only_in_rupees():
    officers = [{"name": "Ms.  A   Founder", "title": "MD &  CEO", "age": 58, "totalPay": 281130000, "fiscalYear": 2026}]
    rep = _report(make_snapshot(info=operating_info(companyOfficers=officers, currency="INR")))
    m = rep["cover"]["management"][0]
    assert m["name"] == "Ms. A Founder" and m["pay_cr"] == pytest.approx(28.113) and "₹28.1 Cr (FY2026)" in render_html(rep)
    usd = _report(make_snapshot(info=operating_info(companyOfficers=officers, currency="INR", financialCurrency="USD")))
    assert usd["cover"]["management"][0]["pay_cr"] is None


def _irr(inp, res, out):
    """Independent re-computation of the sponsor's return at the entry value ``lbo`` reports."""
    ebitda0 = inp.revenue_base * inp.ebitda_margin
    nd = out["leverage"] * ebitda0
    for t in range(LBO_YEARS):
        nd -= res.fcf[t] - max(nd, 0) * out["rate"] * (1 - inp.tax_rate)
    exit_equity = out["entry_multiple"] * res.ebitda[LBO_YEARS - 1] - nd - inp.nci
    return (exit_equity / (out["entry_ev"] - out["leverage"] * ebitda0 - inp.nci)) ** (1 / LBO_YEARS) - 1


def test_lbo_entry_price_earns_exactly_the_hurdle_and_is_never_blended():
    inp = DCFInputs(1000, fade(0.10, 0.05), 0.22, 0.04, 0.06, 0.1, 0.25, 0.12, 0.05, 300, 50, 100)
    res = dcf(inp)
    out = lbo(inp, res, 0.0975)
    assert out["per_share"] > 0 and _irr(inp, res, out) == pytest.approx(LBO_TARGET_IRR)
    assert out["per_share"] == pytest.approx((out["entry_ev"] - inp.net_debt - inp.nci) / inp.shares_cr)
    hot = DCFInputs(1000, fade(0.25, 0.05), 0.22, 0.04, 0.06, 0.1, 0.25, 0.12, 0.05, 300, 50, 100)
    assert lbo(hot, dcf(hot), 0.0975)["per_share"] is None and "hurdle" in lbo(hot, dcf(hot), 0.0975)["reason"]
    rep = _report(make_snapshot())
    assert "LBO cross-check" in render_html(rep) and "lbo" not in {m["key"] for m in rep["valuation"]["methods"]}


AMFI = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

101;INF1;-;Alpha Flexi Cap Fund;Direct Plan;Growth;10.0;29-Sep-2026
102;INF2;INF3;Alpha Flexi Cap Fund;Direct Plan;IDCW;10.0;29-Sep-2026
103;INF4;-;Alpha Flexi Cap Fund;Regular Plan;Growth;10.0;29-Sep-2026
Open Ended Schemes(Debt Scheme - Liquid Fund)
201;INF5;-;Beta Liquid Fund - Direct Plan - Growth;1000.0;29-Sep-2026
"""


def test_amfi_file_parses_by_category_and_ranks_are_known_answers():
    cats = fund.parse_amfi(AMFI)
    flexi = cats["equity scheme - flexi cap fund"]
    assert [(s["code"], s["direct"], s["growth"]) for s in flexi] == [(101, True, True), (102, True, False), (103, False, True)]
    assert cats["debt scheme - liquid fund"][0]["direct"] and cats["debt scheme - liquid fund"][0]["growth"]  # 6-field row: plan read from the name
    assert flexi[0]["name"] == "Alpha Flexi Cap Fund - Direct Plan - Growth"
    peers = [{1: r, 3: r} for r in (0.30, 0.20, 0.10, 0.05, 0.00)]
    ranks = {x["years"]: x for x in fund.rank_in_category({1: 0.20, 3: None}, peers)}
    assert set(ranks) == {1} and ranks[1]["rank"] == 2 and ranks[1]["of"] == 5 and ranks[1]["quartile"] == 1 and ranks[1]["median"] == 0.10


def test_scheme_lookup_uses_the_full_active_list_and_skips_legacy_plans(monkeypatch):
    listing = {"debt scheme - liquid fund": [
        {"code": 1, "name": "Gamma Liquid Fund-PREMIUM PLUS- Growth"}, {"code": 2, "name": "Gamma Liquid Fund - Regular Plan - Growth Option"},
        {"code": 3, "name": "Gamma Liquid Fund - Direct Plan - IDCW Daily"}, {"code": 4, "name": "Gamma Liquid Fund - Direct Plan - Growth Option"}]}
    monkeypatch.setattr(fund, "_amfi_schemes", lambda: listing)
    assert fund.find_scheme("Gamma Liquid Fund", "analysis of gamma liquid fund")["schemeCode"] == 4
    assert fund.find_scheme("Gamma Liquid", "gamma liquid regular")["schemeCode"] == 2  # a named Regular plan beats a legacy one


def test_unit_restructuring_is_not_a_return_and_liquid_funds_annualise_by_calendar_days():
    from test_intel_fund import payload, series

    dates, vals = series(years=6, daily=0.00018)  # every calendar day, ~6.8% a year, like a liquid fund
    cut = len(dates) // 2
    rep = fund.build_fund_report(payload(dates, [v * (100 if i >= cut else 1) for i, v in enumerate(vals)]), None)
    f = rep["fund"]
    assert f["since_inception"] == pytest.approx(1.00018 ** 365.25 - 1, abs=0.002) and f["max_drawdown"] > -0.001
    assert f["nav_adjustments"][0]["date"] == dates[cut].isoformat() and "unit restructuring" in fund.render_fund_html(rep)
    stats = fund.risk_stats(dates, [v * (1 + (0.0001 if i % 2 else -0.0001)) for i, v in enumerate(vals)], 0.06)
    assert stats["sharpe"] > 0 and stats["volatility"] < 0.01  # 6.6% a year beats a 6% risk-free rate only when annualised over 365 NAV days, not 252


def test_fund_report_shows_category_rank_and_the_right_benchmark():
    from test_intel_fund import payload, series

    dates, vals = series()
    others = [{1: g, 3: g, 5: g} for g in (0.5, 0.4, 0.01, 0.0)]
    mine = {n: fund.cagr(*fund.parse_nav(payload(dates, vals)), n) for n in (1, 3, 5)}  # as category_peers computes it: from the published NAVs
    cat = {"category": "Equity Scheme - Flexi Cap Fund", "plan": "Direct", "n_schemes": 5, "peers": [mine, *others]}
    rep = fund.build_fund_report(payload(dates, vals), series(daily=0.0002), bench_label=fund.TRI_PROXY, category=cat)
    html = fund.render_fund_html(rep)
    assert "Category comparison" in html and "3 of 5" in html and "total-return proxy" in html
    items = {x["item"] for x in rep["not_available"]}
    assert "Total-return benchmark (TRI)" not in items and "Category ranking" not in items and "Star ratings" in items
    assert "ranks 3 of 5 in its category" in fund.summary_text(rep["fund"])
    debt = fund.build_fund_report(payload(dates, vals), None, no_bench_reason="an equity index is not a meaningful benchmark for a debt fund",
                                  category={"skipped": "Fewer than five comparable schemes in the category."})
    dh = fund.render_fund_html(debt)
    assert "not used: an equity index is not a meaningful benchmark" in dh and "Category comparison" not in dh
    assert {"Category ranking"} <= {x["item"] for x in debt["not_available"]}
