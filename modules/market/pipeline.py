"""Market pipeline: context + prompt + Groq response."""

from typing import Any
import json
import re

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import market_prompt
from modules.finance import personal
from modules.market.analyzer import MarketAnalyzer
from shared import finance_knowledge
from shared.blocks import MetricBlock, TextBlock, dump_blocks, text_or_error_blocks


def build_context(query: str) -> dict[str, Any]:
    return MarketAnalyzer().analyze(query)


def build_prompt(query: str, context: dict[str, Any] | None = None, grounding: str = "") -> str:
    return market_prompt(query, context or build_context(query), grounding=grounding)



def grounded_market_text(answer: str, context: dict) -> tuple[str, bool]:
    """Fail closed on contradictory freshness or relabelled foreign money.

    Daily snapshots cannot establish current conditions. A deterministic fallback
    uses only dated index facts; headlines are not proof of causal market drivers.
    """
    source = json.dumps(context, default=str, ensure_ascii=False)
    current_claim = bool(re.search(r"\b(?:today|currently|right now|live prices|at present|current (?:driver|market|price|conditions))\b", answer, re.I))
    driver_question = bool(re.search(r"\b(?:factors?|drivers?|driv(?:e|es|ing)|why|causes?|influence)\b", str(context.get('query', '')), re.I))
    causal_claim = driver_question and bool(re.search(r"\b(?:driven (?:mainly |primarily )?by|caused by|primary contributors?|current driver)\b", answer, re.I))
    foreign_source = bool(re.search(r"\$|\b(?:USD|dollars?|cents?)\b", source, re.I))
    relabelled = foreign_source and bool(re.search(r"₹|\b(?:INR|rupees?|paise)\b", answer, re.I))
    if not current_claim and not relabelled and not causal_claim:
        return answer, False
    # Keep useful educational or historical sentences that do not themselves
    # make the unsupported claim. Replacing the entire answer would turn a
    # Nifty-vs-Sensex explanation into an unrelated list of index levels.
    safe = []
    # Market-driver summaries can make unverified causal claims even without
    # the word "today". Retain context only for explicit concept comparisons.
    concept = bool(re.search(r"\b(?:explain|difference|compare|what (?:is|are|does))\b", str(context.get('query', '')), re.I))
    for part in re.split(r"(?<=[.!?])\s+|\n+", answer) if concept else []:
        part = part.strip()
        if not part:
            continue
        if re.search(r"\b(?:today|currently|right now|live prices|at present)\b", part, re.I):
            continue
        if foreign_source and re.search(r"₹|\b(?:INR|rupees?|paise)\b", part, re.I):
            continue
        safe.append(part)
    lines = safe + ["Current market conditions cannot be confirmed from these daily snapshots."]
    for item in context.values():
        if not isinstance(item, dict) or not item.get("as_of"):
            continue
        name = item.get("index") or item.get("sector") or "Index"
        if item.get("current_level") is not None:
            line = f"{name}: {item['current_level']} index points as of {item['as_of']}."
            if item.get("today_change_pct") is not None:
                line += f" The change from the previous close for that dated session was {item['today_change_pct']}%."
            lines.append(line)
    lines.append("Rates, currency movements, commodity costs and earnings can affect markets; the supplied headlines do not establish which factor caused these moves. Source currency units must be verified before comparing prices.")
    return "\n\n".join(lines), True


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
    dates = sorted({str(v['as_of']) for v in context.values() if isinstance(v, dict) and v.get('as_of')})
    note = ("Available index snapshots are dated " + ", ".join(dates) + "; these are delayed observations, not verified live prices.") if dates else ""
    if note:
        context['freshness_note'] = note
    # general market-mechanics questions (circuit breaker, short selling) are grounded in the curated finance knowledge
    prompt = build_prompt(query, context, grounding=finance_knowledge.grounding_for(query))
    answer, fallback = grounded_market_text(generate_response(prompt), context)
    response = {"domain": "market", "query": query, "context": context, "response": answer, "market_semantic_fallback": fallback, "blocks": _build_market_blocks(answer, context)}
    if fallback:  # the strict fallback is the same index lines for every question: add what the question is actually about
        try:
            from shared.news import fetch_news, format_headlines

            items = fetch_news("sensex nifty stock market", limit=5)
        except Exception:  # noqa: BLE001 - headlines are a bonus
            items = []
        if items:
            lines = format_headlines(items)
            answer += "\n\nHeadlines on this (they do not prove what caused the moves):\n" + "\n".join("- " + line for line in lines)
            response["context"]["news_headlines"] = lines
            response["response"] = answer
    if note:
        response['freshness_note'] = note
        response['response'] = note + "\n\n" + response["response"]
    if caption := personal.market_caption(personal.profile()):
        response["profile_basis"] = caption
    return response


class MarketPipeline:
    def run(self, query: str) -> dict[str, Any]:
        return run_pipeline(query)
