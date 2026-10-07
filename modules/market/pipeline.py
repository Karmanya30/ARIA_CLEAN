"""Market pipeline: context + prompt + Groq response."""

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import market_prompt
from modules.finance import personal
from modules.market.analyzer import MarketAnalyzer


def build_context(query: str) -> dict[str, Any]:
    return MarketAnalyzer().analyze(query)


def build_prompt(query: str, context: dict[str, Any] | None = None) -> str:
    return market_prompt(query, context or build_context(query))


def run_pipeline(query: str) -> dict[str, Any]:
    context = build_context(query)
    prompt = build_prompt(query, context)
    answer = generate_response(prompt)
    response = {"domain": "market", "query": query, "context": context, "response": answer}
    if caption := personal.market_caption(personal.profile()):
        response["profile_basis"] = caption
    return response


class MarketPipeline:
    def run(self, query: str) -> dict[str, Any]:
        return run_pipeline(query)
