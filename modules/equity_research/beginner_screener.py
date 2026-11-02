"""
modules/equity_research/beginner_screener.py

Two real-data, non-personalized stock lists for "which stock should I buy"
-style queries that name no company -- ARIA never picks individual
securities for a specific user (see investment.py's disclaimer discipline
in _analysis_prompt), but a published, objective, generic list is a
materially different and safer thing: the same list for every beginner,
built from real market data, the same kind of content financial media
already publishes daily ("today's top gainers", "large-cap stocks for
beginners").

- Beginner-friendly list: structural traits (large-cap, liquid,
  well-established) from real yfinance data over a fixed, curated
  universe -- not personalized, not a pick.
- Real performers list: actual recent % price change over the same
  universe, computed at query time -- always paired with the as-of
  window, since "performing well" only means something as of right now.
"""
from __future__ import annotations

from typing import Any

import yfinance as yf
from loguru import logger

from modules.equity_research.investment import get_stock_data
from modules.market.analyzer import SECTOR_TICKERS
from shared.market_math import pct_change

# Flattened, deduped universe from the sector baskets already curated in
# modules/market/analyzer.py -- large-cap, liquid, long-listed names across
# sectors. This is a reasonable, real, fixed universe to screen over, not
# a claim that these are "the best" stocks.
UNIVERSE = sorted({ticker for tickers in SECTOR_TICKERS.values() for ticker in tickers})


def _recent_change_pct(ticker: str, period: str = "1mo") -> float | None:
    """Real % price change over `period`, or None on any fetch failure --
    callers skip tickers that fail rather than crash or fabricate a
    number, same graceful-degradation pattern as
    modules/market/analyzer.py's get_sector_snapshot."""
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d")
        if hist.empty:
            return None
        return pct_change(hist["Close"].tolist())
    except Exception as exc:
        logger.debug(f"yfinance history fetch failed for {ticker}: {exc}")
        return None


def beginner_friendly_candidates(limit: int = 6) -> list[dict[str, Any]]:
    """Large-cap, liquid, well-established names from the curated
    universe, with real current market cap/PE -- objective structural
    traits, not a personalized pick. Skips any ticker whose live data
    fetch fails, rather than showing a partial/fake entry."""
    results: list[dict[str, Any]] = []
    for ticker in UNIVERSE:
        data = get_stock_data(ticker)
        if data.get("error") or not data.get("market_cap"):
            continue
        results.append(
            {
                "ticker": ticker,
                "company_name": ticker.replace(".NS", "").replace(".BO", ""),
                "market_cap": data["market_cap"],
                "pe_ratio": data.get("pe_ratio"),
                "current_price": data.get("current_price"),
            }
        )
        if len(results) >= limit:
            break
    return results


def top_recent_performers(limit: int = 5, period: str = "1mo") -> list[dict[str, Any]]:
    """Real top-N by actual price % change over `period` across the same
    curated universe, computed at query time -- never a static/cached
    list, since "performing well" only means something as of right now."""
    scored: list[dict[str, Any]] = []
    for ticker in UNIVERSE:
        change = _recent_change_pct(ticker, period=period)
        if change is None:
            continue
        scored.append(
            {
                "ticker": ticker,
                "company_name": ticker.replace(".NS", "").replace(".BO", ""),
                "change_pct": round(change, 2),
            }
        )
    scored.sort(key=lambda row: row["change_pct"], reverse=True)
    return scored[:limit]


def build_suggestions_prompt(
    beginner_list: list[dict[str, Any]],
    performers_list: list[dict[str, Any]],
    performance_window: str = "1 month",
) -> str:
    beginner_text = (
        "\n".join(
            f"- {item['company_name']} ({item['ticker']}): market cap {item['market_cap']}, "
            f"PE {item['pe_ratio'] if item['pe_ratio'] is not None else 'unavailable'}"
            for item in beginner_list
        )
        or "No live data available right now."
    )
    performers_text = (
        "\n".join(
            f"- {item['company_name']} ({item['ticker']}): {item['change_pct']:+.2f}% over {performance_window}"
            for item in performers_list
        )
        or "No live data available right now."
    )

    return f"""\
You are ARIA, an Indian financial assistant.

The user asked which stocks to consider as a beginner, or which stocks are
performing well. You do NOT pick individual stocks for anyone -- naming
specific securities as a personal recommendation is regulated investment
advice. Instead you are given two REAL, OBJECTIVE, GENERIC lists below --
the same lists anyone asking this would get, not tailored to this one
person -- to present factually with their real data.

BEGINNER-FRIENDLY CANDIDATES (large-cap, liquid, well-established -- real data):
{beginner_text}

RECENT TOP PERFORMERS (real {performance_window} price change, as of today):
{performers_text}

Rules:
- Open with one sentence making clear this is NOT a personal recommendation -- these are objective, published lists, the same for anyone who asks.
- For the beginner list, explain in general terms why large, liquid, well-known companies are commonly considered easier for a first-time investor (lower relative volatility than small/mid-caps, longer track record, easier to find information on) -- do not claim any of them personally suits the user.
- For the performers list, state plainly that recent performance does not predict future performance, and that this exact list will look different next week or next month.
- Use ONLY the tickers, prices, and percentages given above. Do not invent or add any not listed.
- Use Indian rupees and Indian market context (NSE/BSE).
- Keep it concise and factual, not hype-y.

Return exactly this format:
Insight: <one-line disclaimer that this isn't personalized advice>
Analysis: <the beginner-friendly candidates with real data and general reasoning>
Recommendation: <the recent top performers with real data and the "not predictive" caveat>
Risk: <one caveat about doing further research -- this is objective data only, not due diligence>
"""
