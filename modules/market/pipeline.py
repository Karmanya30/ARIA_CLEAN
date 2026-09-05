"""Market pipeline: context + prompt + Groq response."""

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import market_prompt
from modules.market.analyzer import MarketAnalyzer
from shared.blocks import MetricBlock, TextBlock, dump_blocks, text_or_error_blocks


def build_context(query: str) -> dict[str, Any]:
    return MarketAnalyzer().analyze(query)


def build_prompt(query: str, context: dict[str, Any] | None = None) -> str:
    return market_prompt(query, context or build_context(query))


def _build_market_blocks(answer: str, context: dict[str, Any]) -> list[dict]:
    """TextBlock for the narration, plus a real MetricBlock per index/
    sector snapshot already fetched into `context` by MarketAnalyzer --
    the level/% change numbers are real yfinance data, not LLM output, so
    they're surfaced directly rather than only through the LLM's prose."""
    if answer.startswith("Error"):
        return text_or_error_blocks(answer)

    blocks = [TextBlock(content=answer)]
    for key in ("index", "sector", "nifty", "sensex"):
        snapshot = context.get(key)
        if not snapshot or snapshot.get("error"):
            continue
        label = snapshot.get("index") or snapshot.get("sector") or key.title()
        level = snapshot.get("current_level")
        change = snapshot.get("five_day_change_pct", snapshot.get("avg_five_day_change_pct"))
        if level is not None:
            blocks.append(MetricBlock(label=f"{label} level", value=f"{level:,.2f}"))
        if change is not None:
            blocks.append(MetricBlock(label=f"{label} 5-day change", value=f"{change:+.2f}", unit="%"))
    return dump_blocks(blocks)


def run_pipeline(query: str) -> dict[str, Any]:
    context = build_context(query)
    prompt = build_prompt(query, context)
    answer = generate_response(prompt)
    return {
        "domain": "market",
        "query": query,
        "context": context,
        "response": answer,
        "blocks": _build_market_blocks(answer, context),
    }


class MarketPipeline:
    def run(self, query: str) -> dict[str, Any]:
        return run_pipeline(query)
