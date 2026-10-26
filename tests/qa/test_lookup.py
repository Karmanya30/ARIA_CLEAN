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
