"""Thin orchestrator for ARIA."""

import re
from datetime import date
from typing import Any

from loguru import logger

from core.router import _CONCEPT_QUESTION, is_broad_market_query, is_equity_research_query, is_intelligence_query, route_query
from core.session import get_session, save_turn
from modules.equity_research.intelligence.pipeline import company_intelligence
from modules.equity_research.pipeline import run_pipeline as equity_research_pipeline
from modules.finance.pipeline import finance_intent, finance_statement, run_pipeline as finance_pipeline
from modules.market.pipeline import run_pipeline as market_pipeline
from modules.tutor.pipeline import run_pipeline as tutor_pipeline
from shared.company_resolver import resolve_company
from shared import human_state, user_store
from shared.human_state import current_voice_block
from shared.news import format_headlines, news_context
from shared.domain_guard import (
    CONFIDENCE_THRESHOLD,
    build_refusal_response,
    classify_domain,
    validate_output,
)

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
# "hi there", "hello aria", "thanks again": a greeting plus a vocative is still just a greeting. (Without this they fell
# through to the domain guard and were refused as off-topic.)
_SMALLTALK_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in _SMALLTALK_PHRASES) + r")(?:\s+(?:there|aria|everyone|all|again|friend|buddy|mate|sir|madam|team|guys))*[\s!.,?]*$"
)


def _is_smalltalk(query: str) -> bool:
    text = query.strip().lower()
    return bool(text) and bool(_SMALLTALK_RE.match(text))


is_smalltalk = _is_smalltalk  # public name for the Live Avatar, which answers small talk itself, faster


def _with_news(query: str, pipeline, *args, **kwargs) -> dict[str, Any]:
    """Run a module pipeline with fresh headlines available to its LLM calls (time-sensitive questions only), and
    record the headlines on the response so the UI can show what the answer was based on."""
    with news_context(query) as items:
        response = pipeline(query, *args, **kwargs)
    if items:
        response.setdefault("context", {}).setdefault("news_headlines", format_headlines(items))
    return response


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
            + (f"\n\n{voice}" if (voice := current_voice_block()) else "")
        ),
    )
    text = reply if (reply and not reply.lower().startswith("error")) else "Hey! What can I help you with today?"
    return {"domain": "smalltalk", "query": query, "response": text}


_SUPPORT_SYSTEM = (
    "You are ARIA, a warm Indian financial assistant. The user is being hard on themselves or venting. Reply in 2-3 short sentences: "
    "acknowledge what they said using only their own words and numbers, reassure without any claim about their finances, history, job or "
    "savings, then ask exactly ONE gentle open question or offer to look at the numbers together. Hard rule: never state any fact or "
    "figure about the user that is not in their message or profile. No plans, no lists.")
_INVENTED = re.compile(r"you(?:'ve| have) saved|your salary|your job|for the past", re.I)
_SAFE_SUPPORT = (
    "That sounds really heavy, and being this hard on yourself doesn't help. Money mistakes happen to everyone. Want to look at the numbers together, one small piece at a time?",
    "I hear you. One rough moment isn't the whole picture of how you handle money. What is weighing on you most right now?",
)
_SAFE_SUPPORT_HI = ("Samajh sakta hoon, yeh kaafi bhaari lag raha hoga. Ek galti poori kahani nahi hoti. Chahein to hum numbers saath mein dekh lein?",)


def _support_reply(query: str, profile: dict, hinglish: bool, turn: int) -> dict[str, Any]:
    """Venting / self-doubt: a constrained reply, checked in code. Any number not in the message or profile, or a claim about
    their savings, job or history, replaces the model's text with a fixed safe one."""
    from ai.llm.groq_client import generate_response

    reply = generate_response(query, system_prompt=_SUPPORT_SYSTEM) or ""
    norm = lambda t: {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", t)}
    if reply.lower().startswith("error") or _INVENTED.search(reply) or not norm(reply) <= norm(query) | norm(str(profile)):
        options = _SAFE_SUPPORT_HI if hinglish else _SAFE_SUPPORT
        reply = options[turn % len(options)]
    return {"domain": "support", "query": query, "response": reply}


def _handle(query: str, session_id: str = "default", mode: str = "Normal Mode") -> dict[str, Any]:
    """Route a user query to the correct module pipeline."""

    if mode in ("Conversational Mode", "Live Avatar"):  # spoken follow-ups ("what about taxes on it?") need their subject back
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

    # a bare "about 40k" answers our pending finance question; "can I afford..." is a finance tool whatever the keywords say
    pending_before = get_session(session_id).get("finance_pending")
    by_intent = pending_before or finance_intent(query) or finance_statement(query)
    domain = "finance" if by_intent else route_query(query)
    if domain == "finance" and not by_intent and _CONCEPT_QUESTION.match(query.lower()) and not re.search(r"\b(i|i'm|im|i've|my|me|mine|we|our)\b", query.lower()):
        domain = "tutor"  # "what is expense ratio?" is a concept, whatever the keyword router thinks
    ticker = resolve_company(query)

    # Module 3 and Module 4 are checked ahead of the coarse keyword-bucket
    # `domain`, not nested inside it -- the coarse classifier's MARKET_KEYWORDS
    # list doesn't cover every broad-market term (e.g. "nifty"/"sensex"), so
    # gating these on domain == "market" silently dropped real market
    # queries to the general fallback. is_broad_market_query and
    # is_equity_research_query are the precise checks; domain is only the
    # fallback for Module 1 vs Module 2 vs general.
    if is_intelligence_query(query, ticker) and (response := company_intelligence(query)):
        pass
    elif is_equity_research_query(query, ticker) or is_intelligence_query(query, ticker):
        response = equity_research_pipeline(query, user_id=session_id)
    elif is_broad_market_query(query):
        response = market_pipeline(query)
    elif domain == "finance":
        response = _with_news(query, finance_pipeline, user_id=session_id)
    elif domain == "tutor":
        # "what is the weather in Paris" matches the generic "what is ..." tutor pattern, so the off-topic guard must see these too
        guard = classify_domain(query)
        if guard["available"] and guard["allowed"] is False and guard["confidence"] >= CONFIDENCE_THRESHOLD:
            response = build_refusal_response(query, guard)
            save_turn(session_id, query, response)
            return response
        response = _with_news(query, tutor_pipeline, user_id=session_id)
    elif domain == "market":
        # domain says market but neither precise check matched (rare) --
        # equity research is the closer fallback of the two.
        response = equity_research_pipeline(query, user_id=session_id)
    else:
        # Nothing above matched -- the query didn't hit any finance/market
        # keyword or precise company/ticker check. This is exactly the
        # "could be genuinely off-topic" tier, so it's where
        # shared/domain_guard.py's pre-check applies: a confidently
        # non-finance query (e.g. "write me a Python program", "who won
        # the cricket match") is refused here, before spending a real LLM
        # call on it. An ambiguous or guard-unavailable query (including
        # every existing test, whose mocked LLM doesn't return classifier
        # JSON) falls through unchanged to tutor_pipeline's general
        # fallback, whose prompt (ai/llm/prompt_templates.py's
        # tutor_prompt) already answers while pivoting toward a finance/
        # business/company/management angle instead of hard-refusing every
        # borderline question -- see shared/domain_guard.py's docstring for
        # the full three-tier rationale.
        guard = classify_domain(query)
        if guard["available"] and guard["allowed"] is False and guard["confidence"] >= CONFIDENCE_THRESHOLD:
            response = build_refusal_response(query, guard)
            save_turn(session_id, query, response)
            return response

        response = _with_news(query, tutor_pipeline, user_id=session_id)
        response["domain"] = "general"
        if guard["available"]:
            response["domain_guard"] = guard

    if pending_before and get_session(session_id).get("finance_pending") is pending_before:
        get_session(session_id).pop("finance_pending")  # our question went unanswered for a turn: stop expecting a bare reply

    # Output Guard -- runs for every response that wasn't already a refusal
    # (that path returned early above), regardless of which branch produced
    # it. Non-blocking: attaches metadata for transparency/demo purposes,
    # never rewrites or discards the answer -- see shared/domain_guard.py's
    # validate_output docstring for why.
    # (skipped in the Live Avatar: it is a transparency extra that costs a model call, and a spoken reply is already late)
    output_guard = validate_output(query, response.get("response", "")) if mode != "Live Avatar" else {"available": False}
    if output_guard["available"]:
        response["domain_guard_output"] = output_guard

    save_turn(session_id, query, response)
    return response


def handle_query(query: str, session_id: str = "default", mode: str = "Normal Mode") -> dict[str, Any]:
    """Read how the user seems to feel (shared/human_state.py), then answer with a matching tone. A self-harm message gets a
    fixed caring reply with no model and no finance, even when tone adaptation is off. Routing and tools get the original query."""
    session = get_session(session_id)
    if human_state.is_crisis(query):
        response = {"domain": "care", "query": query, "response": human_state.CARE_REPLY, "tone": {"strategy": "care", "format": "prose"}}
        save_turn(session_id, query, response)
        return response
    if not session.get("adapt_tone", True):
        return _handle(query, session_id, mode)
    support = False
    try:
        owner = user_store.current_owner.get() or session_id
        state = human_state.analyze(query, session.get("human"))
        prefs, episodes = user_store.get_style(owner)
        plan = human_state.choose(state, prefs)
        new_prefs = human_state.learn_prefs(query, prefs, state["trajectory"]["hing"])
        block = None
        if plan or new_prefs:
            goals = (user_store.get_financial_profile(owner) or {}).get("goals") if plan else None
            block = human_state.style_block(state, plan, goals, new_prefs, episodes)
        if plan:
            episodes = human_state.add_episode(episodes, state, plan, date.today().isoformat())
        support = bool(plan) and plan["strategy"] in ("reassure", "listen") and state["intent"] not in ("question", "decision")             and not finance_intent(query) and not finance_statement(query)
        if plan or new_prefs != prefs:
            user_store.save_style(owner, new_prefs, episodes)
        session["human"] = state["trajectory"]
        logger.info(f"tone strategy={plan and plan['strategy']}")
    except Exception as exc:  # the tone layer must never break an answer
        logger.warning(f"tone layer skipped: {type(exc).__name__}")
        block, plan = None, None
    with human_state.voice(block, plan):
        if plan and plan["strategy"] == "ask":  # a bare "Fine." is a check-in moment: fixed warm reply, no model, no routing
            response = {"domain": "smalltalk", "query": query, "response": human_state.check_in(len(session.get("history", [])), state["hinglish"])}
            save_turn(session_id, query, response)
        elif support:
            response = _support_reply(query, user_store.get_financial_profile(owner) or {}, state["hinglish"], len(session.get("history", [])))
            save_turn(session_id, query, response)
        else:
            response = _handle(query, session_id, mode)
    if plan:
        response["tone"] = {"strategy": plan["strategy"], "format": plan["format"]}
    return response


class Orchestrator:
    """Small class wrapper for callers that prefer object style."""

    def handle(self, user_input: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        session_id = str((context or {}).get("session_id", "default"))
        return handle_query(user_input, session_id=session_id)
