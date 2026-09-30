"""In-memory token -> audio file path registry.

TTS output (ai/speech/tts.synthesize) writes to a real temp file already;
this just hands the frontend a short opaque token instead of a raw
filesystem path, so /api/audio/{token} and the avatar-render route can
both resolve the same file without the client ever seeing server paths.
Same-process, same lifetime as the API itself -- no cross-process sharing
needed now that Tavus's callback lives in this process too, unlike the
old Streamlit-subprocess split.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable
from uuid import uuid4

_STORE: dict[str, str | Future] = {}
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tts")
AUDIO_WAIT_SECONDS = 90


def register(path: str) -> str:
    token = uuid4().hex
    _STORE[token] = path
    return token


def register_later(make_audio: Callable[[], str | None]) -> str:
    """Hand out a token now and make the audio in the background. The chat reply no longer waits for the
    spoken-script LLM call and speech synthesis (several seconds); whoever fetches the audio waits instead."""
    token = uuid4().hex
    _STORE[token] = _POOL.submit(make_audio)
    return token


def resolve(token: str) -> str | None:
    value = _STORE.get(token)
    if isinstance(value, Future):
        try:
            value = value.result(timeout=AUDIO_WAIT_SECONDS)
        except Exception:
            return None
        _STORE[token] = value
    return value
