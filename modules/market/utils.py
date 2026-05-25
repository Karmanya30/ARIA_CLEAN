"""Static market utility helpers."""

from typing import Any


def fetch_market_data(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "source": "mock",
        "trend": "neutral",
        "note": "Live market data is not connected.",
    }
