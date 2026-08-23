"""
Builds the avatar.html payload served by api/routes/avatar.py's
GET /avatar/render (the React frontend embeds it as an iframe srcdoc) --
injects the
base64-encoded avatar model (cached after first read) and, optionally, a
base64-encoded TTS audio clip into the avatar.html template.
"""
from __future__ import annotations

import base64
from pathlib import Path

_AVATAR_DIR = Path(__file__).resolve().parent
_HTML_TEMPLATE_PATH = _AVATAR_DIR / "avatar.html"
_MODEL_PATH = _AVATAR_DIR / "model.glb"

_avatar_data_url_cache: str | None = None


def _avatar_data_url() -> str:
    global _avatar_data_url_cache
    if _avatar_data_url_cache is None:
        encoded = base64.b64encode(_MODEL_PATH.read_bytes()).decode("ascii")
        _avatar_data_url_cache = f"data:model/gltf-binary;base64,{encoded}"
    return _avatar_data_url_cache


def build_avatar_html(audio_path: str | None = None) -> str:
    """Full avatar.html content with the avatar model and (if given) an
    audio clip injected, ready to serve as an HTML response."""
    html = _HTML_TEMPLATE_PATH.read_text(encoding="utf-8")

    audio_base64 = ""
    if audio_path and Path(audio_path).exists():
        audio_base64 = base64.b64encode(Path(audio_path).read_bytes()).decode("ascii")

    html = html.replace("__AVATAR_DATA_URL__", _avatar_data_url())
    html = html.replace("__AUDIO_BASE64__", audio_base64)
    return html
