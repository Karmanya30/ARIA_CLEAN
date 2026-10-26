"""Thin orchestrator for ARIA."""

import contextvars
import os
import re
from concurrent.futures import ThreadPoolExecutor
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
from shared.understand import goal, normalize, spelled, suggest
from shared.human_state import current_voice_block
from shared.news import format_headlines, news_context
from shared.domain_guard import validate_output
from shared.intent_resolver import current_interpretation
from modules.qa.lookup import is_data_question
from modules.qa.models import active_focus
from shared.dialogue import act as dialogue_act, clean as clean_reply, confirmation, general_task, CONVERSATION_SYSTEM

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
            "Answer identity/capability questions truthfully. Do not force a financial topic or "
            "repeatedly ask how you can help. You can help with general questions too."
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

    reply = generate_response(query, system_prompt=_SUPPORT_SYSTEM + (" The user writes Hinglish: answer in simple Hinglish in Roman letters only, never Devanagari." if hinglish else "")) or ""
    norm = lambda t: {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", t)}
    if reply.lower().startswith("error") or _INVENTED.search(reply) or re.search("[ऀ-ॿ]", reply) or not norm(reply) <= norm(query) | norm(str(profile)):
        options = _SAFE_SUPPORT_HI if hinglish else _SAFE_SUPPORT
        reply = options[turn % len(options)]
    return {"domain": "support", "query": query, "response": reply}


def _handle(query: str, session_id: str = "default", mode: str = "Normal Mode", original: str | None = None) -> dict[str, Any]:
    """Route a user query (already spelling-corrected) to the correct module pipeline. `original` is what the user typed:
    it is what history and the response show."""
    shown = original or query

    if interpreted := current_interpretation.get():
        route = interpreted.intent
        standalone = interpreted.standalone_query
        if route == "finance":
            # The model supplies intent only; fact extraction always sees the user's words.
            response = _with_news(shown, finance_pipeline, user_id=session_id, intent_query=standalone)
        elif route == "market":
            response = market_pipeline(standalone)
        elif route == "equity_research":
            ticker = resolve_company(standalone)
            response = company_intelligence(standalone) if is_intelligence_query(standalone, ticker) else None
            if not response:
                response = equity_research_pipeline(standalone, user_id=session_id)
        elif route == "tutor":
            response = _with_news(standalone, tutor_pipeline, user_id=session_id)
        else:
            response = _with_news(standalone, _general_reply)
        response["query"] = shown
        save_turn(session_id, shown, response)
        return response

    if general_task(query):
        get_session(session_id).pop("finance_pending", None)
        response = _general_reply(query)
        response["query"] = shown
        save_turn(session_id, shown, response)
        return response

    focus = active_focus.get()
    if focus and (focus.context.instrument_id or focus.context.headline) and not _is_smalltalk(query):
        # The user is looking at one instrument / news item: same understanding, memory, tone and persistence as everywhere,
        # but the subject is already known, so the question is answered from that item's facts (modules/qa/focus.py).
        from modules.qa import focus as qa_focus
        history = None if get_session(session_id).get("history") else focus.history
        if focus.context.instrument_id:
            response = qa_focus.instrument_answer(focus.context.instrument_id, query, focus.owner_id, history)
        else:
            response = qa_focus.headline_answer(focus.context.headline, query, history)
        if not response["grounding"].get("deterministic") and (guard := _output_guard(query, response.get("response", "")))["available"]:
            response["domain_guard_output"] = guard
        response["query"] = shown
        save_turn(session_id, shown, response)
        return response
    if focus and _ABOUT_IT.search(query) and not _is_smalltalk(query) and not resolve_company(query) and (hint := _focus_company(focus)):
        query = f"{query} (company: {hint})"  # "is it expensive?" on a company/report page means that company

    # Historical evidence is assembled for every mode by execute_turn.
    from shared.conversation_memory import active_context, _FOLLOWUP
    evidence = active_context.get()
    if re.search(r"\b(it|its|this company|that company)\b", query, re.I) and not resolve_company(query):
        subjects = {ticker for turn in get_session(session_id).get("history", [])[-2:]
                    if (ticker := resolve_company(turn["query"]))}
        if len(subjects) == 1:
            query = f"{query} (company: {next(iter(subjects))})"
    ticker = resolve_company(query)
    needs_research = is_equity_research_query(query, ticker) or is_broad_market_query(query) or is_intelligence_query(query, ticker)
    if evidence and evidence["text"] and _FOLLOWUP.search(query) and not needs_research and not _is_smalltalk(query) and not get_session(session_id).get("finance_pending") and not finance_intent(query) and not finance_statement(query):
        response = _with_news(query, _general_reply)
        response["query"] = shown
        save_turn(session_id, shown, response)
        return response

    if _is_smalltalk(query):
        response = _smalltalk_reply(query)
        response["query"] = shown
        save_turn(session_id, shown, response)
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
    elif not by_intent and not ticker and (response := _data_lookup(shown, query, session_id)):
        pass  # a data question about a name outside the hard-coded list: instrument catalogue, then web search
    elif domain == "finance":
        response = _with_news(query, finance_pipeline, user_id=session_id)
    elif domain == "tutor":
        # Category classification is not a safety check and must not block valid questions.
        response = _with_news(query, tutor_pipeline, user_id=session_id)
    elif domain == "market":
        # domain says market but neither precise check matched (rare) --
        # equity research is the closer fallback of the two.
        response = equity_research_pipeline(query, user_id=session_id)
    else:
        if suggestions := suggest(query):
            response = {"domain": "clarify", "query": shown, "response": "Did you mean: " + " / ".join(suggestions) + "?", "suggestions": suggestions}
            save_turn(session_id, shown, response)
            return response
        else:
            response = _with_news(query, _general_reply)

    if pending_before and get_session(session_id).get("finance_pending") is pending_before:
        get_session(session_id).pop("finance_pending")  # our question went unanswered for a turn: stop expecting a bare reply

    # Output Guard -- runs for every response that wasn't already a refusal
    # (that path returned early above), regardless of which branch produced
    # it. Non-blocking: attaches metadata for transparency/demo purposes,
    # never rewrites or discards the answer -- see shared/domain_guard.py's
    # validate_output docstring for why.
    # Same for every mode: bounded wait, so a slow classifier costs a missing tag, never a late reply.
    output_guard = _output_guard(query, response.get("response", ""))
    if output_guard["available"]:
        response["domain_guard_output"] = output_guard

    response["query"] = shown
    save_turn(session_id, shown, response)
    return response


def _data_lookup(shown: str, query: str, session_id: str) -> dict[str, Any] | None:
    """modules/qa/lookup.py; a failure there only means the normal routing carries on."""
    from modules.qa import lookup
    try:
        history = [{"query": t.get("query"), "response": (t.get("response") or {}).get("response")} for t in get_session(session_id).get("history", [])[-3:]]
        return lookup.data_answer(shown, query, user_store.current_owner.get() or session_id, history)
    except Exception as exc:
        logger.warning(f"data lookup skipped: {type(exc).__name__}: {str(exc)[:120]}")
        return None


_ABOUT_IT = re.compile(r"\b(it|its|this|that|the company|the stock|the report|p/?e|pe ratio|price|valuation|revenue|profit|debt|expensive|cheap|risks?|outlook|score|sentiment|management)\b", re.I)


def _focus_company(focus) -> str | None:
    from modules.qa.focus import company_hint
    return company_hint(focus.context)


_GUARD_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="aria-guard")
GUARD_TIMEOUT_S = float(os.getenv("ARIA_OUTPUT_GUARD_TIMEOUT_S", "3"))


def _output_guard(query: str, text: str) -> dict[str, Any]:
    future = _GUARD_POOL.submit(contextvars.copy_context().run, validate_output, query, text)
    try:
        return future.result(timeout=GUARD_TIMEOUT_S)
    except Exception as exc:  # timeout or classifier failure: the tag is a transparency extra, never required
        logger.warning(f"output guard skipped: {type(exc).__name__}")
        return {"available": False}


def _general_reply(query: str) -> dict[str, Any]:
    from ai.llm.groq_client import generate_response
    from shared.conversation_memory import augment
    system = CONVERSATION_SYSTEM
    if voice := current_voice_block():
        system += "\n\n" + voice
    reply = generate_response(augment(query, system), system_prompt=system)
    return {"domain": "general", "query": query, "response": reply}


def _dialogue_reply(query: str, kind: str, session_id: str) -> dict[str, Any]:
    """Short social replies never become a lesson, a new valuation or an invented fact."""
    session = get_session(session_id)
    pending = session.get("finance_pending")
    if pending and pending.get("confirm") and confirmation(query) is not None:
        response = finance_pipeline(query, user_id=session_id)
    elif pending and kind == "decline":
        session.pop("finance_pending", None)
        response = {"domain": "smalltalk", "response": "No problem. We can leave that there."}
    elif pending and kind == "clarify":
        response = _general_reply(query)
    elif pending and pending.get("confirm"):
        response = {"domain": "smalltalk", "response": "I haven't changed it. Say yes to confirm the proposed update, or no to keep the current value."}
    elif pending:
        # An acknowledgement is not a numeric answer. Keep the question recoverable.
        field = pending.get("field", "missing detail").replace("_", " ").replace(".", " ")
        response = {"domain": "smalltalk", "response": f"Okay. When you're ready, share your {field} so I can continue."}
    elif kind == "acknowledge":
        history = session.get("history", [])
        previous = str(history[-1]["response"].get("response", "")) if history else ""
        offer = re.search(r"(?:would you like|shall i|want me to|should i|can i)\b[^?]*\?\s*$", previous, re.I)
        if offer and clean_reply(query) in {"ok", "okay", "sounds good", "alright"}:
            response = _general_reply(query)
        else:
            response = {"domain": "smalltalk", "response": "You're welcome." if "thank" in query.lower() or clean_reply(query) in ("thx", "ty") else "Okay."}
    elif kind == "decline":
        if session.get("history") and clean_reply(query) in {"no", "nope", "nah", "n", "nahi"}:
            response = _general_reply(query)
        else:
            response = {"domain": "smalltalk", "response": "No problem. We can leave that there."}
    elif not session.get("history"):
        response = {"domain": "smalltalk", "response": "What would you like me to explain?" if kind == "clarify" else "What would you like to continue with?"}
    else:
        # The current context contains both sides of the preceding exchange.
        response = _general_reply(query)
    response["query"] = query
    save_turn(session_id, query, response)
    return response


def handle_query(query: str, session_id: str = "default", mode: str = "Normal Mode", correct: bool = True) -> dict[str, Any]:
    from core.session import execute_turn
    return execute_turn(session_id, query, lambda: _handle_query(query, session_id, mode, correct))


def _handle_query(query: str, session_id: str = "default", mode: str = "Normal Mode", correct: bool = True) -> dict[str, Any]:
    """Read how the user seems to feel (shared/human_state.py), then answer with a matching tone. A self-harm message gets a
    fixed caring reply with no model and no finance, even when tone adaptation is off. Routing and tools get the spelling-,
    text-speak- and Hinglish-normalised query (shared/understand.py; amounts are never altered); the tone layer, history and
    display keep the original. `correct=False` routes the original text as typed."""
    session = get_session(session_id)
    text, changes = normalize(query) if correct else (query, [])
    if human_state.is_crisis(query) or human_state.is_crisis(text):
        response = {"domain": "care", "query": query, "response": human_state.CARE_REPLY, "tone": {"strategy": "care", "format": "prose"}}
        save_turn(session_id, query, response)
        return response
    if kind := dialogue_act(query):
        return _dialogue_reply(query, kind, session_id)
    if general_task(text):
        return _handle(text, session_id, mode, original=query)
    if (focus := active_focus.get()) and (focus.context.instrument_id or focus.context.headline):
        return _tone_and_handle(query, text, session, session_id, mode)  # the subject is the item in focus: nothing to resolve
    from shared.intent_resolver import resolve
    ticker = resolve_company(text)
    clear_route = bool(_is_smalltalk(text) or finance_intent(text) or finance_statement(text)
                       or is_equity_research_query(text, ticker) or is_broad_market_query(text)
                       or is_intelligence_query(text, ticker) or _CONCEPT_QUESTION.match(text.lower()))
    interpreted, diagnostic = resolve(text, session.get("history", []), session.get("finance_pending"), clear_route=clear_route)
    if interpreted and interpreted.intent == "clarify":
        response = {"domain": "clarify", "query": query, "response": interpreted.clarification_question,
                    "intent_resolution": diagnostic}
        save_turn(session_id, query, response)
        return response
    if interpreted:
        from shared.conversation_memory import context_for
        token = current_interpretation.set(interpreted)
        try:
            # Retrieve evidence for the resolved subject too, rather than a bare pronoun.
            with context_for(session_id, interpreted.standalone_query):
                response = _tone_and_handle(query, text, session, session_id, mode)
        finally:
            current_interpretation.reset(token)
    else:
        response = _tone_and_handle(query, text, session, session_id, mode)
    if diagnostic["attempted"]:
        response["intent_resolution"] = diagnostic
    if spelled(changes) and response.get("domain") not in ("refused", "clarify", "care", "smalltalk"):
        response["corrected_query"] = text
    return response


def _tone_and_handle(query: str, text: str, session: dict, session_id: str, mode: str) -> dict[str, Any]:
    if not session.get("adapt_tone", True) or session.get("finance_pending"):  # a bare "about 50k" answers our question: no tone read
        return _handle(text, session_id, mode, original=query)
    support = False
    try:
        owner = user_store.current_owner.get() or session_id
        state = human_state.analyze(query, session.get("human"))
        hit = finance_intent(text)
        state["goal"] = goal(text, hit, state["intent"])
        prefs, episodes = user_store.get_style(owner)
        plan = human_state.choose(state, prefs)
        new_prefs = human_state.learn_prefs(query, prefs, state["trajectory"]["hing"])
        block = None
        if plan or new_prefs:
            goals = (user_store.get_financial_profile(owner) or {}).get("goals") if plan else None
            block = human_state.style_block(state, plan, goals, new_prefs, episodes)
        if plan:
            episodes = human_state.add_episode(episodes, state, plan, date.today().isoformat())
        support = current_interpretation.get() is None and bool(plan) and plan["strategy"] in ("reassure", "listen") and state["intent"] not in ("question", "decision") and not hit and not finance_statement(text) and not is_data_question(text)
        if plan or new_prefs != prefs:
            user_store.save_style(owner, new_prefs, episodes)
        session["human"] = state["trajectory"]
        logger.info(f"tone strategy={plan and plan['strategy']}")
    except Exception as exc:  # the tone layer must never break an answer
        logger.warning(f"tone layer skipped: {type(exc).__name__}")
        block, plan = None, None
    with human_state.voice(block, plan):
        if current_interpretation.get() is None and plan and plan["strategy"] == "ask":  # a bare "Fine." is a check-in moment: fixed warm reply, no model, no routing
            response = {"domain": "smalltalk", "query": query, "response": human_state.check_in(len(session.get("history", [])), state["hinglish"])}
            save_turn(session_id, query, response)
        elif support:
            response = _support_reply(query, user_store.get_financial_profile(owner) or {}, state["hinglish"], len(session.get("history", [])))
            save_turn(session_id, query, response)
        else:
            response = _handle(text, session_id, mode, original=query)
    if plan:
        response["tone"] = {"strategy": plan["strategy"], "format": plan["format"]}
    return response


class Orchestrator:
    """Small class wrapper for callers that prefer object style."""

    def handle(self, user_input: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        session_id = str((context or {}).get("session_id", "default"))
        return handle_query(user_input, session_id=session_id)
