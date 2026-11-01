"""The self-hosted avatar remains available after retiring the paid provider."""
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_retired_provider_routes_are_not_registered():
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/tavus/start" not in paths
    assert "/api/tavus/end" not in paths
    assert "/v1/{session_id}/chat/completions" not in paths
    assert "/embed" not in paths


def test_avatar_render_returns_html_without_an_audio_token():
    resp = client.get("/avatar/render")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
