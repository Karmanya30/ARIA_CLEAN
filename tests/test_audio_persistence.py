import os
from pathlib import Path
import subprocess
import sys
import threading

from fastapi.testclient import TestClient
import pytest
from api import audio_store as audio
from api.main import app
from shared import user_store as store


@pytest.fixture(autouse=True)
def clean_artifacts():
    with store._SessionLocal() as session:
        for row in session.query(store.AudioArtifactRecord).all():
            path = audio._path(row.token)
            if path:
                path.unlink(missing_ok=True)
        session.query(store.AudioArtifactRecord).delete()
        session.commit()
    yield


def test_completed_clip_survives_fresh_process_and_source_removal(tmp_path):
    source = tmp_path / "synthetic.wav"
    content = b"RIFF" + b"synthetic-audio" * 10
    source.write_bytes(content)
    token = audio.register(str(source))
    source.unlink()
    result = subprocess.run([sys.executable, "-c", "import sys; from pathlib import Path; from api.audio_store import resolve; sys.stdout.buffer.write(Path(resolve(sys.argv[1])).read_bytes())", token],
                            env={**os.environ, "DB_URL": store.DB_URL}, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == content
    response = TestClient(app).get("/api/audio/" + token)
    assert response.content == content and response.headers["content-type"] == "audio/wav"


def test_queue_saturation_keeps_text_path_nonblocking_and_recovers(monkeypatch, tmp_path):
    source = tmp_path / "synthetic.mp3"
    source.write_bytes(b"synthetic-mp3")
    monkeypatch.setattr(audio, "_SLOTS", threading.BoundedSemaphore(1))
    started, finish = threading.Event(), threading.Event()
    def make():
        started.set()
        assert finish.wait(10)
        return str(source)
    token = audio.register_later(make)
    try:
        assert started.wait(10)
        assert audio.register_later(lambda: pytest.fail("queued past limit")) is None
    finally:
        finish.set()
    assert Path(audio.resolve(token)).read_bytes() == source.read_bytes()
    assert audio._SLOTS.acquire(timeout=10)
    audio._SLOTS.release()


def test_failure_expiry_cleanup_and_source_safety(monkeypatch, tmp_path):
    source = tmp_path / "original.mp3"
    source.write_bytes(b"original")
    token = audio.register(str(source))
    cached = Path(audio.resolve(token))
    with store._SessionLocal() as session:
        session.get(store.AudioArtifactRecord, token).expires_at = 0
        session.commit()
    assert audio.resolve(token) is None
    audio.register(str(source))  # lazy cleanup
    assert not cached.exists() and source.read_bytes() == b"original"
    def broken():
        raise RuntimeError("private failure")
    failed = audio.register_later(broken)
    assert audio.resolve(failed) is None
    assert audio.resolve("../outside") is None


def test_cache_count_and_bytes_enforced(tmp_path, monkeypatch):
    source = tmp_path / "sample.mp3"
    source.write_bytes(b"12345")
    monkeypatch.setattr(audio, "MAX_CACHE_BYTES", 6)
    first, second = audio.register(str(source)), audio.register(str(source))
    assert audio.resolve(first) and audio.resolve(second) is None
    monkeypatch.setattr(audio, "MAX_ARTIFACTS", 2)
    assert audio.register(str(source)) is None
    assert source.exists()


def test_oversized_clip_and_database_admission_failure_are_text_only(tmp_path, monkeypatch):
    source = tmp_path / "large.mp3"
    source.write_bytes(b"123456")
    monkeypatch.setattr(audio, "MAX_FILE_BYTES", 5)
    assert audio.resolve(audio.register(str(source))) is None
    def busy(*args):
        raise RuntimeError("database busy")
    monkeypatch.setattr(audio, "_reserve", busy)
    monkeypatch.setattr(audio, "_SLOTS", threading.BoundedSemaphore(1))
    assert audio.register_later(lambda: str(source)) is None
    assert audio._SLOTS.acquire(blocking=False)
    audio._SLOTS.release()
