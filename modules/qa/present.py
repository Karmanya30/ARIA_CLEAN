"""Presentation: the only place a chat mode or channel is allowed to matter. The written answer is the same everywhere;
a voice/avatar mode adds a short spoken version of it (ai/llm/spoken.py), and written replies get a background audio clip."""
from __future__ import annotations

from typing import Any

from loguru import logger

from api.audio_store import register_later
from api.text_utils import speech_text
from modules.qa import trust
from modules.qa.models import Channel, QARequest


def spoken_text(question: str, written: str) -> str:
    """What ARIA says aloud for a written reply. Never raises: on any failure the written reply is spoken."""
    from ai.llm.spoken import spoken_version

    try:
        return speech_text(spoken_version(question, written))
    except Exception as exc:
        logger.warning(f"spoken rewrite failed; speaking the written reply: {exc}")
        return speech_text(written)


def audio_token(written: str) -> str | None:
    """Starts the text-to-speech clip in the background (api/audio_store) and returns its token at once."""
    def make_audio() -> str | None:
        try:
            from ai.llm.audio_script import generate_audio_script
            from ai.speech.tts import synthesize

            return synthesize(speech_text(generate_audio_script(written)))
        except Exception as exc:
            logger.warning(f"TTS generation failed; the reply stays text-only: {exc}")
            return None

    return register_later(make_audio)


def present(resp: dict[str, Any], req: QARequest) -> dict[str, Any]:
    """Mode/channel styling. Adds fields; never edits `response`."""
    text = resp.get("response") if isinstance(resp.get("response"), str) else ""
    resp["presentation"] = {"mode": req.mode.value, "channel": req.channel.value, "style": "spoken" if req.mode.speaks else "text"}
    if not text:
        return resp
    if req.mode.speaks:  # the avatar reads this aloud; the written answer stays on screen / in history
        resp["spoken"] = spoken_text(req.query, text)
    if req.channel is not Channel.AVATAR and not trust.failed(text):  # written replies get a playable clip in the background
        resp["audio_token"] = audio_token(text)
    return resp
