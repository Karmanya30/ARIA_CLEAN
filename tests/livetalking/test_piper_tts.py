r"""Piper TTS plugin vs a fake parent. Skips cleanly unless the LiveTalking checkout (and its deps) is importable.
Run in the LiveTalking env: E:\LiveTalking\env\python.exe -m pytest tests/livetalking"""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

LT = Path(os.environ.get("LIVETALKING_DIR", r"E:\LiveTalking\src"))
if not (LT / "tts" / "base_tts.py").is_file():
    pytest.skip("LiveTalking checkout not present", allow_module_level=True)
sys.path.append(str(LT))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from livetalking_adapter import piper_tts
    from tts.base_tts import State
except Exception as e:  # missing deps in ARIA's own env
    pytest.skip(f"LiveTalking deps unavailable: {e}", allow_module_level=True)


class Parent:
    def __init__(self, on_frame=None):
        self.frames, self.on_frame = [], on_frame

    def put_audio_frame(self, chunk, ev):
        self.frames.append((chunk, ev))
        if self.on_frame:
            self.on_frame(len(self.frames))


class FakeVoice:
    def __init__(self, sentences=3, secs=0.5, sr=22050):
        self.n, self.secs, self.sr = sentences, secs, sr

    def synthesize(self, text):
        for _ in range(self.n):
            yield SimpleNamespace(audio_float_array=np.random.uniform(-.3, .3, int(self.sr * self.secs)).astype(np.float32),
                                  sample_rate=self.sr)


def make(monkeypatch, parent, voice=None):
    monkeypatch.setattr(piper_tts, "load_voice", lambda *a: voice or FakeVoice())
    return piper_tts.PiperTTS(SimpleNamespace(fps=25), parent)


def test_chunks_events(monkeypatch):
    p = Parent()
    make(monkeypatch, p).txt_to_audio(("Hello there. How are you. Fine.", {"k": 1}))
    assert len(p.frames) >= 70  # 1.5 s of audio
    assert all(c.shape == (320,) and c.dtype == np.float32 for c, _ in p.frames)
    assert p.frames[0][1]["status"] == "start" and p.frames[-1][1]["status"] == "end"
    assert [e for _, e in p.frames[1:-1] if "status" in e] == []
    assert p.frames[0][1]["k"] == 1


def test_flush_mid_text(monkeypatch):
    p = Parent()
    t = make(monkeypatch, p)
    p.on_frame = lambda n: t.flush_talk() if n == 10 else None
    t.txt_to_audio(("One. Two. Three.", {}))
    assert len(p.frames) <= 11 and t.state == State.PAUSE
    assert not any(e.get("status") == "end" for _, e in p.frames)


def test_missing_voice_clear_error(monkeypatch):
    monkeypatch.setenv("LT_VOICE", str(Path("nope") / "x.onnx"))
    with pytest.raises(FileNotFoundError, match="Piper voice not found"):
        piper_tts.load_voice()


@pytest.mark.skipif(not piper_tts.DEFAULT_VOICE.is_file(), reason="kristin voice absent")
def test_real_voice():
    pytest.importorskip("piper")
    p = Parent()
    t0 = time.time()
    piper_tts.PiperTTS(SimpleNamespace(fps=25), p).txt_to_audio(("Hello from Aria. This is a test.", {}))
    assert len(p.frames) > 50 and p.frames[-1][1]["status"] == "end"
    assert max(np.abs(c).max() for c, _ in p.frames) > 0.01
