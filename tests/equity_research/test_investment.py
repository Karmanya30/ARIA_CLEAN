"""modules/equity_research/investment.py -- pure prompt-content checks
(no network) plus the stock-suggestions routing switch. See
tests/equity_research/test_beginner_screener.py for the real-data-backed
screener functions."""
from core.orchestrator import handle_query
from core.session import clear_session
from modules.equity_research.investment import _analysis_prompt, investment_module


def test_analysis_prompt_states_no_buy_sell_advice_explicitly():
    prompt = _analysis_prompt(
        query="should I invest in TCS",
        company_name="TCS",
        stock_data={"current_price": "Rs 4,000", "pe_ratio": 28, "market_cap": "Rs 14 lakh crore", "five_day_trend": "up"},
        headlines=["TCS wins large deal"],
        sentiment="Positive",
    )
    assert "personalized buy/sell advice" in prompt
    assert "NOT a buy/sell call" in prompt


def test_analysis_prompt_recommendation_is_framed_as_how_to_evaluate():
    prompt = _analysis_prompt(
        query="should I invest in TCS",
        company_name="TCS",
        stock_data={"current_price": None, "pe_ratio": None, "market_cap": None, "five_day_trend": "unknown"},
        headlines=[],
        sentiment="Neutral",
    )
    assert "how to evaluate this further" in prompt.lower() or "how to evaluate this stock further" in prompt.lower()


def test_investment_module_routes_unnamed_pick_requests_to_suggestions(mock_llm):
    result = investment_module("which stock should I invest in")
    assert result["domain"] == "stock_suggestions"
    assert "beginner_candidates" in result["context"]
    assert "top_performers" in result["context"]


def test_orchestrator_routes_stock_pick_request_to_suggestions_end_to_end(mock_llm):
    # The actual routing bug this fixes: classify_intent gives this query
    # domain=="finance" ("invest" is checked before "stock"), which would
    # otherwise send it to Module 1, never reaching this path at all.
    session_id = "__pytest_stock_suggestions__"
    clear_session(session_id)
    try:
        result = handle_query("which stock should I invest in", session_id=session_id)
        assert result["domain"] == "stock_suggestions"
    finally:
        clear_session(session_id)
