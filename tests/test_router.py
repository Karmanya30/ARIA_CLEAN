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


def test_global_macro_questions_reach_the_market_module_so_they_get_live_news():
    from core.router import is_broad_market_query
    for q in ["What is the outlook for crude oil and how does it affect India?", "How will the Federal Reserve decision hit Nifty?",
              "Is the rupee against the dollar at a record low?", "Gold price outlook this week", "Impact of US tariffs on Indian exporters",
              "Will OPEC cuts push Brent higher?", "How is the Indian market today?", "Give me the latest news from India and abroad",
              "Any top headlines this morning?"]:
        assert is_broad_market_query(q), q


def test_everyday_money_questions_are_not_captured_by_the_macro_terms():
    from core.router import is_broad_market_query
    for q in ["How do I start investing with 5000 rupees a month?", "Plan my monthly budget", "Is this insurance policy good?",
              "Which software stocks should a beginner learn about?", "What is a SIP?", "Reliance news"]:
        assert not is_broad_market_query(q), q
