"""
Routing helpers: which module (1 Personal Finance, 2 Tutor, 3 Market
Analysis, 4 Equity Research) should handle a query.

Centralized here rather than scattered across business-logic modules, so
core/orchestrator.py's dispatch logic is the only place that needs to
change if routing rules change. modules/equity_research/investment.py
and modules/market/analyzer.py keep only their actual business logic.
"""
from __future__ import annotations

import re

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
    "market cap",
)

# Broad market/index/sector/macro terms -> Module 3 (market analysis),
# not about any single listed company. Deliberately no bare "news" (collides
# with per-stock news, e.g. "Reliance news" -> handled by the fundamental/
# investment paths and the domain fallback instead) and no bare "policy"/
# "budget" (collide with personal-finance phrasing like "plan my monthly
# budget" or "is this insurance policy good" -> Module 1). "rbi"/"election"/
# "government"/etc. already cover genuine macro-policy queries.
_BROAD_MARKET_TERMS = (
    "stock market", "market respond", "market react", "nifty", "sensex",
    "index", "indices", "sector", "sectors", "election", "government",
    "rbi", "inflation", "gdp", "bjp", "congress",
    "west bengal",
    # global / commodity / currency macro that moves Indian markets. Phrases rather than bare words on purpose: bare
    # "rupee" would capture "invest 5000 rupees a month", bare "war" would capture "software".
    "crude", "brent", "oil price", "opec", "gold price", "silver price", "federal reserve", "fed rate", "wall street",
    "tariff", "sanctions", "geopolit", "bond yield", "recession", "global market", "us market", "usd inr", "dollar index",
    "rupee against", "rupee vs", "rupee fall", "rupee slip", "rupee weak", "rupee deprec", "rupee record",
    # everyday "what's going on" phrasing, India and abroad. Still no bare "news": "Reliance news" is a single-stock question.
    "market today", "markets today", "indian market", "share market", "market outlook", "market news", "market update",
    "news today", "latest news", "world news", "top news", "top headlines", "headlines",
)
_INDIVIDUAL_STOCK_TERMS = (
    "stock price", "share price", "market cap", "pe ratio", "p/e", "ticker",
)


# Full research-report / valuation intent -> Module 4's research layer
# (modules/equity_research/intelligence). Deliberately conservative so concept
# questions ("what is a DCF?", "what does an equity research analyst do?") still
# reach the tutor: report phrases need "on/for/of <something>", and valuation words
# need a recognised company alongside them.
_RESEARCH_REPORT_PHRASES = ("research report", "equity research", "initiate coverage", "initiating coverage", "dupont", "financial model",
                            "valuation report", "financial report", "mutual fund analysis", "mutual fund report", "fund analysis", "fund report")
_RESEARCH_COMPANY_PHRASES = (
    "investment thesis", "bull case", "bear case", "bull and bear", "valuation", "dcf", "fair value",
    "intrinsic value", "target price", "price target", "overvalued", "undervalued", "deep dive", "full analysis",
)
_CONCEPT_QUESTION = re.compile(r"^\s*(what is|what's|what are|explain|define|meaning of|how does|how do)\b")


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


def is_research_report_query(query: str, ticker: str | None) -> bool:
    """True if the user wants a full equity research report / valuation of a company
    (Module 4, intelligence layer) rather than a single metric or a live quote."""
    text = query.lower()
    if _CONCEPT_QUESTION.match(text) and not ticker:
        return False
    if any(p in text for p in _RESEARCH_REPORT_PHRASES) and (ticker or re.search(r"\b(on|for|of)\s+\w", text)):
        return True
    return bool(ticker) and any(p in text for p in _RESEARCH_COMPANY_PHRASES)


def is_equity_research_query(query: str, ticker: str | None) -> bool:
    """True if this query should go to Module 4 (Equity Research) at all --
    a full research/valuation request, a resolved company + fundamental
    intent, or a live-price/news intent."""
    if is_research_report_query(query, ticker):
        return True
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
