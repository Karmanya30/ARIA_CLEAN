"""Module 3 vs Module 4 routing predicates -- pure logic, no ML, no LLM."""
from core.router import is_broad_market_query, is_equity_research_query, is_fundamental_query


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
