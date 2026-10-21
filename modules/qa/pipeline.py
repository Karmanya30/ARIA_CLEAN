"""THE answer pipeline. Every question ARIA answers, from any screen or voice, goes through `answer()`:

    understand   spelling / text-speak / Hinglish normalisation, crisis and small-talk detection   (shared/understand.py)
    context      owner + conversation memory (core/session.py), the finance profile, the page/instrument/company/news
                 item in focus, the market snapshot                                                   (modules/qa/focus.py)
    answer       core/orchestrator.py routes by intent to finance / tutor / market / equity research / company
                 intelligence / general; a focus (instrument, news item) replaces the routing but keeps the same
                 crisis, small-talk and dialogue handling
    ground       no number outside the fetched data; "unavailable" stated honestly; degraded replies, never raw errors
    trust        one not-investment-advice line, one accuracy caveat, trust tags                       (modules/qa/trust.py)
    persist      the turn is saved per owner and session (replayed on a repeated request_id)
    present      mode/channel only: a spoken rewrite for the avatar modes, a background audio clip   (modules/qa/present.py)

The chat modes and channels change only the `present` stage. One structured log line per answer carries the stage timings.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from loguru import logger

from ai.llm.groq_client import llm_stats

from modules.qa import present, trust
from modules.qa.models import Focus, QAContext, QARequest, QAResponse, active_focus

LOG_PREFIX = "qa.answer"


def understand(query: str, correct: bool = True) -> tuple[str, list]:
    """The normalised query every channel routes with (the original stays the display / history text)."""
    from shared.understand import normalize

    return normalize(query) if correct else (query, [])


def _run(req: QARequest, text: str, stages: dict[str, int]) -> dict[str, Any]:
    from core.orchestrator import handle_query
    from core.session import get_session

    get_session(req.session_id)["adapt_tone"] = req.adapt_tone
    started = time.perf_counter()
    ctx = req.context
    token = active_focus.set(Focus(context=ctx, owner_id=req.owner_id, history=req.history) if _focus_label(ctx) else None)
    try:
        result = handle_query(req.query, session_id=req.session_id, mode=req.mode.value, correct=req.correct)
    finally:
        active_focus.reset(token)
    stages["answer_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def _finish(result: dict[str, Any], req: QARequest, text: str, changes: list, stages: dict[str, int], t0: float) -> dict[str, Any]:
    started = time.perf_counter()
    if trust.failed(result.get("response")) and result.get("domain") != "company_intelligence" and "response" in result:
        result["response"], result["degraded"] = trust.DEGRADED, True
    result["grounding"] = trust.enforce(result)
    trust.finalize(result)
    stages["trust_ms"] = round((time.perf_counter() - started) * 1000)
    result["qa"] = {"pipeline": "qa.v1", "channel": req.channel.value, "mode": req.mode.value, "route": result.get("domain"),
                    "normalized_query": text, "corrected": text != req.query, "focus": _focus_label(req.context),
                    "latency_ms": {**stages, "total_ms": round((time.perf_counter() - t0) * 1000)}}
    return result


def _focus_label(ctx: QAContext) -> str | None:
    return ("instrument" if ctx.instrument_id else "news_item" if ctx.headline else "company" if ctx.company or ctx.report_id else None)


def _precheck(req: QARequest) -> None:
    """Before any provider runs: the conversation must belong to this owner, and a named instrument must exist."""
    from shared.conversation_memory import conversation

    conversation(req.session_id)  # PermissionError for someone else's conversation
    if req.context.instrument_id:
        from modules.market import instruments

        instruments.resolve(req.context.instrument_id)  # NotFound -> 404


def answer(req: QARequest) -> QAResponse:
    """The one entry point. Raises PermissionError (conversation owned by someone else), ValueError (request_id reused for a
    different message) and modules.market.instruments.NotFound (unknown instrument); the endpoints map them to 403/409/404."""
    from core.session import execute_turn
    from shared.user_store import current_owner

    t0 = time.perf_counter()
    query = req.query.strip()
    req = req.model_copy(update={"query": query})
    text, changes = understand(query, req.correct)
    stages: dict[str, int] = {"understand_ms": round((time.perf_counter() - t0) * 1000)}
    owner = current_owner.set(req.owner_id)
    stats_token = llm_stats.set(stages)  # the model calls of this turn add llm_calls / llm_ms to the stage timings
    try:
        _precheck(req)
        result = execute_turn(req.session_id, query, lambda: present.present(_finish(_run(req, text, stages), req, text, changes, stages, t0), req),
                              req.request_id)
    finally:
        llm_stats.reset(stats_token)
        current_owner.reset(owner)
    total = round((time.perf_counter() - t0) * 1000)
    g = result.get("grounding") or {}
    logger.bind(channel=req.channel.value, mode=req.mode.value, route=result.get("domain"), total_ms=total).info(
        f"{LOG_PREFIX} channel={req.channel.value} mode={req.mode.name} focus={_focus_label(req.context)} route={result.get('domain')} "
        f"corrected={text != query} grounded={g.get('passed')} checked={g.get('numbers_checked')} degraded={bool(result.get('degraded'))} "
        f"qlen={len(query)} stages={(result.get('qa') or {}).get('latency_ms')} total_ms={total}")
    return QAResponse.model_validate({"domain": "general", "query": query, "response": "", **result})


def lookup(req: QARequest, fetch: Callable[[str], dict[str, Any] | None]) -> dict[str, Any] | None:
    """Deterministic data answers (company intelligence): same normalisation, owner scope, trust tags and log line, no model."""
    from shared.user_store import current_owner

    t0 = time.perf_counter()
    text, _ = understand(req.query.strip(), req.correct)
    owner = current_owner.set(req.owner_id)
    try:
        result = fetch(text)
    finally:
        current_owner.reset(owner)
    if result is not None:
        result["qa"] = {"pipeline": "qa.v1", "channel": req.channel.value, "mode": req.mode.value, "route": result.get("domain"),
                        "normalized_query": text, "corrected": text != req.query.strip(),
                        "latency_ms": {"total_ms": round((time.perf_counter() - t0) * 1000)}}
        trust.finalize(result)
    logger.info(f"{LOG_PREFIX} channel={req.channel.value} lookup route={(result or {}).get('domain')} "
                f"corrected={text != req.query.strip()} qlen={len(req.query)} total_ms={round((time.perf_counter() - t0) * 1000)}")
    return result
