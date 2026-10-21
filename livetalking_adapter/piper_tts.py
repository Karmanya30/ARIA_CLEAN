"""Piper TTS plugin for LiveTalking (registered as tts "piper").

Streams sentence by sentence, resamples to 16 kHz float32 and pushes 20 ms (320 sample)
chunks to parent.put_audio_frame exactly like upstream's tts/edge.py ('start' on the first
chunk, 'end' on the last). flush_talk() flips self.state to PAUSE; it is checked between
sentences and before every chunk, so output stops within one chunk (~20 ms) plus the
sentence currently being synthesised (~100-300 ms).
Needs upstream's modules (tts.base_tts, registry) on sys.path: serve.py arranges that.
"""
import os
import threading
from pathlib import Path

import numpy as np
import resampy

from registry import register
from tts.base_tts import BaseTTS, State
from utils.logger import logger

DEFAULT_VOICE = Path(__file__).resolve().parents[1] / "models" / "tts" / "piper" / "en_US-kristin-medium.onnx"
_voices, _lock = {}, threading.Lock()


def voice_path() -> Path:
    # kristin is public domain; hfc_female / ryan are non-commercial, never the default
    return Path(os.environ.get("LT_VOICE") or DEFAULT_VOICE)


def load_voice(path: Path | None = None):
    path = Path(path or voice_path())
    if not path.is_file():
        raise FileNotFoundError(f"Piper voice not found: {path} (set LT_VOICE to a .onnx voice file)")
    with _lock:
        if str(path) not in _voices:
            from piper import PiperVoice
            _voices[str(path)] = PiperVoice.load(str(path))
        return _voices[str(path)]


@register("tts", "piper")
class PiperTTS(BaseTTS):
    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        self.voice = load_voice()  # fail at session creation with a clear error, not mid-sentence

    def _sentences(self, text):
        """Yield 16 kHz float32 audio per sentence (own method so tests can stub the synthesiser)."""
        for c in self.voice.synthesize(text):
            a = np.asarray(c.audio_float_array, dtype=np.float32)
            if c.sample_rate != self.sample_rate and a.size:
                a = resampy.resample(a, c.sample_rate, self.sample_rate).astype(np.float32)
            yield a

    def txt_to_audio(self, msg):
        text, textevent = msg
        pending, first, buf = None, True, np.zeros(0, np.float32)

        def emit(chunk, last=False):
            nonlocal first
            ev = {"status": "start"} if first else {}
            if last:
                ev["status"] = "end"
            if ev:
                ev["text"] = text
            ev.update(**textevent)
            first = False
            self.parent.put_audio_frame(chunk, ev)

        try:
            for sent in self._sentences(text):  # generator: a flush stops us before the next sentence
                if self.state != State.RUNNING:
                    return
                buf = np.concatenate([buf, sent])
                while buf.size >= self.chunk:
                    if self.state != State.RUNNING:
                        return
                    if pending is not None:
                        emit(pending)  # hold one chunk back so the final one can carry 'end'
                    pending, buf = buf[:self.chunk].copy(), buf[self.chunk:]
        except Exception:
            logger.exception("piper tts failed")
            return
        if self.state != State.RUNNING:
            return
        if buf.size:  # pad the tail to a full 20 ms chunk
            if pending is not None:
                emit(pending)
            pending = np.pad(buf, (0, self.chunk - buf.size))
        if pending is not None:
            emit(pending, last=True)
