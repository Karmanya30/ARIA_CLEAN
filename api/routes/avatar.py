"""Self-hosted avatar rendering endpoint."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["avatar"])

@router.get("/avatar/render", response_class=HTMLResponse)
def render_avatar(audio_token: str | None = None):
    from api.audio_store import resolve
    from interface.avatar.render import build_avatar_html
    audio_path = resolve(audio_token) if audio_token else None
    return build_avatar_html(audio_path)
