"""End-to-end /stream protocol with the fake backend and fake TTS (real-time paced, so keep texts short)."""
import json
import time

from avatar_engine import protocol
from avatar_engine.backend_base import GpuOom
from avatar_engine.backend_fake import FakeBackend


def recv(ws):
    m = ws.receive()
    if m["type"] == "websocket.close":
        return "close", None
    if m.get("bytes") is not None:
        return "bin", protocol.unpack(m["bytes"])
    return "json", json.loads(m["text"])


def run_until(ws, stop, limit=15.0):
    """Collect messages until stop(kind, msg) is true; returns [(kind, msg, seconds)]."""
    out, t0 = [], time.time()
    while time.time() - t0 < limit:
        k, m = recv(ws)
        out.append((k, m, time.time() - t0))
        if k == "close" or stop(k, m):
            return out
    raise AssertionError("timeout; got " + str([x[1] for x in out if x[0] == "json"]))


def states(msgs):
    return [m["value"] for k, m, _ in msgs if k == "json" and m.get("type") == "state"]


def is_json(typ, **kw):
    return lambda k, m: k == "json" and m.get("type") == typ and all(m.get(a) == b for a, b in kw.items())


def test_idle_frames_flow_without_speech(client):
    with client.websocket_connect("/stream") as ws:
        msgs = run_until(ws, lambda k, m: k == "bin" and m[1] >= 6)
        vids = [m for k, m, _ in msgs if k == "bin"]
        assert all(v[0] == protocol.VIDEO and v[3][:2] == b"\xff\xd8" for v in vids)       # JPEG
        ts = [v[2] for v in vids]
        assert ts == sorted(ts) and 30 <= (ts[-1] - ts[0]) / (len(ts) - 1) <= 55           # ~25 fps stamps
        assert states(msgs)[0] == "idle"


def test_speak_full_cycle(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "speak", "text": "Hello, I am ARIA. Your financial companion.", "emotion": "warm"}))
        msgs = run_until(ws, is_json("metrics"))
        assert states(msgs)[:3] == ["idle", "thinking", "speaking"]
        caps = [m for k, m, _ in msgs if k == "json" and m.get("type") == "caption"]
        assert [c["text"] for c in caps] == ["Hello, I am ARIA.", "Your financial companion."]
        assert all(c["t_end"] > c["t_start"] for c in caps) and caps[1]["t_start"] >= caps[0]["t_end"] - 150
        audio = [m for k, m, _ in msgs if k == "bin" and m[0] == protocol.AUDIO]
        assert audio and all(a[3][0] == 22050 for a in audio)
        secs = sum(len(a[3][1]) // 2 for a in audio) / 22050
        assert 1.5 < secs < 4.0                          # every sample sent once
        ats = [a[2] for a in audio]
        assert ats == sorted(ats)
        metrics = [m for k, m, _ in msgs if k == "json" and m.get("type") == "metrics"][0]
        assert 0 < metrics["ttfb_ms"] < 1500 and metrics["fps"] > 0
        more = run_until(ws, is_json("state"))
        assert states(more)[-1] == "idle"


def test_interrupt_stops_within_200ms(engine, client):
    engine.backend.delay = 0.02      # slow generation: the interrupt lands mid-sentence
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "speak", "text": "This is a rather long sentence that should still be speaking when the interrupt arrives."}))
        run_until(ws, is_json("state", value="speaking"))
        run_until(ws, lambda k, m: k == "bin" and m[0] == protocol.AUDIO)
        t0 = time.time()
        ws.send_text(json.dumps({"type": "interrupt"}))
        msgs = run_until(ws, is_json("state", value="idle"))
        assert time.time() - t0 < 0.2
        n = [0]

        def eight_frames(k, m):
            n[0] += k == "bin" and m[0] == protocol.VIDEO
            return n[0] >= 8
        tail = run_until(ws, eight_frames)
        assert not [1 for k, m, _ in tail if k == "bin" and m[0] == protocol.AUDIO]      # no speech audio after idle
        assert engine.session.cur is None and not engine.session.queue


def test_speak_again_after_interrupt(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "speak", "text": "First long sentence that will be cut off before it ends."}))
        run_until(ws, lambda k, m: k == "bin" and m[0] == protocol.AUDIO)
        ws.send_text(json.dumps({"type": "interrupt"}))
        ws.send_text(json.dumps({"type": "speak", "text": "Second."}))
        msgs = run_until(ws, is_json("metrics"))
        assert [m["text"] for k, m, _ in msgs if k == "json" and m.get("type") == "caption"][-1] == "Second."


def test_ping_listening_and_configure(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "ping", "t": 5}))
        run_until(ws, is_json("pong", t=5))
        ws.send_text(json.dumps({"type": "listening", "value": True}))
        run_until(ws, is_json("state", value="listening"))
        ws.send_text(json.dumps({"type": "configure", "emotion": "serious", "background": "#102030", "width": 256, "height": 256}))
        ws.send_text("not json")                         # ignored, must not kill the session
        ws.send_text(json.dumps({"type": "listening", "value": False}))
        run_until(ws, is_json("state", value="idle"))


def test_second_session_is_refused_then_takeover(engine, client):
    with client.websocket_connect("/stream") as a:
        run_until(a, lambda k, m: k == "bin")
        with client.websocket_connect("/stream") as b:
            k, m = recv(b)
            assert m["type"] == "state" and m["value"] == "unavailable" and "busy" in m["reason"]
        with client.websocket_connect("/stream?takeover=1") as c:
            msgs = run_until(c, lambda k, m: k == "bin")
            assert states(msgs)[0] == "idle"
            run_until(a, is_json("state", value="unavailable"))
    time.sleep(0.3)
    assert engine.session is None                       # cleaned up after disconnect


def test_unknown_replica_and_not_ready(engine, client):
    with client.websocket_connect("/stream?replica_id=nope") as ws:
        k, m = recv(ws)
        assert m["value"] == "unavailable" and "not found" in m["reason"]
    engine.ready, engine.status = False, "loading models"
    with client.websocket_connect("/stream") as ws:
        k, m = recv(ws)
        assert m["value"] == "unavailable" and "not ready" in m["reason"]
    assert client.get("/health").json()["status"] == "starting"
    engine.ready = True


def test_post_speak_token_stream(client):
    r = client.post("/speak", json={"text": "Hi there."})
    assert r.status_code == 200
    with client.websocket_connect(r.json()["stream_url"]) as ws:
        msgs = run_until(ws, is_json("metrics"))
        assert "speaking" in states(msgs)
    assert client.post("/speak", json={"text": "  "}).status_code == 400


def test_gpu_oom_downgrades_and_recovers(engine, client):
    class Flaky(FakeBackend):
        failed = False

        def lipsync(self, rep, wav16, fps, start_idx, cancel):
            if not Flaky.failed:
                Flaky.failed = True
                raise GpuOom("CUDA out of memory (test)")
            yield from super().lipsync(rep, wav16, fps, start_idx, cancel)

        def downgrade(self):
            return "decoder switched (test)"

    engine.backend.__class__ = Flaky
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "speak", "text": "Memory is low."}))
        msgs = run_until(ws, is_json("metrics"))
        notes = [m for k, m, _ in msgs if k == "json" and m.get("type") == "notice"]
        assert notes and "GPU memory low" in notes[0]["message"]
        assert "unavailable" not in states(msgs)


def test_unrecoverable_oom_signals_unavailable(engine, client):
    class Dead(FakeBackend):
        def lipsync(self, *a, **k):
            raise GpuOom("CUDA out of memory (test)")
            yield

    engine.backend.__class__ = Dead
    with client.websocket_connect("/stream") as ws:
        ws.send_text(json.dumps({"type": "speak", "text": "Hello."}))
        msgs = run_until(ws, is_json("state", value="unavailable"))
        assert "memory" in msgs[-1][1]["reason"]
