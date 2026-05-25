"""Live stock + news investment analysis module."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

import requests
import yfinance as yf

from ai.llm.groq_client import generate_response
from config import settings

# Keywords that indicate fundamental/balance-sheet analysis — must go to screener pipeline
_FUNDAMENTAL_KEYWORDS = (
    "debt", "borrowing", "borrowings", "revenue", "sales", "profit",
    "net profit", "balance sheet", "cash flow", "quarterly", "annual",
    "earnings", "ebitda", "income", "expense", "equity ratio",
    "debt to equity", "d/e ratio", "financial year", "fy", "revenue growth",
    "profit growth", "debt change", "numerical difference", "financial report",
    "financial results", "statement", "results",
)


NEWS_API_URL = "https://newsapi.org/v2/everything"


def _clean_company_query(query: str) -> str:
    cleaned = query.lower()
    cleaned = re.sub(r"\b(analy\w*|stock|stocks|share|shares|price|of|for|about|please|tell|me|the)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.,")
    return cleaned


def _search_terms(search_text: str) -> list[str]:
    terms = [search_text]
    if "estate" in search_text and "real estate" not in search_text:
        terms.append(search_text.replace("estate", "real estate"))
    return list(dict.fromkeys(term for term in terms if term))


def _compact_company_guess(text: str) -> str | None:
    lines = [line.strip(" .:-") for line in text.splitlines() if line.strip(" .:-")]
    if not lines:
        return None
    candidate = lines[-1]
    candidate = re.sub(r"^(company name|company|answer)\s*:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"[^A-Za-z0-9&.,() -]", "", candidate).strip(" .,-")
    if not candidate or len(candidate.split()) > 8 or len(candidate) > 80:
        return None
    return candidate


@lru_cache(maxsize=128)
def _llm_company_guess(search_text: str) -> str | None:
    """Infer a likely listed Indian company name when raw Yahoo search fails."""
    if not search_text:
        return None

    prompt = f"""\
The user mentioned this company/brand in an Indian stock query:
"{search_text}"

Infer the most likely listed Indian company name for Yahoo Finance search.
CRITICAL: Omit suffixes like "Ltd", "Limited", "Corp", "Inc", "Company" from your response. For example, return "Tata Motors" instead of "Tata Motors Ltd".
If it is unclear or not likely listed, return UNKNOWN.

Return only the company name or UNKNOWN.
"""
    result = generate_response(
        prompt,
        system_prompt="You resolve Indian listed company names from noisy user queries.",
    ).strip()
    result = re.sub(r"[`\"']", "", result).strip()
    if not result or "unknown" in result.lower() or result.lower().startswith("error:"):
        return None
    return _compact_company_guess(result)


def _is_indian_quote(quote: dict[str, Any]) -> bool:
    symbol = str(quote.get("symbol", ""))
    exchange = str(quote.get("exchange", "")).upper()
    quote_type = str(quote.get("quoteType", "")).upper()
    return quote_type == "EQUITY" and (symbol.endswith((".NS", ".BO")) or exchange in {"NSI", "BSE"})


@lru_cache(maxsize=128)
def search_company(query: str) -> dict[str, str] | None:
    """Resolve company/ticker dynamically through Yahoo Finance search."""
    search_text = _clean_company_query(query)
    if not search_text:
        return None

    search_terms = _search_terms(search_text)
    guessed_name = _llm_company_guess(search_text)
    if guessed_name and guessed_name.lower() != search_text.lower():
        search_terms.append(guessed_name)

    # Heuristic: try first 2 or 3 words if it's a long query
    words = search_text.split()
    if len(words) > 2:
        search_terms.append(" ".join(words[:2]))
    if len(words) > 3:
        search_terms.append(" ".join(words[:3]))

    for term in search_terms:
        company = _search_yahoo_company(term)
        if company:
            return company

    return None


def _search_yahoo_company(search_text: str) -> dict[str, str] | None:
    try:
        search = yf.Search(search_text, max_results=8)
        quotes = getattr(search, "quotes", []) or []
    except Exception:
        return None

    indian_quotes = [quote for quote in quotes if _is_indian_quote(quote)]
    quote = indian_quotes[0] if indian_quotes else (quotes[0] if quotes else None)
    if not quote:
        return None

    symbol = str(quote.get("symbol", "")).strip()
    company_name = str(
        quote.get("longname")
        or quote.get("shortname")
        or quote.get("name")
        or symbol
    ).strip()

    if not symbol:
        return None
    return {"ticker": symbol, "company_name": company_name}


def detect_company(query: str) -> dict[str, str] | None:
    ticker_match = re.search(r"\b([A-Z]{2,12})(?:\.NS|\.BO)?\b", query)
    if ticker_match:
        ticker = ticker_match.group(1)
        if not ticker.endswith((".NS", ".BO")):
            ticker = f"{ticker}.NS"
        return {"ticker": ticker, "company_name": ticker.replace(".NS", "").replace(".BO", "")}

    return search_company(query)


def _safe_number(value: Any) -> float | int | None:
    if value in {None, "", "N/A"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_market_cap(value: Any) -> str | None:
    number = _safe_number(value)
    if number is None:
        return None
    if number >= 10_000_000:
        return f"₹{number / 10_000_000:,.2f} crore"
    return f"₹{number:,.0f}"


@lru_cache(maxsize=64)
def get_stock_data(ticker: str) -> dict[str, Any]:
    """Fetch current stock metrics from Yahoo Finance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        fast_info = getattr(stock, "fast_info", {}) or {}
        history = stock.history(period="5d", interval="1d")

        current_price = _safe_number(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or getattr(fast_info, "last_price", None)
            or (fast_info.get("last_price") if hasattr(fast_info, "get") else None)
        )
        pe_ratio = _safe_number(info.get("trailingPE"))
        market_cap = _format_market_cap(
            info.get("marketCap")
            or getattr(fast_info, "market_cap", None)
            or (fast_info.get("market_cap") if hasattr(fast_info, "get") else None)
        )

        trend = "unknown"
        if history is not None and len(history) >= 2 and "Close" in history:
            start = _safe_number(history["Close"].iloc[0])
            end = _safe_number(history["Close"].iloc[-1])
            if start is not None and end is not None:
                trend = "up" if end > start else "down" if end < start else "flat"
                current_price = current_price if current_price is not None else end

        return {
            "ticker": ticker,
            "current_price": f"₹{current_price:,.2f}" if current_price is not None else None,
            "pe_ratio": round(pe_ratio, 2) if pe_ratio is not None else None,
            "market_cap": market_cap,
            "five_day_trend": trend,
            "error": None,
        }
    except Exception as exc:
        return {
            "ticker": ticker,
            "current_price": None,
            "pe_ratio": None,
            "market_cap": None,
            "five_day_trend": "unknown",
            "error": str(exc),
        }


@lru_cache(maxsize=64)
def get_news(ticker: str, limit: int = 5) -> list[str]:
    """Fetch recent news headlines using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news or []
        articles = [
            str(item.get("content", {}).get("title", "")).strip()
            for item in news_items
            if str(item.get("content", {}).get("title", "")).strip()
        ]
        return articles[:limit]
    except Exception:
        return []


def analyze_sentiment(headlines: list[str]) -> str:
    """Classify headline sentiment with Groq."""
    if not headlines:
        return "Neutral"

    prompt = f"""\
Classify the overall investor sentiment from these headlines.

Headlines:
{chr(10).join(f"- {headline}" for headline in headlines)}

Return exactly one word: Positive, Negative, or Neutral.
"""
    result = generate_response(prompt).strip()
    if "positive" in result.lower():
        return "Positive"
    if "negative" in result.lower():
        return "Negative"
    return "Neutral"


def _analysis_prompt(
    query: str,
    company_name: str,
    stock_data: dict[str, Any],
    headlines: list[str],
    sentiment: str,
) -> str:
    headlines_text = "\n".join(f"- {headline}" for headline in headlines) or "No recent headlines available."
    return f"""\
You are ARIA, an Indian financial analysis assistant.

User query:
{query}

Company:
{company_name}

Stock data:
- Current price: {stock_data.get("current_price") or "Unavailable"}
- PE ratio: {stock_data.get("pe_ratio") or "Unavailable"}
- Market cap: {stock_data.get("market_cap") or "Unavailable"}
- 5-day trend: {stock_data.get("five_day_trend") or "unknown"}

Recent headlines:
{headlines_text}

Headline sentiment:
{sentiment}

Rules:
- Use only Indian rupees.
- EXPLICITLY use the exact numbers provided in the 'Stock data' section in your output. Prioritize hard data and numbers over theoretical explanations.
- Do not promise returns.
- Do not give personalized buy/sell advice.
- If data is missing, mention it clearly.
- Keep the answer concise and practical.

Return exactly this format:
Insight:
Analysis:
Recommendation:
Risk:
"""


def investment_module(query: str) -> dict[str, Any]:
    """Analyze an Indian stock using yfinance, NewsAPI, and Groq."""
    company = detect_company(query)
    if company is None:
        response = (
            "Insight: I could not identify the company or ticker.\n"
            "Analysis: I searched the available market data source, but could not resolve that name to a listed stock.\n"
            "Recommendation: Try the listed company name or ticker symbol, for example the NSE or BSE ticker.\n"
            "Risk: If the query uses a brand name, project name, or unlisted business name, live stock data may not be available."
        )
        return {"domain": "investment", "query": query, "context": {}, "response": response}

    ticker = company["ticker"]
    company_name = company["company_name"]
    stock_data = get_stock_data(ticker)
    headlines = get_news(ticker)
    sentiment = analyze_sentiment(headlines)

    prompt = _analysis_prompt(query, company_name, stock_data, headlines, sentiment)
    answer = generate_response(
        prompt,
        system_prompt="You are an Indian financial analyst. Be concise, factual, and risk-aware.",
    )

    return {
        "domain": "investment",
        "query": query,
        "context": {
            "company_name": company_name,
            "ticker": ticker,
            "stock_data": stock_data,
            "news_headlines": headlines,
            "sentiment": sentiment,
            "cache_note": "Use lru_cache now; replace with TTL cache for production freshness.",
            "extension_note": "Technical indicators can be added from yfinance OHLCV history, e.g. SMA, RSI, MACD.",
        },
        "response": answer,
    }


def is_fundamental_query(query: str) -> bool:
    """Returns True if the query is about fundamental/balance-sheet data, not live stock price."""
    text = query.lower()
    return any(kw in text for kw in _FUNDAMENTAL_KEYWORDS)


def is_investment_query(query: str) -> bool:
    """Returns True ONLY for live market/stock price/news queries — NOT for fundamental analysis."""
    text = query.lower()
    # If it's a fundamental query, let the screener pipeline handle it
    if is_fundamental_query(query):
        return False
    intent_words = ("stock price", "share price", "stock analysis", "analyze stock", "market cap", "news")
    return any(word in text for word in intent_words)


def is_broad_market_query(query: str) -> bool:
    """Return True for market/event questions that are not about one listed stock."""
    text = query.lower()
    broad_terms = (
        "stock market",
        "market respond",
        "market react",
        "nifty",
        "sensex",
        "index",
        "indices",
        "sector",
        "sectors",
        "election",
        "government",
        "policy",
        "budget",
        "rbi",
        "inflation",
        "gdp",
        "bjp",
        "congress",
        "west bengal",
    )
    individual_stock_terms = (
        "stock price",
        "share price",
        "market cap",
        "pe ratio",
        "p/e",
        "ticker",
    )
    return any(term in text for term in broad_terms) and not any(
        term in text for term in individual_stock_terms
    )
