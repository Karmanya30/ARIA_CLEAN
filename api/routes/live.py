"""Live Avatar: free, streaming voice conversation with a lip-synced 3D ARIA (a second option beside Tavus).

    browser mic -> Web Speech API (free, in Chrome/Edge) -> text
      -> WebSocket /api/live/ws -> Groq, streamed -> speakable chunks -> Kokoro TTS (local) -> audio chunks
      -> browser: TalkingHead 3D avatar, lip-synced from the audio itself (HeadAudio)

Nothing is rendered on a server GPU and nothing is paid for. Plain small talk is streamed straight from the LLM
(first word in ~1 s). Every other question goes through the real orchestrator (finance, tutor, market with live news,
equity research, domain guard), exactly like the text chat; ARIA says a short "let me check" line at once while the
module works, then speaks a short natural version of its written answer, streamed sentence by sentence.
"""
from __future__ import annotations

import asyncio
import base64
import os
import random
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger

from ai.llm.spoken import SPOKEN_SYSTEM, needs_rewrite, spoken_prompt

router = APIRouter(tags=["live-avatar"])

LIVE_MODEL = os.getenv("LIVE_LLM_MODEL", "openai/gpt-oss-20b")
HISTORY_TURNS = 4
_AVATAR_DIR = Path(__file__).resolve().parents[2] / "interface" / "avatar"

SYSTEM = (
    "You are ARIA, a warm Indian AI assistant for personal finance, investing, companies, management and "
    "consultancy, speaking out loud in a live video call. Answer in plain spoken English: short sentences, no "
    "markdown, lists, emojis, tables or symbols, and write numbers the way they are said. Use rupees, never "
    "dollars. Keep it under 70 words unless the user asks for more, then offer to go deeper. If a question is "
    "off-topic, answer briefly and bring it back to money, business or careers. If you do not have fresh data "
    "for a question, say so plainly instead of guessing."
)

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


def _messages(session_id: str, text: str) -> list[dict]:
    from core.session import get_session

    msgs = [{"role": "system", "content": SYSTEM}]
    for turn in get_session(session_id).get("history", [])[-HISTORY_TURNS:]:
        msgs.append({"role": "user", "content": str(turn.get("query", ""))[:600]})
        msgs.append({"role": "assistant", "content": str((turn.get("response") or {}).get("response", ""))[:600]})
    msgs.append({"role": "user", "content": text})
    return msgs


TROUBLE = "Sorry, I'm having trouble reaching my thinking service right now. Please ask me again in a moment."


def _failed(text: str | None) -> bool:
    """generate_response() returns the text 'Error: ...' when every LLM backend is down; never read that out loud."""
    return not text or text.lstrip().lower().startswith("error")


async def _ask_modules(text: str, session_id: str, chunks: asyncio.Queue, on_wait) -> str | None:
    """Runs the real orchestrator in a thread, saying a short line now (and again every few seconds if it takes long) so
    the call never goes quiet; ``on_wait`` tells the page it is waiting. Returns the written answer, or None if the
    modules failed (the caller then answers directly)."""
    from core.orchestrator import handle_query

    job = asyncio.create_task(asyncio.to_thread(handle_query, text, session_id, "Live Avatar"))
    try:
        await chunks.put(random.choice(FILLERS))
        await on_wait()
        for later in FILLERS_LATER * 2:  # a long equity report can take a minute: a line every 7 s, never a long silence
            done, _pending = await asyncio.wait({job}, timeout=7)
            if done:
                break
            await chunks.put(later)
        written = str((await job).get("response") or "").strip()
        return None if written.lower().startswith("error") else written or None
    except asyncio.CancelledError:
        job.cancel()
        raise
    except Exception as exc:
        logger.warning(f"Live avatar: the modules failed ({exc}); answering directly")
        return None


def _stream_llm(messages: list[dict], put, stop: threading.Event) -> None:
    """Runs in a thread: pushes text deltas, then None. Falls back to one non-streamed answer."""
    try:
        from ai.llm.groq_client import _make_groq_client

        stream = _make_groq_client().chat.completions.create(model=LIVE_MODEL, messages=messages, stream=True,
                                                             temperature=0.6, max_tokens=400, reasoning_effort="low")
        for event in stream:
            if stop.is_set():
                break
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                put(delta)
    except Exception as exc:
        logger.warning(f"Live avatar: streaming LLM failed ({exc}); using the non-streamed fallback")
        if not stop.is_set():
            from ai.llm.groq_client import generate_response

            answer = generate_response(messages[-1]["content"], system_prompt=SYSTEM)
            put(TROUBLE if _failed(answer) else answer)
    finally:
        put(None)


async def _reply(ws: WebSocket, text: str, session_id: str, turn: int, lock: asyncio.Lock) -> None:
    from ai.speech.live_tts import synthesize
    from core.session import save_turn

    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    ms = lambda: round((time.perf_counter() - t0) * 1000)  # noqa: E731
    deltas: asyncio.Queue = asyncio.Queue()
    chunks: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()
    timings: dict[str, int] = {}
    put = lambda d: loop.call_soon_threadsafe(deltas.put_nowait, d)  # noqa: E731

    async def send(obj: dict) -> None:  # text deltas and audio chunks go out from two coroutines
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
    full, buf, first = "", "", True
    try:
        messages, direct, from_modules = _messages(session_id, text), None, False
        from core.orchestrator import is_smalltalk

        if not is_smalltalk(text):  # everything else is answered by the real modules, with live news where it matters
            written = await _ask_modules(text, session_id, chunks, lambda: send({"type": "thinking", "turn": turn}))
            timings["modules_ms"] = ms()
            if written:
                from_modules = True  # the orchestrator already saved the written answer to the history
                if needs_rewrite(written):
                    messages = [{"role": "system", "content": SPOKEN_SYSTEM},
                                {"role": "user", "content": spoken_prompt(text, written)}]
                else:
                    direct = written
        if direct is not None:
            deltas.put_nowait(direct)
            deltas.put_nowait(None)
        else:
            threading.Thread(target=_stream_llm, args=(messages, put, stop), daemon=True).start()
        while (delta := await deltas.get()) is not None:
            if not full:
                timings["first_token_ms"] = ms()
            full += delta
            buf += delta
            await send({"type": "text", "turn": turn, "delta": delta})
            while True:
                chunk, buf = split_ready(buf, first)
                if not chunk:
                    break
                if said := speakable(chunk):
                    await chunks.put(said)
                    first = False
        if not full.strip():  # nothing came back at all (network down): say so instead of going quiet
            full = buf = TROUBLE
            await send({"type": "text", "turn": turn, "delta": TROUBLE})
        if said := speakable(buf):
            await chunks.put(said)
        await chunks.put(None)
        await speaker
        timings["total_ms"] = ms()
        answer = speakable(full)
        if not from_modules:
            save_turn(session_id, text, {"domain": "live_avatar", "query": text, "response": answer})
        await send({"type": "done", "turn": turn, "text": answer, "timings": timings})
        logger.info(f"Live avatar turn: {timings}")
    except asyncio.CancelledError:
        stop.set()
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
            if msg.get("type") in ("interrupt", "user") and task and not task.done():
                task.cancel()
            if msg.get("type") == "user" and str(msg.get("text", "")).strip():
                # The page numbers its own turns (it also bumps the number on an interrupt); echoing its number
                # back is what lets it drop chunks of a reply it has moved on from.
                turn = int(msg["turn"]) if str(msg.get("turn", "")).isdigit() else turn + 1
                task = asyncio.create_task(_reply(ws, str(msg["text"]).strip()[:1000], str(msg.get("session_id") or "live"), turn, lock))
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
