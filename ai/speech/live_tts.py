"""
Low-latency speech for the Live Avatar mode.

Piper (MIT, rhasspy/piper) runs a small neural voice locally on the CPU through ONNX Runtime: no network, no
API key, no per-use cost, and a sentence is ready in a fraction of a second. That is what keeps the Live
Avatar's first word under ~3 seconds. edge-tts (the normal chat voice) opens a new connection to Microsoft
for every sentence and needs ~1.5-1.9 s before the first byte, so it is only the fallback when no Piper voice
is installed (`python -m ai.speech.live_tts --download`). Kokoro-82M was tried first: on this class of laptop
CPU it needs ~2 s per phrase, and DirectML cannot run its ConvTranspose layers.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import threading
import urllib.request
import wave
from pathlib import Path

from loguru import logger

VOICE_DIR = Path(__file__).resolve().parents[2] / "models" / "tts" / "piper"
VOICE = os.getenv("LIVE_TTS_VOICE", "en_US-amy-medium")
EDGE_VOICE = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")
_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/"
_VOICE_PATHS = {"en_US-amy-medium": "en_US/amy/medium/", "en_GB-cori-high": "en_GB/cori/high/"}

_voice = None
_lock = threading.Lock()


def available() -> bool:
    return (VOICE_DIR / f"{VOICE}.onnx").exists() and (VOICE_DIR / f"{VOICE}.onnx.json").exists()


def _piper():
    global _voice
    with _lock:
        if _voice is None:
            from piper import PiperVoice

            _voice = PiperVoice.load(str(VOICE_DIR / f"{VOICE}.onnx"))
        return _voice


def _edge(text: str) -> bytes:
    import edge_tts

    async def run() -> bytes:
        out = bytearray()
        async for chunk in edge_tts.Communicate(text, EDGE_VOICE).stream():
            if chunk["type"] == "audio":
                out += chunk["data"]
        return bytes(out)

    return asyncio.run(run())


_RUPEES = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?(\d[\d,]*(?:\.\d+)?)(\s(?:lakh|crore|thousand|million|billion)s?)?", re.IGNORECASE)


def spoken(text: str) -> str:
    """How a line should be *said*: '₹11.6 lakh' -> '11.6 lakh rupees', '12%' -> '12 percent'."""
    text = _RUPEES.sub(lambda m: f"{m.group(1)}{m.group(2) or ''} rupees", text)
    return re.sub(r"(\d)\s?%", r"\1 percent", text).replace("₹", "rupees ")


def synthesize(text: str) -> tuple[bytes, str]:
    """(audio bytes, mime type) for one sentence. Blocking: call it from a worker thread."""
    text = spoken(text)
    if available():
        try:
            voice = _piper()
            pcm = b"".join(c.audio_int16_bytes for c in voice.synthesize(text))  # empty for text with nothing to say
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(voice.config.sample_rate)
                wav.writeframes(pcm)
            return buf.getvalue(), "audio/wav"
        except Exception as exc:  # a broken voice must not silence the avatar
            logger.warning(f"Piper failed, using edge-tts for this sentence: {exc}")
    return _edge(text), "audio/mpeg"


def warm_up() -> None:
    if available():
        synthesize("Hello.")


def download(voice: str = VOICE) -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx.json", ".onnx"):
        target = VOICE_DIR / f"{voice}{suffix}"
        if not target.exists():
            print(f"downloading {target.name} ...")
            urllib.request.urlretrieve(_HF + _VOICE_PATHS[voice] + voice + suffix, target)
    print("Piper voice ready in", VOICE_DIR)


if __name__ == "__main__":
    import sys

    if "--download" in sys.argv:
        download()
