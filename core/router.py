"""
Routing helpers: which module (1 Personal Finance, 2 Tutor, 3 Market
Analysis, 4 Equity Research) should handle a query.

Centralized here rather than scattered across business-logic modules, so
core/orchestrator.py's dispatch logic is the only place that needs to
change if routing rules change. modules/equity_research/investment.py
and modules/market/analyzer.py keep only their actual business logic.
"""
from __future__ import annotations

from shared.intent_classifier import classify_intent

# Fundamental/balance-sheet keywords -> Module 4 (equity research), the
# screener.in-grounded path, not live price.
_FUNDAMENTAL_KEYWORDS = (
    "debt", "borrowing", "borrowings", "revenue", "sales", "profit",
    "net profit", "balance sheet", "cash flow", "quarterly", "annual",
    "earnings", "ebitda", "income", "expense", "equity ratio",
    "debt to equity", "d/e ratio", "financial year", "fy", "revenue growth",
    "profit growth", "debt change", "numerical difference", "financial report",
    "financial results", "statement", "results",
)

# Live stock price/news intent -> Module 4 (equity research), the
# yfinance-grounded path.
_INVESTMENT_INTENT_WORDS = (
    "stock price", "share price", "stock analysis", "analyze stock",
    "market cap", "news",
)

# Broad market/index/sector/macro terms -> Module 3 (market analysis),
# not about any single listed company.
_BROAD_MARKET_TERMS = (
    "stock market", "market respond", "market react", "nifty", "sensex",
    "index", "indices", "sector", "sectors", "election", "government",
    "policy", "budget", "rbi", "inflation", "gdp", "bjp", "congress",
    "west bengal",
)
_INDIVIDUAL_STOCK_TERMS = (
    "stock price", "share price", "market cap", "pe ratio", "p/e", "ticker",
)


def route_query(query: str) -> str:
    """Coarse M1/M2/general bucket -- see shared/intent_classifier.py."""
    return classify_intent(query)


def route(query: str) -> str:
    """Backward-compatible alias for older call sites."""
    return route_query(query)


def is_fundamental_query(query: str) -> bool:
    """True if the query is about fundamental/balance-sheet data (Module 4,
    screener.in path), not live stock price."""
    text = query.lower()
    return any(kw in text for kw in _FUNDAMENTAL_KEYWORDS)


def is_investment_query(query: str) -> bool:
    """True ONLY for live market/stock price/news queries (Module 4,
    yfinance path) -- NOT for fundamental analysis."""
    text = query.lower()
    if is_fundamental_query(query):
        return False
    return any(word in text for word in _INVESTMENT_INTENT_WORDS)


def is_equity_research_query(query: str, ticker: str | None) -> bool:
    """True if this query should go to Module 4 (Equity Research) at all --
    either a resolved company + fundamental intent, or a live-price/news
    intent."""
    if ticker and is_fundamental_query(query):
        return True
    return is_investment_query(query)


def is_broad_market_query(query: str) -> bool:
    """True for market/index/sector/macro questions that are not about one
    listed stock (Module 3, not Module 4)."""
    text = query.lower()
    return any(term in text for term in _BROAD_MARKET_TERMS) and not any(
        term in text for term in _INDIVIDUAL_STOCK_TERMS
    )
