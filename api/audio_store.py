"""Bounded speech queue with durable, expiring completed audio capabilities.

Completed clips survive API restarts. In-flight callables cannot be resumed
after their worker dies. Never delete the synthesizer's arbitrary source path.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
from typing import Callable
from uuid import uuid4

from sqlalchemy import text

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tts")
_SLOTS = threading.BoundedSemaphore(16)
AUDIO_WAIT_SECONDS = 90
TTL_SECONDS = 3600
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CACHE_BYTES = 128 * 1024 * 1024
MAX_ARTIFACTS = 128


def _store():
    from shared import user_store
    return user_store


def _root():
    database = _store()._engine.url.database
    if not database or database == ":memory:":
        raise RuntimeError("Audio persistence needs a file-backed database")
    root = Path(database).resolve().parent / "audio-cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(token):
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        return None
    return _root() / (token + ".audio")


def _prune(session):
    store = _store()
    expired = session.query(store.AudioArtifactRecord).filter(store.AudioArtifactRecord.expires_at <= time.time()).all()
    for row in expired:
        path = _path(row.token)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue  # retry cleanup later; expiry still prevents access
        session.delete(row)


def _reserve(token):
    store = _store()
    with store._SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        _prune(session)
        if session.query(store.AudioArtifactRecord).count() >= MAX_ARTIFACTS:
            session.commit()
            return False
        session.add(store.AudioArtifactRecord(token=token, status="pending", expires_at=time.time() + TTL_SECONDS,
                                             size=0, owner_id=store.current_owner.get()))
        session.commit()
        return True


def _finish(token, source):
    store = _store()
    target = _path(token)
    with store._SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        row = session.get(store.AudioArtifactRecord, token)
        if row is None or row.expires_at <= time.time():
            return
        row.status = "failed"
        if source:
            path = Path(source)
            if path.is_file() and 0 < path.stat().st_size <= MAX_FILE_BYTES:
                used = sum(size for (size,) in session.query(store.AudioArtifactRecord.size))
                if used + path.stat().st_size <= MAX_CACHE_BYTES:
                    try:
                        with path.open("rb") as src, target.open("wb") as dst:
                            remaining = MAX_FILE_BYTES + 1
                            while remaining:
                                chunk = src.read(min(64 * 1024, remaining))
                                if not chunk:
                                    break
                                dst.write(chunk)
                                remaining -= len(chunk)
                        actual = target.stat().st_size
                        if 0 < actual <= MAX_FILE_BYTES and used + actual <= MAX_CACHE_BYTES:
                            row.status, row.size = "ready", actual
                        else:
                            target.unlink(missing_ok=True)
                    except OSError:
                        target.unlink(missing_ok=True)
        session.commit()


def register(path: str) -> str | None:
    token = uuid4().hex
    if not _reserve(token):
        return None
    _finish(token, path)
    return token


def register_later(make_audio: Callable[[], str | None]) -> str | None:
    """Keep text available when the bounded running/queued speech slots fill."""
    if not _SLOTS.acquire(blocking=False):
        return None
    token = uuid4().hex
    try:
        if not _reserve(token):
            _SLOTS.release()
            return None
        def produce():
            try:
                try:
                    source = make_audio()
                except Exception:
                    source = None
                _finish(token, source)
            finally:
                _SLOTS.release()
        _POOL.submit(produce)
    except Exception:
        _SLOTS.release()
        # Database admission/worker startup failure must not discard a text reply.
        return None
    return token


def resolve(token: str) -> str | None:
    path = _path(token)
    if path is None:
        return None
    store = _store()
    deadline = time.monotonic() + AUDIO_WAIT_SECONDS
    while True:
        with store._SessionLocal() as session:
            row = session.get(store.AudioArtifactRecord, token)
            if row is None or row.expires_at <= time.time() or row.status == "failed":
                return None
            if row.status == "ready":
                return str(path) if path.is_file() else None
        if time.monotonic() >= deadline:
            return None
        time.sleep(.1)
