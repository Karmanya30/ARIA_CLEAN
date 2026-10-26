"""Live Avatar: free, streaming voice conversation with a lip-synced 3D ARIA (a second option beside Tavus).

    browser mic -> Web Speech API (free, in Chrome/Edge) -> text
      -> WebSocket /api/live/ws -> Groq, streamed -> speakable chunks -> Kokoro TTS (local) -> audio chunks
      -> browser: TalkingHead 3D avatar, lip-synced from the audio itself (HeadAudio)

Nothing is rendered on a server GPU and nothing is paid for. Every utterance, small talk included, goes through the same
answer pipeline as the text chat (modules/qa/pipeline.py: normalisation, intent routing, memory, grounding, disclaimers,
persistence); this socket only presents the result. For anything but small talk ARIA says a short "let me check" line at
once while the pipeline works, then speaks the short spoken version of the written answer, sentence by sentence.
"""
from __future__ import annotations

import asyncio
import base64
import random
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger

from modules.qa import pipeline
from modules.qa.models import Channel, ChatMode, QARequest

router = APIRouter(tags=["live-avatar"])

_AVATAR_DIR = Path(__file__).resolve().parents[2] / "interface" / "avatar"

# Said at once while a module works, so the user hears a response well inside 3 seconds.
FILLERS = ("Let me check that for you.", "Good question, give me a second.", "Sure, let me pull that up.")
FILLERS_LATER = ("Still putting that together.", "Almost there.", "This one has a lot of detail, bear with me.", "Nearly done.")

# First chunk: speak as soon as there is a natural pause after a few words. Later chunks: whole sentences.
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_SOFT_BREAK = re.compile(r"[,;:—–](?=\s)")
FIRST_CHUNK_MIN, CHUNK_MAX = 24, 220
_MARKUP = re.compile(r"[*_#`>|~]+")


def split_ready(buf: str, first: bool) -> tuple[str | None, str]:
    """(chunk to speak now or None, remaining buffer). Pure, so the chunking rules have a test."""
    m = _SENTENCE_END.search(buf)
    if m:
        return buf[: m.end()].strip(), buf[m.end():]
    if first and len(buf) >= FIRST_CHUNK_MIN:
        soft = _SOFT_BREAK.search(buf, FIRST_CHUNK_MIN - 8)
        if soft:
            return buf[: soft.end()].strip(), buf[soft.end():]
    if len(buf) > CHUNK_MAX:
        cut = buf.rfind(" ", 0, CHUNK_MAX)
        if cut > 0:
            return buf[:cut].strip(), buf[cut:]
    return None, buf


def speakable(text: str) -> str:
    return re.sub(r"\s+", " ", _MARKUP.sub("", text)).strip()


TROUBLE = "Sorry, I'm having trouble reaching my thinking service right now. Please ask me again in a moment."


def _failed(text: str | None) -> bool:
    """generate_response() returns the text 'Error: ...' when every LLM backend is down; never read that out loud."""
    return not text or text.lstrip().lower().startswith("error")


async def _ask_pipeline(text: str, session_id: str, chunks: asyncio.Queue, on_wait, filler: bool) -> dict | None:
    """Runs the one answer pipeline (the same call /api/chat makes, in the Live Avatar mode) in a thread. For anything that is
    not small talk it says a short line at once, and again every few seconds, so the call never goes quiet; ``on_wait`` tells
    the page it is waiting. Returns the response, or None if the pipeline failed."""
    from shared.user_store import current_owner

    owner = current_owner.get()

    def run() -> dict:
        token = current_owner.set(owner)
        try:
            return pipeline.answer(QARequest(query=text, session_id=session_id, owner_id=owner, mode=ChatMode.LIVE,
                                             channel=Channel.AVATAR)).to_dict()
        finally:
            current_owner.reset(token)

    job = asyncio.create_task(asyncio.to_thread(run))
    try:
        if filler:
            await chunks.put(random.choice(FILLERS))
            await on_wait()
            for later in FILLERS_LATER * 2:  # a long equity report can take a minute: a line every 7 s, never a long silence
                done, _pending = await asyncio.wait({job}, timeout=7)
                if done:
                    break
                await chunks.put(later)
        return await job
    except asyncio.CancelledError:
        job.cancel()
        raise
    except Exception as exc:
        logger.warning(f"Live avatar: the answer pipeline failed ({type(exc).__name__}: {exc})")
        return None


async def _reply(ws: WebSocket, text: str, session_id: str, turn: int, lock: asyncio.Lock) -> None:
    spoken = await _reply_impl(ws, text, session_id, turn, lock)
    async with lock:
        await ws.send_json({"type": "done", "turn": turn, "text": spoken["response"], "timings": spoken["timings"]})


async def _reply_impl(ws: WebSocket, text: str, session_id: str, turn: int, lock: asyncio.Lock) -> dict:
    from ai.speech.live_tts import synthesize
    from core.orchestrator import is_smalltalk

    t0 = time.perf_counter()
    ms = lambda: round((time.perf_counter() - t0) * 1000)  # noqa: E731
    chunks: asyncio.Queue = asyncio.Queue()
    timings: dict[str, int] = {}

    async def send(obj: dict) -> None:  # text and audio chunks go out from two coroutines
        async with lock:
            await ws.send_json(obj)

    async def speak() -> None:
        seq = 0
        while (chunk := await chunks.get()) is not None:
            audio, mime = await asyncio.to_thread(synthesize, chunk)
            if seq == 0:
                timings["first_audio_ms"] = ms()
            await send({"type": "audio", "turn": turn, "seq": seq, "text": chunk, "mime": mime,
                        "audio": base64.b64encode(audio).decode("ascii"), "server_ms": ms()})
            seq += 1

    speaker = asyncio.create_task(speak())
    try:
        resp = await _ask_pipeline(text, session_id, chunks, lambda: send({"type": "thinking", "turn": turn}), not is_smalltalk(text))
        timings["modules_ms"] = ms()
        # The written answer is already saved (full text, per owner, like every channel); this is what is said aloud.
        full = speakable(str((resp or {}).get("spoken") or (resp or {}).get("response") or ""))
        if not full or _failed(full):
            full = TROUBLE
        timings["first_token_ms"] = ms()
        await send({"type": "text", "turn": turn, "delta": full})
        buf, first = full, True
        while True:
            chunk, buf = split_ready(buf, first)
            if not chunk:
                break
            if said := speakable(chunk):
                await chunks.put(said)
                first = False
        if said := speakable(buf):
            await chunks.put(said)
        await chunks.put(None)
        await speaker
        timings["total_ms"] = ms()
        logger.info(f"Live avatar turn: {timings}")
        return {"domain": "live_avatar", "query": text, "response": full, "timings": timings}
    except asyncio.CancelledError:
        speaker.cancel()
        raise


@router.websocket("/api/live/ws")
async def live_socket(ws: WebSocket) -> None:
    await ws.accept()
    task: asyncio.Task | None = None
    turn = 0
    lock = asyncio.Lock()
    try:
        while True:
            msg = await ws.receive_json()
            from api import auth
            if auth.mode() == "accounts":
                account = auth.principal(ws)  # also observes logout/expiry during a live socket
                if account is None or (msg.get("type") == "user" and msg.get("owner_id") != account["id"]):
                    await ws.close(code=1008, reason="Account session is unavailable or does not match.")
                    return
            if msg.get("type") in ("interrupt", "user") and task and not task.done():
                task.cancel()
            if msg.get("type") == "user" and str(msg.get("text", "")).strip():
                # The page numbers its own turns (it also bumps the number on an interrupt); echoing its number
                # back is what lets it drop chunks of a reply it has moved on from.
                turn = int(msg["turn"]) if str(msg.get("turn", "")).isdigit() else turn + 1
                from shared.user_store import current_owner
                token = current_owner.set(msg.get("owner_id"))
                try:
                    if auth.mode() == "accounts":
                        from shared.conversation_memory import conversation
                        try:
                            conversation(str(msg.get("session_id") or "live"))
                        except PermissionError:
                            await ws.close(code=1008, reason="This conversation belongs to another account.")
                            return
                    task = asyncio.create_task(_reply(ws, str(msg["text"]).strip()[:1000], str(msg.get("session_id") or "live"), turn, lock))
                finally:
                    current_owner.reset(token)
            elif msg.get("type") == "ping":
                async with lock:
                    await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if task and not task.done():
            task.cancel()


@router.get("/avatar/live", response_class=HTMLResponse)
def live_page() -> str:
    return (_AVATAR_DIR / "live.html").read_text(encoding="utf-8")


@router.get("/avatar/face.png")
def avatar_face() -> FileResponse:
    """The photo the live page animates (interface/avatar/face.png). Without it the page falls back to the 3D model."""
    path = next((p for p in (_AVATAR_DIR / "face.png", _AVATAR_DIR / "face.jpg") if p.exists()), None)
    if path is None:
        raise HTTPException(status_code=404, detail="No avatar photo configured.")
    return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg", headers={"Cache-Control": "no-cache"})


@router.get("/avatar/glasses.png")
def avatar_glasses() -> FileResponse:
    """Optional transparent overlay drawn over the photo (scripts/make_glasses.py). 404 means: no glasses."""
    path = _AVATAR_DIR / "glasses.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No glasses overlay configured.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/avatar/model.glb")
def avatar_model() -> FileResponse:
    return FileResponse(_AVATAR_DIR / "model.glb", media_type="model/gltf-binary", headers={"Cache-Control": "max-age=86400"})
