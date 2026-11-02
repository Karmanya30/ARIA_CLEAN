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

from loguru import logger

from core.router import is_fundamental_query, is_research_report_query
from modules.equity_research.financial_pipeline import compare_companies, process_financial_query
from modules.equity_research.investment import investment_module
from shared.blocks import MetricBlock, TextBlock, dump_blocks, text_or_error_blocks
from shared.company_resolver import resolve_companies, resolve_company


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

    # Full research report / valuation request -> the financial-intelligence layer.
    # Any failure there falls through to the standard paths below, so the existing
    # Module 4 behaviour is always the safety net.
    if is_research_report_query(query, ticker):
        try:
            from modules.equity_research.intelligence.fund import is_fund_query, run_fund_report

            if is_fund_query(query):
                return run_fund_report(query, user_id=user_id)
            from modules.equity_research.intelligence.pipeline import run_research

            return run_research(query, user_id=user_id)
        except Exception:
            logger.exception("research layer failed; falling back to the standard Module 4 path")

    if ticker and is_fundamental_query(query):
        tickers = resolve_companies(query)
        result = compare_companies(query, tickers) if len(tickers) > 1 else process_financial_query(query, ticker)
        return {
            "domain": "equity_research",
            "query": query,
            "company": ticker,
            "metric": result.get("metric"),
            "value": result.get("value"),
            "normalized_data": result.get("normalized_data"),  # the evidence modules/qa/trust.py checks the answer's numbers against
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
