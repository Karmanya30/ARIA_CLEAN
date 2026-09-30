"""Tavus start/end recovery: orphaned calls, a stale cached persona, ending exactly the call asked for. Fake Tavus, no network."""
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import avatar


class FakeTavus:
    def __init__(self, active=(), reject_personas=()):
        self.active, self.reject, self.ended, self.deleted, self.created = list(active), set(reject_personas), [], [], 0

    def get(self, url, params=None, **kw):
        return _Resp(200, {"data": [{"conversation_id": c, "status": "active"} for c in self.active]})

    def post(self, url, json=None, **kw):
        if url.endswith("/end"):
            cid = url.split("/")[-2]
            self.ended.append(cid)
            self.active = [c for c in self.active if c != cid]
            return _Resp(200, {})
        if url.endswith("/personas"):
            self.created += 1
            return _Resp(200, {"persona_id": f"p{self.created}"})
        if json["persona_id"] in self.reject:
            return _Resp(400, {"message": "Invalid persona_id"})
        if self.active:
            return _Resp(400, {"message": "maximum concurrent conversations reached"})
        self.active.append("new-call")
        return _Resp(200, {"conversation_id": "new-call", "conversation_url": "https://tavus.daily.co/new-call"})

    def delete(self, url, **kw):
        self.deleted.append(url.split("/")[-1])
        return _Resp(200, {})


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture
def tavus(monkeypatch, tmp_path):
    def install(fake, cached_persona=None):
        cache = tmp_path / "persona.json"
        if cached_persona:
            cache.write_text(json.dumps({"base_url": "https://tunnel.test/v1/s1", "persona_id": cached_persona}))
        monkeypatch.setattr(avatar, "_PERSONA_CACHE_FILE", cache)
        monkeypatch.setattr(avatar, "requests", type("R", (), {"get": fake.get, "post": fake.post, "delete": fake.delete,
                                                             "RequestException": Exception, "Response": _Resp}))
        monkeypatch.setattr(avatar, "_require_env", lambda: None)
        monkeypatch.setattr(avatar, "_get_ngrok_url", lambda port: "https://tunnel.test")
        monkeypatch.setattr(avatar, "_ACTIVE_CONVERSATION_ID", None)
        return fake
    return install


def test_orphaned_call_and_stale_persona_no_longer_block_a_new_call(tavus):
    fake = tavus(FakeTavus(active=["orphan-from-last-run"], reject_personas={"p-stale"}), cached_persona="p-stale")
    res = TestClient(app).post("/api/tavus/start", json={"session_id": "s1"})
    assert res.status_code == 200 and res.json()["conversation_id"] == "new-call"
    assert fake.ended == ["orphan-from-last-run"] and fake.created == 1 and "p-stale" not in fake.active


def test_end_with_an_id_only_ends_that_call(tavus):
    fake = tavus(FakeTavus())
    client = TestClient(app)
    client.post("/api/tavus/start", json={"session_id": "s1"})
    client.post("/api/tavus/end", json={"conversation_id": "old-call"})  # a late end from a previous attempt
    assert fake.ended == ["old-call"] and "new-call" in fake.active
    client.post("/api/tavus/end")  # no body: ends the active call, as before
    assert fake.ended[-1] == "new-call"
