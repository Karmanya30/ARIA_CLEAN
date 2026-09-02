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
    "market cap",
)

# Generic "should I invest in <company>" phrasing -> Module 4, but ONLY
# when a company is actually resolved (see is_equity_research_query) --
# unlike _INVESTMENT_INTENT_WORDS above, these words alone are far too
# common in genuine Module 1 queries ("how should I invest my salary") to
# use without that guard. Found live: "should I invest in TCS" resolves a
# real ticker but matches none of _INVESTMENT_INTENT_WORDS's narrow
# phrasing, so it fell through to Module 1's generic answer instead of
# ever reaching the real yfinance-grounded, disclaimer-first analysis in
# modules/equity_research/investment.py.
_GENERIC_INVESTMENT_PHRASES = (
    "invest in", "should i invest", "should i buy", "good time to buy",
    "worth buying", "worth investing",
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
)
_INDIVIDUAL_STOCK_TERMS = (
    "stock price", "share price", "market cap", "pe ratio", "p/e", "ticker",
)

# Unnamed "pick a stock for me" phrasing -> Module 4's beginner-screener
# path (modules/equity_research/beginner_screener.py), checked as a
# precise routing predicate for the same reason is_broad_market_query and
# is_equity_research_query are -- classify_intent's coarse bucket sends
# "which stock should I invest in" to "finance" (FINANCE_KEYWORDS' "invest"
# is checked before MARKET_KEYWORDS' "stock"), which would otherwise never
# reach Module 4 at all. Gated on "stock" being present, then a signal
# word/phrase -- exact multi-word phrase matching was tried first and
# missed real phrasing like "name me some stocks which are performing
# well" (no exact match for "stocks performing well" with "which are" in
# between) and "recommend a good stock" (no exact match for "recommend a
# stock" with "good" in between), so this uses bare "recommend"/"suggest"
# instead. Deliberately does NOT include a bare "should i buy" as a
# standalone signal, though -- "should I buy TCS stock" must still resolve
# TCS specifically, not fall in here.
_STOCK_SUGGESTION_SIGNALS = (
    "which stock", "name some stock", "name me some stock", "name a stock",
    "recommend", "suggest", "beginner", "performing well", "perform well",
    "good stocks", "best stocks", "top stocks", "help me pick",
    "don't know which", "dont know which",
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
    a resolved company + fundamental intent, a resolved company + generic
    investment intent, or a live-price/news intent."""
    if ticker and is_fundamental_query(query):
        return True
    if ticker:
        text = query.lower()
        if any(phrase in text for phrase in _GENERIC_INVESTMENT_PHRASES):
            return True
    return is_investment_query(query)


def is_broad_market_query(query: str) -> bool:
    """True for market/index/sector/macro questions that are not about one
    listed stock (Module 3, not Module 4)."""
    text = query.lower()
    return any(term in text for term in _BROAD_MARKET_TERMS) and not any(
        term in text for term in _INDIVIDUAL_STOCK_TERMS
    )


def wants_stock_suggestions(query: str) -> bool:
    """True for unnamed "which stock should I buy"-style requests (Module
    4's beginner-screener path) -- checked ahead of the coarse domain
    bucket, same as is_broad_market_query/is_equity_research_query."""
    text = query.lower()
    if "stock" not in text:
        return False
    return any(signal in text for signal in _STOCK_SUGGESTION_SIGNALS)
