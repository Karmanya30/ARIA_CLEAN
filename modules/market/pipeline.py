"""Market pipeline: context + prompt + Groq response."""

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import market_prompt
from modules.market.analyzer import MarketAnalyzer
from shared import finance_knowledge


def build_context(query: str) -> dict[str, Any]:
    return MarketAnalyzer().analyze(query)


def build_prompt(query: str, context: dict[str, Any] | None = None, grounding: str = "") -> str:
    return market_prompt(query, context or build_context(query), grounding=grounding)


def run_pipeline(query: str) -> dict[str, Any]:
    context = build_context(query)
    # Grounds general market-mechanics questions ("what is a circuit
    # breaker", "what is short selling") that MarketAnalyzer's live
    # index/sector/news context doesn't cover -- that context is about
    # current market state, not conceptual mechanics.
    grounding = finance_knowledge.grounding_for(query)
    prompt = build_prompt(query, context, grounding=grounding)
    answer = generate_response(prompt)
    return {
        "domain": "market",
        "query": query,
        "context": context,
        "response": answer,
    }


class MarketPipeline:
    def run(self, query: str) -> dict[str, Any]:
        return run_pipeline(query)
