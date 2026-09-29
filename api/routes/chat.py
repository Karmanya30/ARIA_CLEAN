"""Chat endpoints -- the direct API replacement for what
interface/streamlit_app.py's _render_chat_tab used to do in-process."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from api.audio_store import register
from api.text_utils import speech_text

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    session_id: str
    mode: str = "Normal Mode"
    # Device-level id the frontend keeps in localStorage: saved research reports belong to it, not to
    # the per-tab session, so they survive closing the tab.
    owner_id: str | None = None


@router.post("")
def send_message(req: ChatRequest) -> dict[str, Any]:
    from core.orchestrator import handle_query
    from shared.user_store import current_owner

    token = current_owner.set(req.owner_id)
    try:
        result = handle_query(req.query.strip(), session_id=req.session_id, mode=req.mode)
    finally:
        current_owner.reset(token)
    response_text = result.get("response", "No response generated.")

    # TTS runs for every response regardless of mode (matches the original
    # Streamlit app's behavior -- Normal Mode also got a playable audio
    # clip, not just Conversational Mode; only the 3D avatar overlay was
    # mode-gated).
    audio_token = None
    try:
        from ai.llm.audio_script import generate_audio_script
        from ai.speech.tts import synthesize

        audio_script = generate_audio_script(response_text)
        audio_path = synthesize(speech_text(audio_script))
        if audio_path:
            audio_token = register(audio_path)
    except Exception as exc:
        logger.warning(f"TTS generation failed; returning text-only response: {exc}")

    result["audio_token"] = audio_token
    return result


@router.get("/history")
def get_history(session_id: str) -> dict[str, Any]:
    from core.session import get_session

    # POST /api/chat returns audio_token at the TOP level of its response
    # (attached after handle_query() already ran, once TTS finishes) --
    # but save_turn() only ever stored the nested response["audio_token"],
    # and this route used to hand back the raw session dict verbatim. Any
    # turn loaded through here (not just appended locally after a fresh
    # send -- e.g. after switching away from the Chat tab and back, which
    # remounts it and re-fetches) silently lost audio_token at the shape
    # the frontend actually reads it from: the <audio> replay control and
    # the Conversational Mode avatar's "most recent turn" lookup both went
    # quietly empty for any turn that wasn't just sent in the current
    # component's lifetime.
    session = get_session(session_id)
    history = [
        {**turn, "audio_token": turn.get("response", {}).get("audio_token")}
        for turn in session.get("history", [])
    ]
    return {**session, "history": history}


@router.post("/clear")
def clear_chat(req: dict[str, str]) -> dict[str, str]:
    from core.session import clear_session

    session_id = req["session_id"]
    clear_session(session_id)

    # Tavus bills per active-conversation minute -- end it on clear too,
    # same reasoning as the old Streamlit "Clear Chat" button.
    try:
        from api.routes.avatar import end_tavus_for_session

        end_tavus_for_session(session_id)
    except Exception as exc:
        logger.debug(f"No Tavus conversation to end for {session_id}: {exc}")

    return {"status": "cleared"}
