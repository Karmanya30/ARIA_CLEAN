"""Data questions about names outside the hard-coded company list (modules/qa/lookup.py) and the web-search fallback."""
import pytest

from modules.qa import lookup
from shared import websearch


@pytest.mark.parametrize("window,name,symbol,ok", [
    ("kaynes technology", "Kaynes Technology India Limited", "KAYNES.NS", True),
    ("keynes technology", "Kaynes Technology India Limited", "KAYNES.NS", True),      # one spelling slip beside an exact word
    ("suzlon energy", "Suzlon Energy Limited", "SUZLON.NS", True),
    ("gold", "Gold", "GC=F", True),
    ("inflation", "Insolation Energy Limited", "INA.NS", False),                       # a lone fuzzy word is never enough
    ("zorblax industries", "Kaynes Technology India Limited", "KAYNES.NS", False),
])
def test_confident_match(window, name, symbol, ok):
    assert lookup._confident(window, {"name": name, "symbol": symbol}) is ok


def test_candidates_drop_question_and_data_words():
    assert lookup.candidates("What is the PE ratio of Suzlon Energy?")[0] == "suzlon energy"
    assert lookup.candidates("What is a P/E ratio?") == []


def test_only_data_questions_with_a_named_thing_are_handled(monkeypatch):
    monkeypatch.setattr(lookup, "find_instrument", lambda *t: None)
    monkeypatch.setattr(lookup, "web_answer", lambda q, why: {"domain": "general", "response": "web"})
    assert lookup.data_answer("What is inflation?", "What is inflation?", "o", None) is None
    assert lookup.data_answer("tell me a joke", "tell me a joke", "o", None) is None
    assert lookup.data_answer("What is the debt of Zorblax Industries?", "x", "o", None)["response"] == "web"
    assert lookup.data_answer("what is the debt of zorblax industries", "x", "o", None) is None  # nothing says it is a name


def test_web_search_parses_results_and_never_raises(monkeypatch):
    html = ('<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Repo rate</a>'
            '<a class="result__snippet">5.50% since June</a></div>')

    class R:
        text = html
        def raise_for_status(self): pass

    websearch._cache.clear()
    monkeypatch.setattr(websearch.requests, "post", lambda *a, **k: R())
    assert websearch.search("rbi repo rate") == [{"title": "Repo rate", "snippet": "5.50% since June", "url": "https://example.com/a"}]

    websearch._cache.clear()
    def boom(*a, **k): raise OSError("offline")
    monkeypatch.setattr(websearch.requests, "post", boom)
    monkeypatch.setattr(websearch.requests, "get", boom)
    assert websearch.search("rbi repo rate") == []


def test_fundamentals_answers_keep_their_figures_through_the_number_check(monkeypatch):
    """The equity-research reply must carry its statements as evidence, or trust.enforce removes every figure from it."""
    from modules.equity_research import pipeline
    from modules.qa import trust

    data = {"net_profit": {"by_year": {"Mar 2024": 42042.0}}}
    monkeypatch.setattr(pipeline, "process_financial_query", lambda q, c: {"metric": "Profit", "value": None, "normalized_data": data,
                                                                         "explanation": "Net profit was ₹42,042 Cr in FY23-24.", "confidence": "high"})
    monkeypatch.setattr(pipeline, "resolve_company", lambda q: "RELIANCE")
    monkeypatch.setattr(pipeline, "is_fundamental_query", lambda q: True)
    resp = pipeline.run_pipeline("net profit of Reliance in FY23-24")
    assert trust.enforce(resp)["passed"] and "42,042" in resp["response"]


def test_two_companies_are_compared_from_the_data_only(monkeypatch):
    from modules.equity_research import financial_pipeline as fp

    raw = {"INFY": {"view": "consolidated"}, "WIPRO": {"view": "consolidated"}}
    monkeypatch.setattr(fp, "get_screener_data", lambda t, consolidated=False: raw.get(t, {"error": "not found"}))
    monkeypatch.setattr(fp, "normalize_screener_data", lambda r: {"revenue": {"by_year": {"Mar 2026": 178650.0 if r is raw["INFY"] else 92624.0}}})
    out = fp.compare_companies("Compare the revenue of Infosys and Wipro", ["INFY", "WIPRO", "NOPE"])
    assert "178,650" in out["explanation"] and "92,624" in out["explanation"] and "NOPE: revenue is not available" in out["explanation"]
    from shared.company_resolver import resolve_companies
    assert resolve_companies("Compare the revenue of Infosys and Wipro") == ["INFY", "WIPRO"]


def test_a_fund_question_never_resolves_to_the_company_inside_its_name(monkeypatch):
    from modules.market import instruments as I

    stock = {"id": "stock:SBIN.NS", "name": "State Bank of India", "symbol": "SBIN.NS", "type": "stock"}
    monkeypatch.setattr(I, "search", lambda q, limit=5: {"items": [stock]})
    assert lookup.find_instrument("Show me the NAV of SBI fund") is None
    assert lookup.find_instrument("price of SBI") == stock


def test_bing_tracking_links_are_unwrapped():
    import base64

    real = "https://example.com/nav?fund=sbi"
    wrapped = "https://www.bing.com/ck/a?!&&p=x&u=a1" + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=") + "&ntb=1"
    assert websearch._bing_link(wrapped) == real
    assert websearch._bing_link("https://example.com/x") == "https://example.com/x"


def test_a_stale_consolidated_page_falls_back_to_the_fresher_standalone_one(monkeypatch):
    from datetime import date

    from modules.equity_research import screener_adapter as sa

    old = {"profit_loss": {"__columns__": ["Mar 2014", "Mar 2015"]}}
    new = {"profit_loss": {"__columns__": ["Mar 2025", f"Mar {date.today().year}"]}}
    monkeypatch.setattr(sa, "_get_screener_data", lambda name, consolidated=False: old if consolidated else new)
    assert sa.get_screener_data("X", consolidated=True) is new
    monkeypatch.setattr(sa, "_get_screener_data", lambda name, consolidated=False: new)
    assert sa.get_screener_data("X", consolidated=True) is new


def test_a_research_report_reply_is_checked_against_the_report_it_summarises():
    from modules.qa import trust

    resp = {"domain": "equity_research", "value": 2422.08, "company": "TCS", "report": {"valuation": {"fair_value": 2422.08, "price": 2535.0}},
            "response": "Insight: the fair value is 2,422.08 against a price of 2,535."}
    assert trust.enforce(resp)["passed"] and "2,535" in resp["response"]
