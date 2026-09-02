"""Tiny shared market-data math -- split out of modules/market/analyzer.py
so modules/equity_research/beginner_screener.py can reuse the exact same
% change calculation instead of a second copy of the formula."""
from __future__ import annotations


def pct_change(closes: list[float]) -> float | None:
    if len(closes) < 2 or closes[0] == 0:
        return None
    return (closes[-1] - closes[0]) / closes[0] * 100
