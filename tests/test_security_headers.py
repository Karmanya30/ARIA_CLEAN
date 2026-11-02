from fastapi.testclient import TestClient

from api.main import app


def test_basic_hardening_headers_are_sent():
    r = TestClient(app).get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
