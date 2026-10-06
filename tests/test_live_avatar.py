"""Live Avatar: how replies are cut into speakable chunks, and the WebSocket turn (fake LLM and voice, no network)."""
import pytest
from fastapi.testclient import TestClient

from ai.speech import live_tts
from api.main import app
from api.routes import live
from core.session import clear_session, get_session


def test_first_chunk_is_short_later_chunks_are_sentences():
    chunk, rest = live.split_ready("A SIP is a plan where you invest a fixed amount, every month, into", True)
    assert chunk == "A SIP is a plan where you invest a fixed amount," and rest.startswith(" every")
    assert live.split_ready("A SIP is a plan where you invest a fixed amount, every", False)[0] is None  # later: wait for a full stop
    assert live.split_ready("Short, then more", True)[0] is None  # too short to be worth a separate clip
    assert live.split_ready("It compounds. Next", False) == ("It compounds.", " Next")
    assert live.split_ready("Pay ₹1.5 lakh", False)[0] is None  # a decimal point is not a sentence end
    long = "word " * 60
    assert len(live.split_ready(long, False)[0]) <= live.CHUNK_MAX
    assert live.speakable("**Bold** and `code` # heading") == "Bold and code heading"


@pytest.fixture
def fake_pipeline(monkeypatch):
    def fake_llm(messages, put, stop):
        for d in ["A SIP lets you invest a fixed amount, ", "every month. ", "It builds **discipline**."]:
            put(d)
        put(None)

    monkeypatch.setattr(live, "_stream_llm", fake_llm)
    monkeypatch.setattr(live_tts, "synthesize", lambda text: (b"RIFFfake", "audio/wav"))
    clear_session("live-test")


def test_a_turn_streams_text_then_audio_chunks_then_done_and_is_saved(fake_pipeline):
    with TestClient(app).websocket_connect("/api/live/ws") as ws:
        ws.send_json({"type": "user", "text": "What is a SIP?", "session_id": "live-test"})
        msgs = []
        while not msgs or msgs[-1]["type"] != "done":
            msgs.append(ws.receive_json())
    audio = [m for m in msgs if m["type"] == "audio"]
    assert [a["text"] for a in audio] == ["A SIP lets you invest a fixed amount,", "every month.", "It builds discipline."]
    assert [a["seq"] for a in audio] == [0, 1, 2] and all(a["audio"] for a in audio)
    done = msgs[-1]
    assert done["text"] == "A SIP lets you invest a fixed amount, every month. It builds discipline."
    assert {"first_token_ms", "first_audio_ms", "total_ms"} <= set(done["timings"])
    turn = get_session("live-test")["history"][-1]
    assert turn["query"] == "What is a SIP?" and turn["response"]["domain"] == "live_avatar"


def test_live_page_and_model_are_served():
    client = TestClient(app)
    page = client.get("/avatar/live")
    assert page.status_code == 200 and "/api/live/ws" in page.text and "SpeechRecognition" in page.text
    assert client.get("/avatar/model.glb").headers["content-type"] == "model/gltf-binary"


def test_amounts_are_spoken_as_words():
    assert live_tts.spoken("₹5,000 a month at 12% is about ₹11.6 lakh.") == "5,000 rupees a month at 12 percent is about 11.6 lakh rupees."
    assert live_tts.spoken("Rs. 2 crore or INR 500") == "2 crore rupees or 500 rupees"


def test_replies_carry_the_turn_number_the_page_sent(fake_pipeline):
    with TestClient(app).websocket_connect("/api/live/ws") as ws:
        ws.send_json({"type": "user", "text": "Hi", "session_id": "live-test", "turn": 7})
        msgs = [ws.receive_json()]
        while msgs[-1]["type"] != "done":
            msgs.append(ws.receive_json())
    assert {m["turn"] for m in msgs} == {7}


def test_avatar_photo_is_served_when_configured_and_404_otherwise(monkeypatch, tmp_path):
    client = TestClient(app)
    monkeypatch.setattr(live, "_AVATAR_DIR", tmp_path)
    assert client.get("/avatar/face.png").status_code == 404  # no photo: the page falls back to the 3D avatar
    (tmp_path / "face.png").write_bytes(b"\x89PNG fake")
    r = client.get("/avatar/face.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_glasses_overlay_is_served_when_present_and_404_otherwise(monkeypatch, tmp_path):
    client = TestClient(app)
    monkeypatch.setattr(live, "_AVATAR_DIR", tmp_path)
    assert client.get("/avatar/glasses.png").status_code == 404  # no overlay: the page just shows the photo
    (tmp_path / "glasses.png").write_bytes(b"PNG fake")
    r = client.get("/avatar/glasses.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
