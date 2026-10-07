"""Systematic scenarios (every case worked line by line) and the fundamental-analysis section."""
import pytest
from test_intel_report_html import report_for

from modules.equity_research.intelligence.fundamentals import news_signals
from modules.equity_research.intelligence.report_html import render_html
from modules.equity_research.intelligence.valuation import (
    SCENARIO_WEIGHTS, DCFInputs, DDMInputs, ddm, ddm_scenario_detail, ddm_scenario_value, dcf, fade, residual_income,
    scenario_detail, scenario_value, weighted_value,
)

INP = DCFInputs(revenue_base=10_000, growth=fade(0.12, 0.05), ebitda_margin=0.20, da_pct=0.04, capex_pct=0.06, nwc_pct=0.10,
                tax_rate=0.25, wacc=0.11, terminal_growth=0.05, net_debt=1_000, nci=0, shares_cr=50)


@pytest.fixture(scope="module")
def op():
    return report_for()


@pytest.fixture(scope="module")
def bank():
    return report_for("bank")


def test_the_base_case_table_adds_up_to_the_headline_dcf():
    d, res = scenario_detail(INP, 0), dcf(INP)
    assert sum(d["pv_fcf"]) == pytest.approx(res.pv_fcf)
    assert d["bridge"]["per_share"] == pytest.approx(res.per_share)
    lines = d["lines"]
    for i in range(len(INP.growth)):  # every line follows from the ones above it
        assert lines["ebit"][i] == pytest.approx(lines["ebitda"][i] - lines["da"][i])
        assert lines["fcf"][i] == pytest.approx(lines["nopat"][i] + lines["da"][i] - lines["capex"][i] - lines["nwc_change"][i])
    b = d["bridge"]
    assert b["equity_value"] == pytest.approx(b["enterprise_value"] - b["net_debt"] - b["nci"])


def test_each_case_table_matches_its_scenario_value_and_the_weighted_value_follows_the_weights():
    vals = {n: scenario_detail(INP, d)["bridge"]["per_share"] for n, d in (("bear", -1), ("base", 0), ("bull", 1))}
    assert vals["bear"] == pytest.approx(scenario_value(INP, -1)) and vals["bull"] == pytest.approx(scenario_value(INP, 1))
    assert vals["bear"] < vals["base"] < vals["bull"]
    assert weighted_value(vals) == pytest.approx(sum(SCENARIO_WEIGHTS[k] * v for k, v in vals.items()))
    assert weighted_value({**vals, "bull": None}) is None  # never a weighted value over a missing case


def test_a_refused_case_says_why_instead_of_inventing_numbers():
    tight = DCFInputs(**{**INP.__dict__, "wacc": 0.065, "terminal_growth": 0.05})  # bull: WACC 5.5% vs terminal growth 5.5%
    assert "reason" in scenario_detail(tight, 1)


def test_ddm_cases_are_worked_the_same_way():
    inp = DDMInputs(eps0=50, payout=0.25, growth=fade(0.14, 0.05), coe=0.13, terminal_growth=0.05, terminal_roe=0.15)
    d = ddm_scenario_detail(inp, 0)
    assert d["bridge"]["per_share"] == pytest.approx(ddm(inp).per_share)
    assert ddm_scenario_detail(inp, -1)["bridge"]["per_share"] == pytest.approx(ddm_scenario_value(inp, -1))
    assert sum(d["pv_dps"]) == pytest.approx(d["bridge"]["sum_pv_dividends"])


def test_residual_income_is_book_value_when_returns_equal_the_cost_of_equity():
    assert residual_income(100, 0.12, 0.12, 0.3)["per_share"] == pytest.approx(100)
    rich = residual_income(100, 0.20, 0.12, 0.3)
    assert rich["per_share"] > 100 and rich["rows"][-1]["roe"] == pytest.approx(0.12)  # excess return fades to nothing by year 10
    assert residual_income(100, 0.08, 0.12, 0.3)["per_share"] < 100  # value-destroying returns are worth less than book


def test_headlines_are_sorted_into_fundamental_themes_with_a_direction():
    s = news_signals([{"title": "Acme bags Rs 2,000 crore order from NHAI", "source": "ET", "date": "2026-10-01"},
                      {"title": "Acme to commission new plant in Gujarat", "source": "Mint", "date": "2026-09-30"},
                      {"title": "SEBI imposes penalty on Acme promoters", "source": "BS", "date": "2026-09-29"},
                      {"title": "Acme Q2 net profit falls 12%", "source": "BL", "date": "2026-09-28"}])
    got = [(i["category"], i["direction"]) for i in s["items"]]
    assert got == [("Orders and contracts", "positive"), ("Capacity and capex", "neutral"), ("Regulatory and legal", "negative"), ("Results", "negative")]
    assert s["summary"]["Results"]["negative"] == 1
    mixed = news_signals([{"title": "Acme rises Tuesday, underperforms competitors", "source": "ET", "date": "2026-10-01"}])
    assert mixed["items"][0]["direction"] == "mixed"


def test_the_report_works_every_case_through_and_adds_fundamental_analysis(op):
    sc = op["scenarios"]
    assert [c["key"] for c in sc["cases"]] == ["bear", "base", "bull"] and sc["weighted"] is not None
    assert sc["history"]["columns"][-1].endswith("A") and all("lines" in c["detail"] for c in sc["cases"])
    f = op["fundamentals"]
    assert f["available"] and f["piotroski"]["available"] and 0 <= f["piotroski"]["score"] <= f["piotroski"]["tested"]
    assert f["growth_check"]["available"] and f["residual_income"]["available"]
    html = render_html(op)
    for needle in ("Forecasts and scenarios", "Scenarios side by side", "Bear case:", "Bull case:", "Bridge to value per share",
                   "Probability-weighted value", "Fundamental analysis", "Piotroski F-score", "Fundamental growth", "Residual income model, year by year"):
        assert needle in html, needle
    ids = {f_["id"] for f_ in op["facts"]}
    assert f["piotroski"]["fact"] in ids and f["residual_income"]["fact"] in ids  # every new figure is on the audited ledger


def test_a_bank_gets_ddm_scenarios_and_lender_appropriate_fundamentals(bank):
    assert bank["scenarios"]["model"] == "DDM" and all("eps" in c["detail"]["lines"] for c in bank["scenarios"]["cases"] if "lines" in c["detail"])
    f = bank["fundamentals"]
    assert not f["piotroski"]["available"] and "lender" in f["piotroski"]["reason"]  # not built for banks: says so instead of scoring
    assert f["growth_check"]["available"] and "retention" in f["growth_check"]
    assert "Dividend per share" in render_html(bank)


def test_growth_check_is_not_meaningful_when_the_business_released_capital():
    from types import SimpleNamespace as NS

    from modules.equity_research.intelligence import fundamentals
    from modules.equity_research.intelligence.facts import Ledger

    yrs = ["Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"]
    col = lambda v: {y: v for y in yrs}  # noqa: E731
    an = NS(years=yrs, facts={"roic": NS(value=15.0)}, series={
        "ebit": col(100.0), "capex": col(10.0), "dep": col(20.0), "tax_rate": col(0.25), "revenue": col(1000.0),
        "nwc_pct": dict(zip(yrs, (0.10, 0.08, 0.06, 0.04)))})  # working capital falls every year
    ledger = Ledger()
    g = fundamentals._growth_check(NS(is_financial=False), an, NS(dcf_inputs=NS(growth=(0.16,))), ledger)
    assert g["available"] and g["fundamental"] is None and g["reinvestment"] < 0
    assert ledger.find("Fundamental growth") is None
    assert "releasing capital" in g["note"] and "verdict" not in g
