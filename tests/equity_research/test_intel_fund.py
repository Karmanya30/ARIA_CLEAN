"""Mutual-fund analysis: known-answer maths, scheme picking, the report and its disclosure page, API round trip. No network."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from test_intel_store_api import owner  # noqa: F401  (fixture)

from api.main import app
from core.router import is_research_report_query
from modules.equity_research.intelligence import fund
from modules.equity_research.intelligence.report_html import render_html  # noqa: F401
from shared import user_store

client = TestClient(app)


def series(years=8, daily=0.0004, start=date(2018, 1, 1)):
    dates = [start + timedelta(days=i) for i in range(int(years * 365))]
    return dates, [10 * (1 + daily) ** i for i in range(len(dates))]


def payload(dates, vals):
    return {"meta": {"scheme_code": 999, "scheme_name": "Test Flexi Cap Fund - Direct Plan - Growth", "fund_house": "Test AMC", "scheme_category": "Equity Scheme - Flexi Cap Fund", "scheme_type": "Open Ended"},
            "data": [{"date": d.strftime("%d-%m-%Y"), "nav": f"{v:.4f}"} for d, v in reversed(list(zip(dates, vals)))]}


def test_xirr_cagr_drawdown_known_answers():
    d0 = date(2020, 1, 1)
    assert fund.xirr([(d0, -100), (date(2021, 1, 1), 110)]) == pytest.approx(0.10, abs=0.002)
    assert fund.xirr([(d0, 100), (date(2021, 1, 1), 110)]) is None  # no outflow: undefined
    dates = [date(2020, 1, 1), date(2023, 1, 1)]
    assert fund.cagr(dates, [100, 200], 3) == pytest.approx(2 ** (1 / 3) - 1) and fund.cagr(dates, [100, 200], 5) is None
    assert fund.max_drawdown([100, 50, 75, 60]) == pytest.approx(-0.5)


def test_flat_nav_sip_has_zero_return_and_growing_nav_positive():
    dates, _ = series(4)
    flat = fund.sip(dates, [10.0] * len(dates), 3)
    assert flat["xirr"] == pytest.approx(0.0, abs=1e-6) and flat["installments"] == 36 and flat["invested"] == 360_000
    grow = fund.sip(dates, series(4)[1], 3)
    assert grow["xirr"] > 0.1 and grow["value"] > grow["invested"]
    assert fund.sip(dates, [10.0] * len(dates), 10) is None  # not enough history


def test_calendar_rolling_and_risk_on_a_smooth_series():
    dates, vals = series()
    cal = fund.calendar_years(dates, vals)
    assert all(v > 0 for _, v in cal) and cal[-1][0] == dates[-1].year
    r = fund.rolling(dates, vals)
    assert r["min"] == pytest.approx(r["max"], abs=0.01)  # constant growth: every window alike
    risk = fund.risk_stats(dates, vals, 0.0675)
    assert risk["volatility"] == pytest.approx(0.0, abs=1e-9) and risk["window_years"] == 3


def test_scheme_picking_and_name_extraction():
    res = [{"schemeCode": 1, "schemeName": "Alpha Fund - Regular Plan - Growth"}, {"schemeCode": 2, "schemeName": "Alpha Fund - Direct Plan - IDCW"},
           {"schemeCode": 3, "schemeName": "Alpha Fund - Direct Plan - Growth"}]
    assert fund.pick_scheme(res, "alpha fund")["schemeCode"] == 3
    assert fund.pick_scheme(res, "alpha fund regular")["schemeCode"] == 1
    assert fund.pick_scheme(res, "alpha fund dividend")["schemeCode"] == 2
    assert fund.fund_name_from("Give me a mutual fund analysis of Parag Parikh Flexi Cap") == "Parag Parikh Flexi Cap"
    assert fund.is_fund_query("fund analysis of X") and not fund.is_fund_query("best mutual fund to invest")
    assert is_research_report_query("mutual fund analysis of Quant Small Cap", None) and not is_research_report_query("which mutual fund should i buy", None)


def test_report_html_and_markdown_are_honest_about_scope():
    dates, vals = series()
    bench = series(daily=0.0002)
    rep = fund.build_fund_report(payload(dates, vals), bench, today=date(2026, 1, 1))
    f = rep["fund"]
    assert f["returns"][0]["excess"] > 0 and f["beta_alpha"]["months"] >= 24 and rep["stance"]["rating"] is None
    html = fund.render_fund_html(rep)
    for needle in ("Mutual fund analysis", "Returns vs benchmark", "SIP outcomes", "Important disclosures", "No language model wrote any part", "subject to market risks",
                   "Portfolio holdings", "Expense ratio", "does not rate or rank funds"):
        assert needle in html, needle
    assert "Undervalued if fair value" not in html and "fair value" not in html.split("Important disclosures")[1].lower().split("<h3>5.")[0]
    assert "Returns (CAGR)" in rep["markdown"] and "Insight:" in fund.summary_text(f)
    with pytest.raises(ValueError):
        fund.build_fund_report(payload(dates[:10], vals[:10]), None)
    assert "unavailable" in fund.render_fund_html(fund.build_fund_report(payload(dates, vals), None))
    assert "1-year return" in html and "1 year<" in html and "1 years" not in html
    mid = fund.render_fund_html(fund.build_fund_report(payload(*series(years=7.5)), None))
    assert " YTD" in mid and "2025 YTD" in mid


def test_fund_report_saves_lists_downloads_and_cannot_be_regenerated(owner):
    dates, vals = series()
    rep = fund.build_fund_report(payload(dates, vals), None, today=date(2026, 1, 1))
    meta = user_store.save_research_report(owner, rep)
    p = {"owner_id": owner}
    assert user_store.list_research_reports(owner)[0]["stance"] == "Not rated" and meta["version"] == 1 and meta["kind"] == "fund_analysis"
    html = client.get(f"/api/research/reports/{meta['id']}/html", params=p).text
    assert "Test Flexi Cap Fund" in html and "window.print" not in html
    d = client.get(f"/api/research/reports/{meta['id']}/download", params={**p, "format": "html"})
    assert d.status_code == 200 and "_fund_analysis_v1_" in d.headers["content-disposition"] and "Save as PDF" in d.text
    assert client.post(f"/api/research/reports/{meta['id']}/regenerate", json=p).status_code == 400
