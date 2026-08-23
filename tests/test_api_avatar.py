"""api/routes/avatar.py -- the Tavus custom-LLM callback route (now part of
the single unified API process, not a separate Streamlit-spawned
subprocess) plus the free-avatar render route.

Two real bugs were fixed in this route before the Streamlit->React
rewrite and are still covered here: (1) Tavus's docs require the
custom-LLM endpoint to be streamable via SSE -- a flat JSON response left
the avatar silent on real calls; (2) the route must capture the real
session_id from its own path (not a shared constant) so concurrent
conversations don't bleed into each other's history, and so the turn
lands in the same core.session store /api/chat/history reads -- no
separate transcript table needed now that Tavus's callback and the
frontend's own chat calls run in one process.
"""
import json

from fastapi.testclient import TestClient

from api.main import app
from core.session import clear_session, get_session

client = TestClient(app)
_TEST_SESSION = "__pytest_api_avatar__"


def _cleanup():
    clear_session(_TEST_SESSION)


def test_non_streaming_returns_a_single_json_completion(mock_llm):
    _cleanup()
    try:
        resp = client.post(
            f"/v1/{_TEST_SESSION}/chat/completions",
            json={"model": "aria-custom", "messages": [{"role": "user", "content": "what's the weather in Chennai"}], "stream": False},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"]
    finally:
        _cleanup()


def test_streaming_returns_valid_sse_with_role_first_and_done_last(mock_llm):
    _cleanup()
    try:
        with client.stream(
            "POST",
            f"/v1/{_TEST_SESSION}/chat/completions",
            json={"model": "aria-custom", "messages": [{"role": "user", "content": "what's the weather in Chennai"}], "stream": True},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            lines = [line for line in resp.iter_lines() if line.startswith("data: ")]

        assert lines[-1] == "data: [DONE]"

        first_payload = json.loads(lines[0].removeprefix("data: "))
        assert first_payload["choices"][0]["delta"] == {"role": "assistant"}

        reassembled = "".join(
            json.loads(line.removeprefix("data: "))["choices"][0]["delta"].get("content", "")
            for line in lines[:-1]
        )
        assert reassembled.strip() == mock_llm.response.strip()

        last_content_payload = json.loads(lines[-2].removeprefix("data: "))
        assert last_content_payload["choices"][0]["finish_reason"] == "stop"
    finally:
        _cleanup()


def test_turn_is_saved_under_the_real_session_id(mock_llm):
    _cleanup()
    try:
        client.post(
            f"/v1/{_TEST_SESSION}/chat/completions",
            json={"model": "aria-custom", "messages": [{"role": "user", "content": "what's the weather in Chennai"}], "stream": False},
        )

        # handle_query() saves into core.session internally -- the same
        # store GET /api/chat/history reads, so a voice turn from Tavus
        # and a typed turn from the Chat tab end up in one place.
        history = get_session(_TEST_SESSION)["history"]

        assert len(history) == 1
        assert history[0]["query"] == "what's the weather in Chennai"
        assert history[0]["response"]["response"] == mock_llm.response
    finally:
        _cleanup()


def test_avatar_render_returns_html_without_an_audio_token():
    resp = client.get("/avatar/render")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
