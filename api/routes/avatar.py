"""Avatar endpoints -- the free, self-hosted TalkingHead 3D avatar
(default) and the opt-in paid Tavus CVI mode.

Tavus used to run as a separate FastAPI subprocess (spawned by the old
Streamlit app) with its own ngrok tunnel, torn down and recreated per
mode-switch. Killing that subprocess forcefully (the only option on
Windows) never gave pyngrok's own ngrok.exe child a chance to run its
cleanup, orphaning it -- and since this account's ngrok domain is a
static reserved one, an orphan permanently squats on it until killed by
hand ("endpoint already online" on every later attempt). Now that
everything lives in one long-running API process, the ngrok tunnel's
lifetime is tied to *this* process instead of a disposable child, which
removes that whole bug class rather than working around it.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel

router = APIRouter(tags=["avatar"])

TAVUS_API_KEY = os.environ.get("TAVUS_API_KEY")
TAVUS_REPLICA_ID = os.environ.get("TAVUS_REPLICA_ID")
TAVUS_API_URL = "https://tavusapi.com/v2"
REQUEST_TIMEOUT = 15

_AVATAR_DIR = Path(__file__).resolve().parents[2] / "interface" / "avatar"
_PERSONA_CACHE_FILE = _AVATAR_DIR / ".tavus_persona_cache.json"

_NGROK_URL: str | None = None
_ACTIVE_CONVERSATION_ID: str | None = None


# ── Free avatar (TalkingHead) ────────────────────────────────────────────
@router.get("/avatar/render", response_class=HTMLResponse)
def render_avatar(audio_token: str | None = None):
    from api.audio_store import resolve
    from interface.avatar.render import build_avatar_html

    audio_path = resolve(audio_token) if audio_token else None
    return build_avatar_html(audio_path)


# ── Tavus CVI ─────────────────────────────────────────────────────────
def _require_env() -> None:
    missing = [
        name
        for name, val in [
            ("TAVUS_API_KEY", TAVUS_API_KEY),
            ("TAVUS_REPLICA_ID", TAVUS_REPLICA_ID),
            ("NGROK_AUTHTOKEN", os.environ.get("NGROK_AUTHTOKEN")),
        ]
        if not val
    ]
    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}. Add them to your .env file."
        )


def _tunnel_is_alive(url: str) -> bool:
    """A cached tunnel URL goes stale if the underlying ngrok.exe process
    dies outside of pyngrok's own bookkeeping -- e.g. killed directly
    (rather than via ngrok.disconnect()), or ngrok's free-tier session
    limit knocking it offline. pyngrok's in-memory tunnel object has no
    way to notice that on its own, so the dead URL would otherwise be
    reused silently for the rest of this process's life: every future
    Tavus conversation gets wired to a callback URL nothing is listening
    on, and the call drops shortly after connecting with no clear error
    on our side (found live -- "Call ended." right after "ARIA is here",
    right after an ngrok.exe process was killed out from under a still-
    running API process). Any HTTP response (even a 404 from our own
    FastAPI app, which has no route at "/") proves the tunnel is still
    forwarding; only a connection failure means it's actually dead."""
    try:
        requests.get(url, timeout=3)
        return True
    except requests.RequestException:
        return False


def _get_ngrok_url(port: int) -> str:
    """Lazily creates one tunnel for this process's lifetime -- Tavus's
    cloud only needs to reach us while CVI mode is actually in use, so
    there's no reason to hold a tunnel open (or even installed) for a
    session that never opens Tavus mode at all."""
    global _NGROK_URL
    if _NGROK_URL and _tunnel_is_alive(_NGROK_URL):
        return _NGROK_URL
    if _NGROK_URL:
        logger.warning(f"Cached ngrok tunnel {_NGROK_URL} is no longer reachable -- reconnecting.")
        _NGROK_URL = None

    from pyngrok import conf, ngrok
    from pyngrok.exception import PyngrokNgrokHTTPError

    token = os.environ.get("NGROK_AUTHTOKEN")
    pyngrok_config = conf.PyngrokConfig(auth_token=token)
    try:
        _NGROK_URL = ngrok.connect(port, pyngrok_config=pyngrok_config).public_url
    except PyngrokNgrokHTTPError as exc:
        if "already online" in str(exc):
            # This account's ngrok domain is a static reserved one -- if a
            # previous API process's ngrok.exe child got force-killed
            # (rather than shut down gracefully) it never got a chance to
            # release the domain, and stays orphaned holding it, blocking
            # every later tunnel attempt with an otherwise-opaque 502
            # ("Internal Server Error" to the browser) that gives no hint
            # what actually went wrong.
            raise RuntimeError(
                "ngrok's reserved domain is still held by an orphaned ngrok.exe "
                "from a previous run (likely force-killed rather than shut down "
                "cleanly). Stop that ngrok.exe process, then retry."
            ) from exc
        raise
    logger.info(f"ngrok tunnel created: {_NGROK_URL}")
    return _NGROK_URL


def _forget_persona() -> None:
    try:
        _PERSONA_CACHE_FILE.unlink()
    except OSError:
        pass


def _delete_persona(persona_id: str) -> None:
    """Best-effort: personas count against the Tavus account's limit, so a replaced one is removed."""
    try:
        requests.delete(f"{TAVUS_API_URL}/personas/{persona_id}", headers={"x-api-key": TAVUS_API_KEY}, timeout=REQUEST_TIMEOUT)
        logger.info(f"Deleted old Tavus persona: {persona_id}")
    except requests.RequestException as e:
        logger.warning(f"Failed to delete old Tavus persona {persona_id}: {e}")


def _end_orphaned_conversations() -> None:
    """End every conversation Tavus still reports as active. One left behind by a crashed or restarted API
    process (whose id this process never knew) keeps counting against the account's concurrent-conversation
    limit, so every new start fails even with credits left."""
    try:
        resp = requests.get(f"{TAVUS_API_URL}/conversations", params={"status": "active", "limit": 50},
                            headers={"x-api-key": TAVUS_API_KEY}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        active = [c["conversation_id"] for c in resp.json().get("data", []) if c.get("status") == "active"]
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning(f"Could not list active Tavus conversations: {e}")
        return
    for cid in active:
        logger.warning(f"Ending orphaned Tavus conversation {cid} before starting a new one")
        _end_conversation(cid)


def _get_or_create_persona(base_url: str) -> str:
    """Reuse a cached persona across conversations instead of creating a
    fresh one via the API every time a user opens Tavus CVI Mode -- Tavus's
    own persona-strategy guidance recommends reuse unless per-session
    behavior actually differs (ARIA's system prompt doesn't). Cache is
    keyed by base_url, which includes the session_id, so each distinct
    session still gets a persona whose llm.base_url actually resolves to
    it."""
    headers = {"x-api-key": TAVUS_API_KEY, "Content-Type": "application/json"}

    old = None
    if _PERSONA_CACHE_FILE.exists():
        try:
            cached = json.loads(_PERSONA_CACHE_FILE.read_text())
            if cached.get("base_url") == base_url and cached.get("persona_id"):
                logger.info(f"Reusing cached Tavus persona: {cached['persona_id']}")
                return cached["persona_id"]
            old = cached.get("persona_id")
        except (json.JSONDecodeError, OSError):
            pass

    pal_payload = {
        "persona_name": "ARIA Assistant",
        "system_prompt": (
            "You are ARIA, an AI-powered personal finance assistant covering "
            "personal finance, financial education, market analysis, and "
            "equity research. Keep spoken answers concise and conversational."
        ),
        "context": "The user is interacting through a conversational video interface.",
        "layers": {
            "llm": {"model": "aria-custom", "base_url": base_url, "api_key": "dummy-key"}
        },
        "default_replica_id": TAVUS_REPLICA_ID,
    }
    resp = requests.post(
        f"{TAVUS_API_URL}/personas", json=pal_payload, headers=headers, timeout=REQUEST_TIMEOUT
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to create Tavus persona: {resp.text}")

    persona_id = resp.json()["persona_id"]
    logger.info(f"Created Tavus persona: {persona_id}")
    _PERSONA_CACHE_FILE.write_text(json.dumps({"base_url": base_url, "persona_id": persona_id}))
    if old and old != persona_id:
        _delete_persona(old)
    return persona_id


class TavusStartRequest(BaseModel):
    session_id: str


@router.post("/api/tavus/start")
def start_tavus(req: TavusStartRequest, port: int = 8000) -> dict[str, str]:
    global _ACTIVE_CONVERSATION_ID
    _require_env()

    try:
        ngrok_url = _get_ngrok_url(port)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    base_url = f"{ngrok_url}/v1/{req.session_id}"
    logger.info(f"Using Custom LLM Base URL: {base_url}")

    headers = {"x-api-key": TAVUS_API_KEY, "Content-Type": "application/json"}
    _end_orphaned_conversations()

    def create(persona_id: str) -> requests.Response:
        return requests.post(f"{TAVUS_API_URL}/conversations", headers=headers, timeout=REQUEST_TIMEOUT, json={
            "replica_id": TAVUS_REPLICA_ID,
            "persona_id": persona_id,
            "conversation_name": "ARIA Session",
            # Belt-and-braces cost guard: end the call automatically if nobody
            # is on it or it runs unexpectedly long, rather than relying on
            # /api/tavus/end always being called from the frontend.
            "properties": {"max_call_duration": 900, "participant_left_timeout": 30},
        })

    try:
        resp = create(_get_or_create_persona(base_url))
        if 400 <= resp.status_code < 500:
            # The cached persona may have been deleted or changed on Tavus's side: start over with a fresh one.
            logger.warning(f"Tavus rejected the conversation ({resp.status_code}: {resp.text[:200]}); retrying with a new persona")
            _forget_persona()
            resp = create(_get_or_create_persona(base_url))
    except (RuntimeError, requests.RequestException) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Failed to create Tavus Conversation: {resp.text}")

    data = resp.json()
    _ACTIVE_CONVERSATION_ID = data["conversation_id"]
    logger.info(f"Created Tavus Conversation: {_ACTIVE_CONVERSATION_ID}")

    embed_url = f"/embed?conversation_url={quote(data['conversation_url'], safe='')}"
    return {"conversation_id": data["conversation_id"], "conversation_url": data["conversation_url"], "embed_url": embed_url}


def _end_conversation(conversation_id: str | None = None) -> None:
    global _ACTIVE_CONVERSATION_ID
    conversation_id = conversation_id or _ACTIVE_CONVERSATION_ID
    if not conversation_id or not TAVUS_API_KEY:
        return

    headers = {"x-api-key": TAVUS_API_KEY}
    try:
        requests.post(
            f"{TAVUS_API_URL}/conversations/{conversation_id}/end", headers=headers, timeout=REQUEST_TIMEOUT
        )
        logger.info(f"Ended Tavus Conversation: {conversation_id}")
    except requests.RequestException as e:
        logger.warning(f"Failed to end Tavus conversation {conversation_id}: {e}")
    finally:
        if conversation_id == _ACTIVE_CONVERSATION_ID:
            _ACTIVE_CONVERSATION_ID = None


def end_tavus_for_session(session_id: str) -> None:
    """Best-effort: this project runs one active Tavus conversation at a
    time in practice (single local demo user), so ending "the" active
    conversation is equivalent to ending this session's. Called from
    api/routes/chat.py's clear endpoint."""
    _end_conversation()


class TavusEndRequest(BaseModel):
    conversation_id: str | None = None


@router.post("/api/tavus/end")
def end_tavus(req: TavusEndRequest | None = None) -> dict[str, str]:
    # With an id, only that call ends: a late "end" from a restarted frontend must not kill the new call.
    _end_conversation(req.conversation_id if req else None)
    return {"status": "ended"}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool | None = False


def _chunk(model: str, created: int, delta: dict, finish_reason: str | None) -> str:
    payload = {
        "id": "chatcmpl-aria",
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_sse(text: str, model: str) -> AsyncIterator[str]:
    """Fake-streams a fully-computed response as OpenAI-style SSE chunks --
    Tavus's docs require the custom-LLM endpoint to be streamable via SSE;
    responding with a flat JSON blob regardless of `stream` (an earlier,
    broken version of this route) left the avatar silently unable to
    speak, confirmed live."""
    created = int(time.time())
    yield _chunk(model, created, {"role": "assistant"}, None)
    words = text.split(" ")
    for i, word in enumerate(words):
        piece = word + (" " if i < len(words) - 1 else "")
        yield _chunk(model, created, {"content": piece}, None)
    yield _chunk(model, created, {}, "stop")
    yield "data: [DONE]\n\n"


@router.post("/v1/{session_id}/chat/completions")
async def tavus_chat_completions(session_id: str, req: ChatCompletionRequest):
    # Note: no separate transcript store needed here. Tavus's callback and
    # the React frontend's own /api/chat both run in this one process now
    # (unlike the old Streamlit-subprocess split, which needed a SQLite
    # TavusTurn table just to cross a process boundary) -- handle_query()
    # already calls core.session.save_turn() internally, so the turn
    # lands in the same history GET /api/chat/history serves, and the
    # frontend can poll that one endpoint for both text and voice turns.
    from core.orchestrator import handle_query

    user_messages = [m for m in req.messages if m.role == "user"]
    query = user_messages[-1].content if user_messages else ""

    logger.info(f"Tavus queried ARIA [{session_id}]: {query}")

    try:
        from ai.llm.spoken import spoken_version

        result = handle_query(query, session_id=session_id, mode="Normal Mode")
        # the replica reads this aloud: labelled sections and bullets become a few natural sentences
        response_text = spoken_version(query, result.get("response", "I could not generate a response."))
    except Exception:
        logger.exception("Error in orchestrator while handling Tavus query")
        response_text = "I'm sorry, I encountered an internal error while processing that."

    if req.stream:
        return StreamingResponse(_stream_sse(response_text, req.model), media_type="text/event-stream")

    return {
        "id": "chatcmpl-aria",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response_text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@router.get("/embed", response_class=HTMLResponse)
def tavus_embed(conversation_url: str):
    """Serves the custom call UI (interface/avatar/tavus_embed.html) --
    daily-js's `createCallObject()` (not `createFrame()`) joins with zero
    built-in UI chrome, so this renders only the replica's video in a
    round "assistant" frame with our own mute/end buttons, instead of
    Tavus/Daily's default prebuilt call room."""
    template_path = _AVATAR_DIR / "tavus_embed.html"
    html = template_path.read_text(encoding="utf-8")
    return html.replace("__CONVERSATION_URL__", conversation_url)
