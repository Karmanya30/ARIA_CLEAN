"""The New ARIA Avatar's GPU service: which addresses the page is told about and the pass it is given (no network)."""
import hmac
import time

from fastapi.testclient import TestClient

from api.main import app


def _valid(token: str, secret: str) -> bool:
    """The check scripts/musetalk_server.py makes on every request."""
    expiry, _, sig = token.partition(".")
    return expiry.isdigit() and int(expiry) > time.time() and hmac.compare_digest(sig, hmac.new(secret.encode(), expiry.encode(), "sha256").hexdigest())


def test_nothing_configured_means_use_the_local_server(monkeypatch):
    monkeypatch.delenv("ARIA_LIPSYNC_URLS", raising=False)
    monkeypatch.delenv("ARIA_LIPSYNC_SECRET", raising=False)
    assert TestClient(app).get("/api/avatar/lipsync").json() == {"endpoints": []}


def test_addresses_keep_their_order_and_share_a_pass_the_gpu_accepts(monkeypatch):
    monkeypatch.setenv("ARIA_LIPSYNC_URLS", " https://one.example/ , https://two.example ")
    monkeypatch.setenv("ARIA_LIPSYNC_SECRET", "s3cret")
    endpoints = TestClient(app).get("/api/avatar/lipsync").json()["endpoints"]
    assert [e["url"] for e in endpoints] == ["https://one.example", "https://two.example"]
    assert _valid(endpoints[0]["token"], "s3cret") and not _valid(endpoints[0]["token"], "another-secret")
    assert endpoints[0]["token"].split(".")[0].isdigit() and int(endpoints[0]["token"].split(".")[0]) - time.time() <= 7200


def test_addresses_without_a_secret_are_not_offered(monkeypatch):
    monkeypatch.setenv("ARIA_LIPSYNC_URLS", "https://one.example")
    monkeypatch.delenv("ARIA_LIPSYNC_SECRET", raising=False)
    assert TestClient(app).get("/api/avatar/lipsync").json() == {"endpoints": []}  # an unprotected GPU would be free for anyone
