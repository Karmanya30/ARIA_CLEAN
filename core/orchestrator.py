"""Thin orchestrator for ARIA."""

import re
from typing import Any

from core.router import is_broad_market_query, is_equity_research_query, route_query
from core.session import save_turn
from modules.equity_research.pipeline import run_pipeline as equity_research_pipeline
from modules.finance.pipeline import run_pipeline as finance_pipeline
from modules.market.pipeline import run_pipeline as market_pipeline
from modules.tutor.pipeline import run_pipeline as tutor_pipeline
from shared.company_resolver import resolve_company

# Casual greetings/small-talk with no real question in them -- found live:
# these fell through to modules/tutor/pipeline.py's generic fallback, whose
# prompt unconditionally instructs the LLM to "explain the concept" in a
# rigid Insight/Analysis/Recommendation/Risk format. Sent through a real
# voice call (Conversational/Tavus mode), saying "hey" got answered with a
# structured lecture on what the word "hey" means -- the opposite of
# sounding like a person talking. Matched BEFORE any module routing so it
# never reaches that fallback at all.
_SMALLTALK_PHRASES = (
    "hi", "hey", "hello", "yo", "sup", "what's up", "whats up", "howdy",
    "good morning", "good afternoon", "good evening", "good night",
    "how are you", "how're you", "how are you doing", "how you doing",
    "thanks", "thank you", "thanks a lot", "thx", "cheers",
    "bye", "goodbye", "see you", "see ya", "cya", "talk later",
    "who are you", "what are you", "what's your name", "whats your name",
    "what can you do", "what can you help with", "help",
)
_SMALLTALK_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in _SMALLTALK_PHRASES) + r")[\s!.,?]*$"
)


def _is_smalltalk(query: str) -> bool:
    text = query.strip().lower()
    if not text:
        return False
    if _SMALLTALK_RE.match(text):
        return True
    # A single phrase from the list matches whole (e.g. "hey"), but a
    # compound greeting like "Hey, how are you?" is two phrases joined by
    # punctuation and never matches the anchored regex above -- found live:
    # it fell through to the tutor pipeline's out-of-scope guard and got
    # answered with the canned finance-scope disclaimer instead of a
    # natural reply. Split on the same punctuation the regex already
    # tolerates and require every clause to be smalltalk on its own, so a
    # real question tacked onto a greeting ("hey, what's the nifty doing")
    # still routes normally instead of being swallowed as smalltalk.
    clauses = [c.strip() for c in re.split(r"[!.,?]+", text) if c.strip()]
    return bool(clauses) and all(_SMALLTALK_RE.match(c) for c in clauses)


def _smalltalk_reply(query: str) -> dict[str, Any]:
    from ai.llm.groq_client import generate_response

    reply = generate_response(
        query,
        system_prompt=(
            "You are ARIA, a friendly Indian financial assistant in a real-time "
            "conversation (sometimes spoken aloud). The user just sent a casual "
            "greeting or small talk, not a real question. Reply the way a person "
            "would -- one or two short, warm sentences. No bullet points, no "
            "'Insight:'/'Analysis:' style sections, no definitions, no lecture. "
            "Naturally invite them to ask about their finances, a concept, or "
            "the market."
        ),
    )
    text = reply if (reply and not reply.lower().startswith("error")) else "Hey! What can I help you with today?"
    from shared.blocks import text_or_error_blocks

    return {"domain": "smalltalk", "query": query, "response": text, "blocks": text_or_error_blocks(text)}


def handle_query(query: str, session_id: str = "default", mode: str = "Normal Mode") -> dict[str, Any]:
    """Route a user query to the correct module pipeline."""

    if mode == "Conversational Mode":
        from core.session import get_session
        from ai.llm.groq_client import generate_response

        session = get_session(session_id)
        history = session.get("history", [])[-3:]  # Last 3 turns
        if history:
            history_str = ""
            for i, turn in enumerate(history):
                history_str += f"User: {turn['query']}\n"

            prompt = f"""
Given this chat history:
{history_str}

Rewrite the user's follow-up query to be fully self-contained.
If it refers to a company or topic from the history, explicitly include it in the new query.
If it is already standalone, return it exactly as is.
Return ONLY the rewritten query. Do not add any conversational text.

Follow-up query: {query}
"""
            rewritten = generate_response(prompt, system_prompt="You rewrite queries. Output ONLY the rewritten query.")
            if rewritten and not rewritten.lower().startswith("error"):
                query = rewritten.strip('"\' \n')

    if _is_smalltalk(query):
        response = _smalltalk_reply(query)
        save_turn(session_id, query, response)
        return response

    domain = route_query(query)
    ticker = resolve_company(query)

    # Module 3 and Module 4 are checked ahead of the coarse keyword-bucket
    # `domain`, not nested inside it -- the coarse classifier's MARKET_KEYWORDS
    # list doesn't cover every broad-market term (e.g. "nifty"/"sensex"), so
    # gating these on domain == "market" silently dropped real market
    # queries to the general fallback. is_broad_market_query and
    # is_equity_research_query are the precise checks; domain is only the
    # fallback for Module 1 vs Module 2 vs general.
    if is_equity_research_query(query, ticker):
        response = equity_research_pipeline(query, user_id=session_id)
    elif is_broad_market_query(query):
        response = market_pipeline(query)
    elif domain == "finance":
        response = finance_pipeline(query, user_id=session_id)
    elif domain == "tutor":
        response = tutor_pipeline(query, user_id=session_id)
    elif domain == "market":
        # domain says market but neither precise check matched (rare).
        # Found live: "What about current market analysis?" (no company
        # name, no broad-market keyword hit) landed here and used to always
        # go to equity_research_pipeline, which *requires* a company to
        # analyze -- it just returned "I could not identify the company or
        # ticker" instead of an actual answer. Only route there if a ticker
        # actually resolved; a company-less market question belongs in
        # market_pipeline (Module 3), which is built to answer without one.
        if ticker:
            response = equity_research_pipeline(query, user_id=session_id)
        else:
            response = market_pipeline(query)
    else:
        # Falls to tutor_pipeline which has an out-of-scope guard: non-finance
        # queries (e.g. "who is Ronaldo", "what is SHM") are rejected there
        # with a polite refusal instead of being answered by the LLM.
        response = tutor_pipeline(query, user_id=session_id)
        if response.get("domain") != "out_of_scope":
            response["domain"] = "general"

    save_turn(session_id, query, response)
    return response


class Orchestrator:
    """Small class wrapper for callers that prefer object style."""

    def handle(self, user_input: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        session_id = str((context or {}).get("session_id", "default"))
        return handle_query(user_input, session_id=session_id)
