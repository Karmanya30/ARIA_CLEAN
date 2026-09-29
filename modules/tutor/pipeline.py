"""
Tutor pipeline: Module 2 orchestrator (retrieval -> DKT -> DQN -> TAXAL)
with a generic LLM fallback for queries that don't confidently match any
concept in the knowledge base.
"""
from __future__ import annotations

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import tutor_prompt
from modules.tutor import orchestrator as m2_orchestrator
from shared.blocks import ExplanationBlock, MCQBlock, MasteryBlock, dump_blocks, text_or_error_blocks
from shared.ner import extract_entities

# ---------------------------------------------------------------------------
# Out-of-scope guard
# ---------------------------------------------------------------------------
# Keywords that indicate a finance / economics / investing question -- the
# domain ARIA is actually built for.  Kept intentionally broad so that
# misspelled or paraphrased finance queries still pass through.
_FINANCE_SCOPE_KEYWORDS = (
    # Core finance
    "sip", "mutual fund", "investment", "invest", "portfolio", "stock",
    "share", "equity", "debt", "bond", "nifty", "sensex", "nse", "bse",
    "sebi", "ipo", "dividend", "return", "interest", "compound",
    "simple interest", "tax", "income tax", "gst", "tds", "budget",
    "emi", "loan", "insurance", "premium", "pension", "pf", "ppf", "epf",
    "nps", "elss", "fd", "fixed deposit", "recurring deposit", "rd",
    "inflation", "gdp", "rbi", "repo rate", "fiscal", "monetary",
    "saving", "savings", "expense", "credit", "debit", "net worth",
    "asset", "liability", "balance sheet", "cash flow", "p/e",
    "price to earnings", "market cap", "liquidity", "solvency",
    "risk", "volatility", "hedge", "derivative", "futures", "options",
    "commodity", "gold", "real estate", "realty", "reit",
    # Financial concepts that might be asked as "what is X"
    "compounding", "diversification", "arbitrage", "amortisation",
    "amortization", "depreciation", "working capital", "leverage",
    "margin", "short selling", "buyback", "rights issue", "bonus share",
    "face value", "book value", "intrinsic value", "bull", "bear",
    "circuit breaker", "upper circuit", "lower circuit",
    "moving average", "rsi", "macd", "candlestick", "support",
    "resistance", "stop loss", "index fund", "etf", "nav",
    "expense ratio", "alpha", "beta", "sharpe", "standard deviation",
    "correlation", "covariance", "systematic risk", "unsystematic",
    "sector", "cyclical", "defensive", "blue chip", "mid cap", "small cap",
    "large cap", "penny stock",
    # Generic scope words -- found live: "what about current happenings in
    # financial markets" was rejected as out-of-scope because "financial
    # markets" itself isn't a substring of any of the specific terms above
    # (only compounds like "market cap" were listed, not bare "market").
    "market", "markets", "financial", "finance", "economy", "economic",
    "economics",
)


def _is_finance_related(query: str) -> bool:
    """Return True if the query is plausibly about finance / economics."""
    text = query.lower()
    return any(kw in text for kw in _FINANCE_SCOPE_KEYWORDS)


_OUT_OF_SCOPE_REPLY = (
    "I'm ARIA, your Indian personal finance and investment assistant. "
    "I can help you with topics like SIPs, mutual funds, stocks, taxes, "
    "budgeting, market analysis, and financial concepts. "
    "I'm not able to answer general knowledge questions outside finance. "
    "Feel free to ask me anything about your money or the markets!"
)


def build_context(query: str) -> dict[str, Any]:
    return {"entities": extract_entities(query)}


def run_pipeline(query: str, user_id: str = "default") -> dict[str, Any]:
    result = m2_orchestrator.handle(user_id, query)
    if result is not None:
        taxal = result["taxal"]
        response_text = (
            f"Cognitive: {taxal['cognitive']}\n"
            f"Functional: {taxal['functional']}\n"
            f"Causal: {taxal['causal']}"
        )

        blocks = [
            ExplanationBlock(label="Cognitive", content=taxal["cognitive"]),
            ExplanationBlock(label="Functional", content=taxal["functional"]),
            ExplanationBlock(label="Causal", content=taxal["causal"]),
            MasteryBlock(topic=result["concept_name"], concept_id=result["concept_id"], score=result["mastery"]),
        ]
        if result["quiz"]:
            blocks.append(
                MCQBlock(
                    question=result["quiz"]["question"],
                    correct_answer=result["quiz"]["correct_answer"],
                    wrong_answers=result["quiz"]["wrong_answers"],
                    explanation=result["quiz"]["explanation"],
                    concept_id=result["quiz"]["concept_id"],
                )
            )

        return {
            "domain": "tutor",
            "query": query,
            "response": response_text,
            "blocks": dump_blocks(blocks),
            "concept": result["concept_name"],
            "level": result["level"],
            "action": result["action"],
            "mastery": result["mastery"],
            "taxal": taxal,
            "quiz": result["quiz"],
        }

    # No confident concept match in the finance knowledge base.
    # Only call the LLM if the query is plausibly finance-related -- otherwise
    # we'd end up answering arbitrary general-knowledge questions (physics,
    # sports, etc.) which is outside ARIA's scope.
    if not _is_finance_related(query):
        return {
            "domain": "out_of_scope",
            "query": query,
            "response": _OUT_OF_SCOPE_REPLY,
            "blocks": text_or_error_blocks(_OUT_OF_SCOPE_REPLY),
        }

    context = build_context(query)
    prompt = tutor_prompt(query, context)
    answer = generate_response(prompt)
    return {
        "domain": "tutor",
        "query": query,
        "context": context,
        "response": answer,
        "blocks": text_or_error_blocks(answer),
    }


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class TutorPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
