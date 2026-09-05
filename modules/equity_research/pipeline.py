"""
Equity research pipeline (Module 4) — unifies the two sub-paths that used
to be dispatched separately by core/orchestrator.py:

- Fundamental/balance-sheet analysis, grounded in real screener.in data
  (financial_pipeline.process_financial_query).
- Live stock price/news analysis, grounded in real yfinance data
  (investment.investment_module).

Routing between the two (and whether a query belongs here at all, vs.
Module 3 Market Analysis) lives in core/router.py, not here — this module
only does equity-research business logic.
"""
from __future__ import annotations

from typing import Any

from core.router import is_fundamental_query
from modules.equity_research.financial_pipeline import process_financial_query
from modules.equity_research.investment import investment_module
from shared.blocks import MetricBlock, TextBlock, dump_blocks, text_or_error_blocks
from shared.company_resolver import resolve_company


def _build_fundamental_blocks(result: dict[str, Any]) -> list[dict]:
    explanation = result.get("explanation") or ""
    if not explanation or explanation.startswith("Error"):
        return text_or_error_blocks(explanation or "No explanation available.")

    blocks: list = [TextBlock(content=explanation)]
    value = result.get("value")
    if value is not None:
        metric_label = str(result.get("metric") or "Metric").replace("_", " ").title()
        blocks.append(MetricBlock(label=metric_label, value=f"{value:,.2f}"))
    return dump_blocks(blocks)


def run_pipeline(query: str, user_id: str = "default") -> dict[str, Any]:
    ticker = resolve_company(query)

    if ticker and is_fundamental_query(query):
        result = process_financial_query(query, ticker)
        return {
            "domain": "equity_research",
            "query": query,
            "company": ticker,
            "metric": result.get("metric"),
            "value": result.get("value"),
            "response": result.get("explanation", ""),
            "confidence": result.get("confidence", "low"),
            "blocks": _build_fundamental_blocks(result),
        }

    return investment_module(query)


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class EquityResearchPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
