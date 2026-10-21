r"""Avatar-engine tests need cv2/numpy/fastapi (the MuseTalk env python): E:\MuseTalk\env\python.exe -m pytest tests/avatar.
They use a fake backend and a fake TTS: no GPU, no model downloads, never the microphone."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from avatar_engine.backend_fake import FakeBackend  # noqa: E402
from avatar_engine.engine import Engine  # noqa: E402
from avatar_engine.server import create_app  # noqa: E402


class FakeTts:
    """~55 ms of a 220 Hz tone per character at 22.05 kHz."""
    def voices(self):
        return ["fake"]

    def resolve(self, v):
        return "fake"

    def warm_up(self):
        pass

    def synth(self, text, voice=None, emotion="neutral", rate=None):
        n = int(22050 * 0.055 * max(len(text), 3))
        t = np.arange(n) / 22050
        return (np.sin(2 * np.pi * 220 * t) * 8000 * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.int16).tobytes(), 22050


@pytest.fixture
def face_png(tmp_path):
    img = np.full((800, 600, 3), (180, 170, 160), np.uint8)
    cv2.ellipse(img, (300, 330), (130, 170), 0, 0, 360, (140, 160, 200), -1)
    img = np.clip(img.astype(int) + np.random.RandomState(0).randint(-25, 25, img.shape) + (np.arange(800)[:, None, None] % 40), 0, 255).astype(np.uint8)
    p = tmp_path / "face.png"
    cv2.imwrite(str(p), img)
    return p


@pytest.fixture
def engine(tmp_path, face_png):
    eng = Engine(FakeBackend(), FakeTts(), root=tmp_path / "replicas", default_face=face_png)
    eng.start()
    assert eng.ready, eng.error
    return eng


@pytest.fixture
def client(engine):
    from fastapi.testclient import TestClient
    with TestClient(create_app(engine, autostart=False)) as c:
        yield c
