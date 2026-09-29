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
from modules.equity_research.financial_pipeline import process_financial_query
from modules.equity_research.investment import investment_module
from shared.company_resolver import resolve_company


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
        result = process_financial_query(query, ticker)
        return {
            "domain": "equity_research",
            "query": query,
            "company": ticker,
            "metric": result.get("metric"),
            "value": result.get("value"),
            "response": result.get("explanation", ""),
            "confidence": result.get("confidence", "low"),
        }

    return investment_module(query)


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class EquityResearchPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
