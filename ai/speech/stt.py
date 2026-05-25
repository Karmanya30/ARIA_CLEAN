"""
ai/speech/stt.py

Whisper speech-to-text module for ARIA.

Features:
- Lazy, thread-safe model loading
- CPU fallback with optional CUDA
- Windows ffmpeg PATH support
- Safe torch.load handling (CUDA metadata issue)
- Accepts audio bytes OR file path
- Automatic audio format detection
"""

from __future__ import annotations

import gc
import os
import shutil
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


WHISPER_MODEL = str(_setting("WHISPER_MODEL", "base.en"))
WHISPER_DEVICE = str(_setting("WHISPER_DEVICE", "auto")).lower()
WHISPER_USE_GPU = str(_setting("WHISPER_USE_GPU", "1")).lower() not in {"0", "false", "no"}


# ===============================
# GLOBAL MODEL
# ===============================
_model = None
_model_lock = threading.Lock()


def _local_ffmpeg_executable(exe_path: Path) -> Path:
    wrapper_dir = Path(__file__).resolve().parents[2] / "data" / "bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    local_path = wrapper_dir / "ffmpeg.exe"
    if not local_path.exists() or local_path.stat().st_size != exe_path.stat().st_size:
        shutil.copy2(exe_path, local_path)
    return local_path


# ===============================
# FFMPEG PATH FIX
# ===============================
def _add_ffmpeg_to_path() -> None:
    candidates = []

    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass

    candidates.extend([
        _setting("FFMPEG_DIR", ""),
        _setting("FFMPEG_PATH", ""),
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
        (
            r"C:\Users\jtmah\AppData\Local\Microsoft\WinGet\Packages"
            r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
            r"\ffmpeg-8.1-full_build\bin"
        ),
    ])

    current_path = os.environ.get("PATH", "")
    normalized = {str(Path(p)).lower() for p in current_path.split(os.pathsep) if p}

    for candidate in candidates:
        if not candidate:
            continue

        path = Path(str(candidate))
        if path.is_file():
            if path.stem.lower() != "ffmpeg":
                path = _local_ffmpeg_executable(path)
            path = path.parent

        if path.is_dir() and str(path).lower() not in normalized:
            os.environ["PATH"] = current_path + os.pathsep + str(path)
            logger.info(f"Added ffmpeg to PATH: {path}")
            return


# ===============================
# DEVICE SELECTION
# ===============================
def _cuda_available() -> bool:
    if not WHISPER_USE_GPU:
        return False
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _select_device() -> str:
    if WHISPER_DEVICE in {"cpu", "cuda"}:
        return WHISPER_DEVICE if WHISPER_DEVICE == "cpu" or _cuda_available() else "cpu"
    return "cuda" if _cuda_available() else "cpu"


# ===============================
# LOAD MODEL
# ===============================
def _load():
    global _model

    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        _add_ffmpeg_to_path()

        try:
            import torch
            import whisper
        except ImportError as exc:
            raise RuntimeError("Install Whisper: pip install openai-whisper") from exc

        device = _select_device()
        logger.info(f"Loading Whisper '{WHISPER_MODEL}' on {device}")

        # 🔥 Fix CUDA checkpoint issue
        original_load = torch.load

        def cpu_safe_load(f, map_location=None, **kwargs):
            return original_load(f, map_location="cpu", **kwargs)

        torch.load = cpu_safe_load

        try:
            _model = whisper.load_model(WHISPER_MODEL, device=device)
        finally:
            torch.load = original_load

        logger.info("Whisper loaded successfully")
        return _model


# ===============================
# AUDIO FORMAT DETECTION
# ===============================
def _suffix_for_audio(audio: bytes, filename: str | None = None) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix

    if audio.startswith(b"RIFF"):
        return ".wav"
    if audio.startswith(b"ID3") or audio[:2] == b"\xff\xfb":
        return ".mp3"
    if audio.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if audio.startswith(b"OggS"):
        return ".ogg"
    if audio.startswith(b"fLaC"):
        return ".flac"

    return ".webm"


# ===============================
# TRANSCRIBE
# ===============================
def transcribe(
    audio: bytes | bytearray | str | os.PathLike[str],
    language: str = "en",
    *,
    filename: str | None = None,
    raise_errors: bool = False,
) -> str:

    tmp_path: str | None = None

    try:
        model = _load()
        device = _select_device()

        # Case 1: file path
        if isinstance(audio, (str, os.PathLike)):
            audio_path = str(audio)

        # Case 2: raw bytes
        else:
            audio_bytes = bytes(audio)

            if not audio_bytes:
                return ""

            suffix = _suffix_for_audio(audio_bytes, filename)

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            audio_path = tmp_path

        result = model.transcribe(
            audio_path,
            language=language,
            fp16=(device == "cuda"),
        )

        text = str(result.get("text", "")).strip()
        logger.debug(f"ASR: {text[:80]}")
        return text

    except Exception as exc:
        logger.exception(f"Whisper failed: {exc}")
        if raise_errors:
            raise RuntimeError(f"Transcription failed: {exc}") from exc
        return ""

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ===============================
# HEALTH CHECK
# ===============================
def health() -> bool:
    try:
        _load()
        return True
    except Exception as exc:
        logger.warning(f"Whisper health failed: {exc}")
        return False


# ===============================
# UNLOAD
# ===============================
def unload():
    global _model

    with _model_lock:
        if _model is not None:
            del _model
            _model = None
            gc.collect()
            logger.info("Whisper unloaded")
