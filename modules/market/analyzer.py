"""
Real broad-market data — Nifty/Sensex index levels + sector-basket
aggregates via yfinance, plus market-wide headlines via Economic Times'
dozens of public RSS feeds, India and abroad (shared/news.py: no API key,
no ToS issue — RSS is meant for public syndication; NewsAPI's free tier
explicitly forbids this use).

No trained model here by design: this module's value is real current
data + LLM synthesis, the same pattern as the equity-research module,
not another model to train.
"""
from __future__ import annotations

from typing import Any

import yfinance as yf
from loguru import logger

from modules.equity_research.intelligence.data import _ttl_cache
from shared.news import fetch_news, format_headlines

INDEX_TICKERS = {"nifty": "^NSEI", "nifty 50": "^NSEI", "sensex": "^BSESN"}

# Representative large-cap baskets per sector -- equal-weight proxy, not a
# real index. TATAMOTORS.NS was replaced with TMPV.NS after Tata Motors'
# Oct/Nov 2025 demerger into passenger-vehicle (TMPV) and commercial-
# vehicle (TMLCV) entities; verified live against yfinance, not assumed.
SECTOR_TICKERS = {
    "it": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
    "banking": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS"],
    "auto": ["MARUTI.NS", "TMPV.NS", "M&M.NS", "BAJAJ-AUTO.NS"],
    "pharma": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS"],
    "fmcg": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS"],
}

def _pct_change(closes: list[float]) -> float | None:
    if len(closes) < 2 or closes[0] == 0:
        return None
    return (closes[-1] - closes[0]) / closes[0] * 100


@_ttl_cache(300)  # was lru_cache: index levels never refreshed until a restart
def get_index_snapshot(name: str) -> dict[str, Any]:
    """Nifty/Sensex snapshot: current level, 5-day % change, trend."""
    ticker = INDEX_TICKERS.get(name.lower())
    if not ticker:
        return {"error": f"Unknown index '{name}'"}
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1d")
        if hist.empty:
            return {"error": "No data returned"}
        closes = hist["Close"].tolist()
        change = _pct_change(closes)
        return {
            "index": name.title(),
            "ticker": ticker,
            "current_level": round(closes[-1], 2),
            "five_day_change_pct": round(change, 2) if change is not None else None,
            "trend": "up" if closes[-1] > closes[0] else "down" if closes[-1] < closes[0] else "flat",
        }
    except Exception as exc:
        return {"error": str(exc)}


@_ttl_cache(300)
def get_sector_snapshot(sector: str) -> dict[str, Any]:
    """Equal-weight snapshot of a representative sector basket."""
    tickers = SECTOR_TICKERS.get(sector.lower())
    if not tickers:
        return {"error": f"Unknown sector '{sector}'"}

    changes = []
    constituents = []
    for symbol in tickers:
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if hist.empty:
                continue
            change = _pct_change(hist["Close"].tolist())
            if change is not None:
                changes.append(change)
                constituents.append({"ticker": symbol, "five_day_change_pct": round(change, 2)})
        except Exception as exc:
            logger.debug(f"yfinance fetch failed for {symbol} (sector {sector}): {exc}")
            continue

    if not changes:
        logger.warning(f"No live data available for any ticker in sector '{sector}'")
        return {"error": f"No live data available for sector '{sector}'"}

    avg_change = sum(changes) / len(changes)
    return {
        "sector": sector.upper(),
        "constituents": constituents,
        "avg_five_day_change_pct": round(avg_change, 2),
        "trend": "up" if avg_change > 0 else "down" if avg_change < 0 else "flat",
    }


def get_market_news(query: str = "", limit: int = 12) -> list[str]:
    """Fresh headlines for the question (or a broad market + world briefing when it names nothing specific), merged
    from many Indian and international feeds, each tagged with its source and age. Empty list, never an error."""
    return format_headlines(fetch_news(query, limit=limit))


def _detect_sector(query: str) -> str | None:
    text = query.lower()
    for sector in SECTOR_TICKERS:
        if sector in text:
            return sector
    return None


def _detect_index(query: str) -> str | None:
    text = query.lower()
    for name in INDEX_TICKERS:
        if name in text:
            return name
    return None


class MarketAnalyzer:
    def analyze(self, query: str) -> dict[str, Any]:
        sector = _detect_sector(query)
        index_name = _detect_index(query)

        context: dict[str, Any] = {"query": query, "news_headlines": get_market_news(query)}

        if sector:
            context["sector"] = get_sector_snapshot(sector)
        if index_name:
            context["index"] = get_index_snapshot(index_name)
        if not sector and not index_name:
            # General "how's the market" query -- show both major indices.
            context["nifty"] = get_index_snapshot("nifty")
            context["sensex"] = get_index_snapshot("sensex")

        return context
