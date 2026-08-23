"""api/routes/chat.py -- the direct replacement for what
interface/streamlit_app.py's _render_chat_tab used to do in-process."""
from fastapi.testclient import TestClient

from api.main import app
from core.session import clear_session, get_session

client = TestClient(app)
_TEST_SESSION = "__pytest_api_chat__"


def _cleanup():
    clear_session(_TEST_SESSION)


def test_send_message_returns_response_and_audio_token(mock_llm):
    _cleanup()
    try:
        resp = client.post(
            "/api/chat",
            json={"query": "what's the weather in Chennai", "session_id": _TEST_SESSION, "mode": "Normal Mode"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["response"] == mock_llm.response
        assert body["audio_token"]  # TTS runs for every mode, matching the old app
    finally:
        _cleanup()


def test_history_reflects_sent_messages(mock_llm):
    _cleanup()
    try:
        client.post("/api/chat", json={"query": "hello", "session_id": _TEST_SESSION})

        resp = client.get(f"/api/chat/history?session_id={_TEST_SESSION}")

        assert resp.status_code == 200
        history = resp.json()["history"]
        assert len(history) == 1
        assert history[0]["query"] == "hello"
    finally:
        _cleanup()


def test_history_entries_carry_audio_token_at_top_level(mock_llm):
    # Found via live testing: switching away from the Chat tab and back
    # remounts it, which re-fetches history from this endpoint instead of
    # using the locally-appended turn from POST /api/chat -- the frontend
    # reads audio_token at the top level of each entry (matching what
    # POST /api/chat itself returns), not nested inside "response".
    _cleanup()
    try:
        post_resp = client.post("/api/chat", json={"query": "hello", "session_id": _TEST_SESSION})
        sent_token = post_resp.json()["audio_token"]
        assert sent_token  # TTS runs for every mode

        resp = client.get(f"/api/chat/history?session_id={_TEST_SESSION}")

        history = resp.json()["history"]
        assert history[0]["audio_token"] == sent_token
    finally:
        _cleanup()


def test_clear_empties_history(mock_llm):
    _cleanup()
    try:
        client.post("/api/chat", json={"query": "hello", "session_id": _TEST_SESSION})

        resp = client.post("/api/chat/clear", json={"session_id": _TEST_SESSION})

        assert resp.status_code == 200
        assert get_session(_TEST_SESSION)["history"] == []
    finally:
        _cleanup()
