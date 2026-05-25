"""
ai/speech/tts.py

Text-to-speech module for ARIA.

Features:
- Edge-TTS primary (high-quality neural voice)
- Thread-safe asyncio execution (works with Streamlit)
- pyttsx3 offline fallback
- Configurable voice, timeout, and speech rate
- Safe temp file handling
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from config import settings
except Exception:
    settings = None


# ===============================
# CONFIG
# ===============================
def _setting(name: str, default: Any) -> Any:
    if settings is not None and hasattr(settings, name):
        return getattr(settings, name)
    return os.getenv(name, default)


TTS_VOICE = str(_setting("TTS_VOICE", "en-IN-NeerjaNeural"))
TTS_TIMEOUT_SECONDS = float(_setting("TTS_TIMEOUT_SECONDS", 30))
TTS_RATE = int(_setting("TTS_RATE", 165))


# ===============================
# EDGE-TTS (ASYNC)
# ===============================
async def _edge_async(text: str, out_path: str, voice: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


# ===============================
# THREAD-SAFE RUNNER
# ===============================
def _run_edge_tts(
    text: str,
    out_path: str,
    voice: str,
    timeout: float = TTS_TIMEOUT_SECONDS,
) -> None:

    errors: list[BaseException] = []

    def worker() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_edge_async(text, out_path, voice))
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise TimeoutError(f"Edge-TTS timed out after {timeout:.0f}s")

    if errors:
        raise errors[0]


# ===============================
# TEMP FILE HELPERS
# ===============================
def _new_temp_path(suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    return tmp.name


def _remove_if_exists(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


# ===============================
# MAIN SYNTHESIS
# ===============================
def synthesize(
    text: str,
    out_path: str | None = None,
    *,
    voice: str = TTS_VOICE,
    fallback: bool = True,
    timeout: float = TTS_TIMEOUT_SECONDS,
) -> str | None:

    text = str(text or "").strip()
    if not text:
        return None

    edge_path = out_path or _new_temp_path(".mp3")

    # ── Primary: Edge-TTS ─────────────────
    try:
        _run_edge_tts(text, edge_path, voice, timeout=timeout)
        logger.debug(f"[TTS] Edge: {edge_path}")
        return edge_path

    except Exception as exc:
        logger.warning(f"Edge-TTS failed: {exc}")

        if out_path is None:
            _remove_if_exists(edge_path)

        if not fallback:
            return None

    # ── Fallback: pyttsx3 ─────────────────
    try:
        fallback_path = out_path or _new_temp_path(".wav")
        _pyttsx3(text, fallback_path)
        logger.debug(f"[TTS] pyttsx3: {fallback_path}")
        return fallback_path

    except Exception as exc:
        logger.error(f"TTS failed completely: {exc}")

        if out_path is None:
            _remove_if_exists(fallback_path if "fallback_path" in locals() else None)

        return None


# ===============================
# OFFLINE ENGINE
# ===============================
def _pyttsx3(text: str, out_path: str | None = None) -> str:
    try:
        import pyttsx3
    except ImportError as exc:
        raise RuntimeError("Install pyttsx3: pip install pyttsx3") from exc

    path = out_path or _new_temp_path(".wav")

    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", TTS_RATE)
        engine.save_to_file(text, path)
        engine.runAndWait()
    finally:
        try:
            engine.stop()
        except Exception:
            pass

    return path


# ===============================
# VOICE LIST
# ===============================
def list_voices(locale: str = "en-IN") -> list[dict[str, Any]]:
    try:
        import edge_tts

        async def collect():
            return await edge_tts.list_voices()

        def run():
            return asyncio.run(collect())

        voices_holder = []
        errors = []

        def worker():
            try:
                voices_holder.append(run())
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=TTS_TIMEOUT_SECONDS)

        if thread.is_alive():
            raise TimeoutError("Voice list timeout")

        if errors:
            raise errors[0]

        voices = voices_holder[0] if voices_holder else []

        if not locale:
            return voices

        locale = locale.lower()
        return [
            v for v in voices
            if locale in str(v.get("ShortName", "")).lower()
            or locale in str(v.get("Locale", "")).lower()
        ]

    except Exception as exc:
        logger.error(f"Voice list failed: {exc}")
        return []


# ===============================
# HEALTH CHECK
# ===============================
def health() -> bool:
    try:
        import edge_tts  # noqa
        return True
    except Exception:
        try:
            import pyttsx3  # noqa
            return True
        except Exception:
            return False