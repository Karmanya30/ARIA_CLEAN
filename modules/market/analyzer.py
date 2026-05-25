"""Lightweight market context builder."""

from typing import Any


class MarketAnalyzer:
    def analyze(self, query: str) -> dict[str, Any]:
        return {
            "query": query,
            "trends": ["price movement", "sector sentiment", "volume changes"],
            "insight": "Use current context cautiously; no live market data is loaded.",
        }
