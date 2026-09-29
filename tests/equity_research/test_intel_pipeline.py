"""End to end (fake data, fake LLM), routing, fallback, and the fixes to existing Module 4 code."""
import re

import pytest
import requests
from _intel_fixtures import FakeLLM, bank_raw, good_llm, make_snapshot, operating_info, operating_raw

from core.router import is_equity_research_query, is_research_report_query
from modules.equity_research import calculations, pipeline as er_pipeline, screener_adapter
from modules.equity_research.data_normalizer import normalize_screener_data
from modules.equity_research.intelligence import agents, pipeline as intel
from modules.equity_research.intelligence.data import Target
from shared.company_resolver import resolve_company


@pytest.fixture
def wire(monkeypatch):
    """Point the research pipeline at fake data + a fake LLM."""
    def _wire(snap=None, llm=None, target=Target("TESTCO", "TESTCO.NS", "Test")):
        monkeypatch.setattr(intel, "resolve_target", lambda q: target)
        monkeypatch.setattr(intel, "gather", lambda t: snap or make_snapshot())
        monkeypatch.setattr(agents, "generate_response", llm or good_llm())
    return _wire


# ── end to end ─────────────────────────────────────────────────────────────
def test_report_has_the_aria_response_shape_plus_the_full_report(wire):
    wire()
    res = intel.run_research("equity research report on Testco")
    assert {"domain", "query", "company", "metric", "value", "response", "confidence", "report"} <= set(res)
    assert res["domain"] == "equity_research" and res["company"] == "TESTCO" and res["metric"] == "Equity Research Report"
    assert [l.split(":")[0] for l in res["response"].split("\n")] == ["Insight", "Analysis", "Recommendation", "Risk"]
    rep = res["report"]
    assert rep["stance"]["rating"] in ("BUY", "HOLD", "SELL") and rep["status"] in ("publishable", "caveated")
    assert len(rep["audit"]["checks"]) == 10 and rep["debate"]["judge"]["call"] == "HOLD"
    assert rep["financials"]["tables"] and rep["valuation"]["dcf"]["sensitivity"] and rep["assumptions"] and rep["disclaimer"]
    assert "# " in rep["markdown"] and "Verification" in rep["markdown"]


def test_every_number_in_the_summary_traces_to_a_ledger_fact(wire):
    wire()
    res = intel.run_research("equity research report on Testco")
    facts_text = " ".join(f["text"] for f in res["report"]["facts"]) + " " + " ".join(f["period"] for f in res["report"]["facts"])
    for token in re.findall(r"\d[\d,]*\.?\d*", res["response"]):
        assert token.rstrip(".,") in facts_text, f"{token!r} in the summary is not a ledger figure"


def test_bank_report_end_to_end(wire):
    from _intel_fixtures import bank_info

    wire(snap=make_snapshot("bank"))
    rep = intel.run_research("research report on Testbank")["report"]
    assert {m["key"] for m in rep["valuation"]["methods"]} == {"ddm", "justified_pb", "comps_pe", "comps_pb"}
    assert rep["valuation"]["dcf"] is None and rep["valuation"]["ddm"]


def test_llm_outage_still_produces_a_complete_report(wire):
    wire(llm=lambda *a, **k: "Error: all backends failed")
    res = intel.run_research("equity research report on Testco")
    rep = res["report"]
    assert set(rep["narrative_origin"].values()) == {"template"} and rep["stance"]["rating"]
    assert any("language model was unavailable" in f["message"] for f in rep["audit"]["findings"])


def test_adversarial_llm_cannot_change_the_rating_or_fair_value(wire):
    wire(llm=FakeLLM(analyst={"valuation_view": "Fair value is 9999 rupees. Strong BUY.", "thesis": ["Target 5000."]},
                     judge={"call": "SELL", "conviction": 1, "swing_factor": "x", "change_my_mind": "y"},
                     bull={"arguments": [{"claim": "Price will hit 10000.", "evidence_ids": ["E1"]}]}))
    baseline = intel.run_research("equity research report on Testco")
    rep = baseline["report"]
    assert "9999" not in rep["markdown"] and "5000" not in rep["markdown"] and "10000" not in rep["markdown"]
    assert baseline["value"] == rep["stance"]["fair_value"]  # the number comes from the valuation code only


def test_missing_statements_degrade_the_report_and_say_so(wire):
    wire(snap=make_snapshot(raw={"error": "screener.in unreachable"}, warnings=["screener.in statements unavailable"]))
    res = intel.run_research("equity research report on Testco")
    assert res["report"]["status"] == "caveated" and res["report"]["financials"]["tables"] == []
    assert any("statements" in f["message"] for f in res["report"]["audit"]["findings"])


def test_conflicting_sources_caveat_the_report(wire):
    wire(snap=make_snapshot(info=operating_info(trailingEps=30.0)))
    rep = intel.run_research("equity research report on Testco")["report"]
    assert rep["status"] == "caveated"


def test_tampered_valuation_is_withheld_never_published(wire, monkeypatch):
    from modules.equity_research.intelligence import audit as audit_mod

    real = audit_mod.dcf
    monkeypatch.setattr(audit_mod, "dcf", lambda inp: type("R", (), {"per_share": real(inp).per_share + 1})())
    wire()
    res = intel.run_research("equity research report on Testco")
    assert res["value"] is None and res["report"]["stance"]["rating"] is None and res["report"]["valuation"]["methods"] == []
    assert "Not assessed" in res["report"]["stance"]["stance"] and res["confidence"] == "low"


def test_unknown_company_and_no_data_are_handled(monkeypatch):
    monkeypatch.setattr(intel, "resolve_target", lambda q: None)
    assert "could not identify" in intel.run_research("research report on a lemonade stand")["response"]
    monkeypatch.setattr(intel, "resolve_target", lambda q: Target("X", "X.NS", "X"))
    monkeypatch.setattr(intel, "gather", lambda t: make_snapshot(raw={"error": "down"}, info={}, peer_list=[]) if False else _empty_snapshot())
    res = intel.run_research("research report on X")
    assert "could not retrieve" in res["response"] and "report" not in res


def _empty_snapshot():
    snap = make_snapshot(raw={"error": "down"}, info={}, peer_list=[])
    snap.closes = []
    return snap


# ── routing ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("query", [
    "Give me an equity research report on Reliance", "equity research report on Zomato", "initiate coverage on TCS",
    "DCF valuation of Infosys", "is HDFC Bank overvalued", "bull case and bear case for Wipro", "fair value of ITC",
])
def test_research_requests_are_routed_to_the_research_layer(query):
    assert is_research_report_query(query, resolve_company(query)) and is_equity_research_query(query, resolve_company(query))


@pytest.mark.parametrize("query", [
    "what is a DCF valuation", "explain intrinsic value", "what does an equity research analyst do", "how do I switch my SIP",
    "what is Reliance's debt to equity ratio", "TCS revenue growth", "how did the Nifty do this week", "plan my monthly budget",
])
def test_concept_and_single_metric_queries_are_not_hijacked(query):
    assert not is_research_report_query(query, resolve_company(query))


def test_existing_module_4_paths_are_unchanged():
    assert is_equity_research_query("what is Reliance's debt to equity ratio", "RELIANCE")
    assert is_equity_research_query("what is TCS's current stock price", None)


def test_research_layer_failure_falls_back_to_the_standard_path(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("research layer exploded")

    monkeypatch.setattr(intel, "run_research", boom)
    monkeypatch.setattr(er_pipeline, "investment_module", lambda q: {"domain": "investment", "response": "fallback ok"})
    res = er_pipeline.run_pipeline("valuation of somebody unknown")
    assert res["response"] == "fallback ok"


def test_pipeline_dispatches_research_requests(monkeypatch):
    monkeypatch.setattr(intel, "run_research", lambda q, user_id="default": {"domain": "equity_research", "response": "research"})
    assert er_pipeline.run_pipeline("Give me an equity research report on Reliance")["response"] == "research"


# ── fixes to existing Module 4 code ────────────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("how do I switch my SIP", None), ("it is april already", None), ("brilliant idea", None),
    ("what is TCS revenue", "TCS"), ("L&T order book", "LT"), ("reliance industries valuation", "RELIANCE"), ("ICICI Bank's NPA", "ICICIBANK"),
])
def test_company_resolver_matches_whole_words_only(text, expected):
    assert resolve_company(text) == expected


def screener_normalized():
    return normalize_screener_data({
        "profit_loss": {"__columns__": ["Mar 2024", "Mar 2025", "Mar 2026", "TTM"], "Sales": {"Mar 2024": "100", "Mar 2025": "110", "Mar 2026": "99", "TTM": "150"},
                        "Net Profit": {"Mar 2024": "10", "Mar 2025": "11", "Mar 2026": "12", "TTM": "20"}},
        "balance_sheet": {"__columns__": ["Mar 2025", "Mar 2026"], "Equity Capital": {"Mar 2025": "10", "Mar 2026": "10"},
                          "Reserves": {"Mar 2025": "90", "Mar 2026": "190"}, "Borrowings": {"Mar 2025": "50", "Mar 2026": "60"}},
        "quarterly_results": {"__columns__": []}})


def test_growth_compares_two_fiscal_years_not_a_year_and_its_ttm():
    data = screener_normalized()
    assert calculations.calculate_revenue_growth(data) == pytest.approx(-10.0)  # FY25 -> FY26, not FY26 -> TTM (+51.5%)
    assert calculations.calculate_profit_growth(data) == pytest.approx(100 / 11 * 1 - 0 if False else (12 - 11) / 11 * 100)


def test_debt_to_equity_divides_by_net_worth_not_share_capital():
    data = screener_normalized()
    assert data["equity"]["by_year"]["Mar 2026"] == 200.0
    assert calculations.calculate_de_ratio(data) == pytest.approx(60 / 200)


def test_a_year_missing_reserves_leaves_equity_unknown_instead_of_understated():
    raw = {"profit_loss": {"__columns__": []}, "balance_sheet": {"__columns__": ["Mar 2026"], "Equity Capital": {"Mar 2026": "10"}, "Borrowings": {"Mar 2026": "60"}},
           "quarterly_results": {"__columns__": []}}
    assert calculations.calculate_de_ratio(normalize_screener_data(raw)) is None


class _Resp:
    def __init__(self, status, url, html="<html></html>"):
        self.status_code, self.url, self.text = status, url, html


def test_screener_adapter_default_is_unchanged_and_consolidated_is_opt_in(monkeypatch):
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append((url, timeout))
        return _Resp(200, url)

    monkeypatch.setattr(requests, "get", fake_get)
    assert screener_adapter.get_screener_data("abc")["view"] == "standalone" and seen[-1][0].endswith("/ABC/")
    assert screener_adapter.get_screener_data("abc", consolidated=True)["view"] == "consolidated" and seen[-1][0].endswith("/consolidated/")
    assert all(t == 20 for _, t in seen)  # every request now has a timeout


def test_screener_falls_back_when_the_preferred_view_is_missing(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=None: _Resp(404 if url.endswith("/consolidated/") else 200, url.replace("/consolidated/", "/")))
    assert screener_adapter.get_screener_data("abc", consolidated=True)["view"] == "standalone"
    monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=None: _Resp(500, url))
    assert "error" in screener_adapter.get_screener_data("abc")
