"""Chat endpoints. POST /api/chat is a thin adapter over the one answer pipeline (modules/qa/pipeline.py), exactly like
/api/instruments/ask, the live avatar, the Tavus callback and company intelligence: all of them build a QARequest and call
`answer()`; only presentation differs by mode."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from modules.qa import pipeline
from modules.qa.models import Channel, ChatMode, QAContext, QARequest

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    session_id: str = Field(min_length=1, max_length=200)
    request_id: str | None = Field(None, min_length=1, max_length=200)
    mode: str = ChatMode.NORMAL.value
    # Device-level id the frontend keeps in localStorage: saved research reports belong to it, not to
    # the per-tab session, so they survive closing the tab.
    owner_id: str | None = None
    adapt_tone: bool = True  # Settings > Conversation; crisis care replies ignore it
    correct: bool = True  # False = route the text exactly as typed (the chat's "use original" button)
    # Where the question comes from and what the user is looking at (instrument drawer, company page, news item).
    channel: Channel = Channel.CHAT
    context: QAContext | None = None
    history: list[dict[str, Any]] | None = Field(None, max_length=20)
    # Legacy field of the market news chip: a news item the question is about. Untrusted text; maps to context.headline.
    system_context: str | None = Field(None, max_length=16000)

    def to_qa(self) -> QARequest:
        ctx = self.context or QAContext()
        channel = self.channel
        if self.system_context and not ctx.headline:
            ctx = ctx.model_copy(update={"headline": self.system_context})
            channel = Channel.MARKET_CHIP if channel is Channel.CHAT else channel
        return QARequest(query=self.query, session_id=self.session_id, owner_id=self.owner_id, request_id=self.request_id,
                         mode=ChatMode.parse(self.mode), channel=channel, context=ctx, correct=self.correct,
                         adapt_tone=self.adapt_tone, history=self.history)


def answer_http(qa: QARequest) -> dict[str, Any]:
    """Runs the pipeline and maps its errors to HTTP statuses (shared by every endpoint that answers a question)."""
    from modules.market.instruments import NotFound

    if not qa.query.strip() or not qa.session_id.strip():
        raise HTTPException(422, "query and session_id must not be blank")
    try:
        return pipeline.answer(qa).to_dict()
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("")
def send_message(req: ChatRequest) -> dict[str, Any]:
    return answer_http(req.to_qa())



@router.get("/history")
def get_history(session_id: str, owner_id: str | None = None) -> dict[str, Any]:
    from shared.user_store import current_owner
    token = current_owner.set(owner_id)
    try:
        return _get_history(session_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    finally:
        current_owner.reset(token)


@router.get("/context")
def inspect_context(session_id: str, query: str, owner_id: str | None = None):
    import os
    if os.getenv("ARIA_CONTEXT_DEBUG", "0") != "1":
        raise HTTPException(404, "Context diagnostics disabled")
    from shared.user_store import current_owner
    from shared.conversation_memory import build_context
    token = current_owner.set(owner_id)
    try:
        return build_context(session_id, query)["diagnostics"]
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    finally:
        current_owner.reset(token)


def _get_history(session_id: str) -> dict[str, Any]:
    # POST /api/chat returns audio_token at the TOP level of its response (attached after the turn was saved) --
    # but the saved turn only holds the nested response, and this route used to hand back the raw session dict
    # verbatim. Any turn loaded through here (e.g. after switching away from the Chat tab and back) silently lost
    # audio_token at the shape the frontend reads it from.
    from shared.conversation_memory import load
    session = load(session_id)
    history = [
        {**turn, "audio_token": turn.get("response", {}).get("audio_token")}
        for turn in session.get("history", [])
    ]
    return {**session, "history": history}


@router.post("/clear")
def clear_chat(req: dict[str, str]) -> dict[str, str]:
    from core.session import clear_session

    session_id = req["session_id"]
    from shared.user_store import current_owner
    token = current_owner.set(req.get("owner_id"))
    try:
        clear_session(session_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    finally:
        current_owner.reset(token)

    # Tavus bills per active-conversation minute -- end it on clear too,
    # same reasoning as the old Streamlit "Clear Chat" button.
    try:
        from api.routes.avatar import end_tavus_for_session

        end_tavus_for_session(session_id)
    except Exception as exc:
        logger.debug(f"No Tavus conversation to end for {session_id}: {exc}")

    return {"status": "cleared"}
