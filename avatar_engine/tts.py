"""Local text-to-speech for the avatar: Piper (CPU, ONNX). Edge-TTS (online) is an opt-in fallback only.
voice = a Piper voice name from models/tts/piper (e.g. 'en_GB-cori-high'), 'aria' (the default), or 'edge:<ShortName>'."""
from __future__ import annotations

import io
import re
import threading
from pathlib import Path

import numpy as np

from . import config

_RUPEES = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?(\d[\d,]*(?:\.\d+)?)(\s(?:lakh|crore|thousand|million|billion)s?)?", re.IGNORECASE)
# emotion -> speaking-rate multiplier (Piper length_scale: <1 is faster) and noise (more variation = livelier)
RATE = {"neutral": 1.0, "warm": 1.0, "serious": 1.06, "concerned": 1.06, "upbeat": 0.94}


def spoken(text: str) -> str:
    """How a line should be *said* ('₹11.6 lakh' -> '11.6 lakh rupees', '12%' -> '12 percent'); same rules as ai/speech/live_tts."""
    text = _RUPEES.sub(lambda m: f"{m.group(1)}{m.group(2) or ''} rupees", text)
    return re.sub(r"(\d)\s?%", r"\1 percent", text).replace("₹", "rupees ")


class Tts:
    def __init__(self, voice_dir: Path | None = None, default: str | None = None):
        self.dir = Path(voice_dir or config.VOICE_DIR)
        self.default = default or config.VOICE
        self._voices: dict = {}
        self._lock = threading.Lock()

    def voices(self) -> list[str]:
        return sorted(p.name[:-5] for p in self.dir.glob("*.onnx"))

    def available(self) -> bool:
        return bool(self.voices())

    def resolve(self, voice: str | None) -> str:
        if voice and voice.startswith("edge:"):
            return voice
        v = self.default if not voice or voice == "aria" else voice
        if v in self.voices():
            return v
        return self.default if self.default in self.voices() else (self.voices() or [""])[0]

    def _load(self, name: str):
        with self._lock:
            if name not in self._voices:
                from piper import PiperVoice
                self._voices[name] = PiperVoice.load(str(self.dir / f"{name}.onnx"))
            return self._voices[name]

    def synth(self, text: str, voice: str | None = None, emotion: str = "neutral", rate: float | None = None) -> tuple[bytes, int]:
        """Blocking. -> (16-bit mono PCM bytes, sample rate)."""
        text = spoken(text)
        name = self.resolve(voice)
        if name.startswith("edge:") or not name:
            if not name.startswith("edge:") and not config.EDGE_FALLBACK:
                raise RuntimeError("no Piper voice installed (models/tts/piper) and Edge fallback is off (AVATAR_EDGE_FALLBACK=1)")
            return _edge(text, name[5:] if name.startswith("edge:") else "en-IN-NeerjaNeural")
        from piper import SynthesisConfig
        v = self._load(name)
        cfg = SynthesisConfig(length_scale=(rate or RATE.get(emotion, 1.0)) * 1.0)
        pcm = b"".join(c.audio_int16_bytes for c in v.synthesize(text, cfg))
        return pcm, v.config.sample_rate

    def warm_up(self) -> None:
        if self.available():
            pcm, sr = self.synth("Hello.")
            resample16k(pcm, sr)     # import scipy now, not during the first request


def _edge(text: str, voice: str) -> tuple[bytes, int]:
    """Optional online fallback: Edge-TTS mp3 decoded to PCM with ffmpeg (needs network + ffmpeg)."""
    import asyncio
    import subprocess

    import edge_tts
    import imageio_ffmpeg

    async def run() -> bytes:
        out = bytearray()
        async for ch in edge_tts.Communicate(text, voice).stream():
            if ch["type"] == "audio":
                out += ch["data"]
        return bytes(out)

    mp3 = asyncio.run(run())
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
                       input=mp3, capture_output=True, check=True)
    return r.stdout, 24000


def resample16k(pcm: bytes, sr: int) -> np.ndarray:
    """int16 PCM -> float32 mono at 16 kHz (what the lip-sync model listens to)."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if sr == 16000:
        return x
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(16000, sr)
    return resample_poly(x, 16000 // g, sr // g).astype(np.float32)
