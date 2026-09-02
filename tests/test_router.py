"""Module 3 vs Module 4 routing predicates -- pure logic, no ML, no LLM."""
from core.router import (
    is_broad_market_query,
    is_equity_research_query,
    is_fundamental_query,
    wants_stock_suggestions,
)


def test_nifty_query_is_broad_market_not_equity_research():
    query = "how did the Nifty do this week"
    assert is_broad_market_query(query) is True
    assert is_equity_research_query(query, None) is False


def test_company_debt_query_is_equity_research():
    query = "what is Reliance Industries' debt to equity ratio"
    assert is_fundamental_query(query) is True
    assert is_equity_research_query(query, "RELIANCE.NS") is True
    assert is_broad_market_query(query) is False


def test_live_price_query_without_fundamental_keywords_is_equity_research():
    assert is_equity_research_query("what is TCS's current stock price", None) is True


def test_sector_query_is_broad_market():
    assert is_broad_market_query("how is the IT sector performing") is True


def test_unnamed_stock_pick_requests_want_suggestions():
    for query in [
        "which stock should I invest in",
        "name me some stocks which are performing well",
        "recommend a good stock",
        "suggest some best stocks for beginners",
        "which stocks should I buy",
        "I don't know which stock to invest in",
    ]:
        assert wants_stock_suggestions(query) is True, query


def test_named_company_query_does_not_want_suggestions():
    # Must still resolve the named company specifically, not fall into the
    # generic beginner-screener path.
    assert wants_stock_suggestions("should I buy TCS stock") is False
    assert wants_stock_suggestions("what is Reliance's stock price") is False


def test_query_without_stock_does_not_want_suggestions():
    assert wants_stock_suggestions("recommend a good mutual fund") is False
    assert wants_stock_suggestions("what is my risk profile") is False


def test_should_i_invest_in_named_company_reaches_equity_research():
    # Found live: this resolves a real ticker but matches none of the
    # narrow "stock price"/"analysis" phrasing is_investment_query alone
    # checks for, so it silently fell through to Module 1 instead of ever
    # reaching Module 4's yfinance-grounded analysis.
    assert is_equity_research_query("should I invest in TCS", "TCS") is True
    assert is_equity_research_query("is it a good time to buy Reliance", "RELIANCE") is True


def test_generic_investment_phrasing_without_a_resolved_company_stays_out():
    # The guard that makes the fix above safe -- these phrases alone are
    # far too common in genuine Module 1 queries to trigger Module 4
    # without an actual company resolved.
    assert is_equity_research_query("how should I invest my salary", None) is False
