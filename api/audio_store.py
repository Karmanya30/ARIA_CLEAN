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

from uuid import uuid4

_STORE: dict[str, str] = {}


def register(path: str) -> str:
    token = uuid4().hex
    _STORE[token] = path
    return token


def resolve(token: str) -> str | None:
    return _STORE.get(token)
