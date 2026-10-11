"""WP5: validation API and the pipeline hook."""
import queue

import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules.equity_research.forecast import contracts as c
from modules.equity_research.forecast import jobs, store

client = TestClient(app)
BASE = "/api/research/validation"


@pytest.fixture
def api(tmpdb, monkeypatch):
    monkeypatch.setattr(jobs, "_last_bar", lambda s: "2026-01-02")
    monkeypatch.setattr(jobs, "_ensure_worker", lambda: None)  # never start a real job
    monkeypatch.setattr(jobs, "_queue", queue.Queue())  # a worker from an earlier test must not steal them


def test_round_trip(api):
    r = client.post(BASE, json={"symbol": "tcs.ns", "report_id": "rep"})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    run_id = r.json()["run_id"]
    got = client.get(f"{BASE}/{run_id}").json()
    assert got["symbol"] == "TCS.NS" and got["status"] == "queued" and got["progress"] == 0
    assert c.RunResult.model_validate(got).run_id == run_id
    assert client.get(f"{BASE}/latest", params={"symbol": "TCS.NS"}).json()["run_id"] == run_id
    assert client.post(BASE, json={"symbol": "TCS.NS"}).json()["run_id"] == run_id  # in flight: same run
    cancelled = client.post(f"{BASE}/{run_id}/cancel").json()
    assert cancelled["status"] == "failed" and cancelled["errors"] == ["cancelled"]
    assert client.post(BASE, json={"symbol": "TCS.NS", "force": True}).json()["run_id"] != run_id


def test_validation_errors(api):
    assert client.post(BASE, json={"symbol": "bad symbol!"}).status_code == 422
    assert client.post(BASE, json={"symbol": "A" * 21}).status_code == 422
    assert client.post(BASE, json={}).status_code == 422
    assert client.get(f"{BASE}/latest", params={"symbol": "no way"}).status_code == 422
    assert client.get(f"{BASE}/doesnotexist").status_code == 404
    assert client.post(f"{BASE}/doesnotexist/cancel").status_code == 404
    assert client.get(f"{BASE}/latest", params={"symbol": "NEVER.NS"}).json() == {"status": "not_run"}


# ---- pipeline hook --------------------------------------------------------
def test_pipeline_hook(monkeypatch):
    from modules.equity_research.intelligence import pipeline

    calls = []
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: calls.append(a))
    monkeypatch.setenv("ARIA_FORECAST", "0")
    pipeline._queue_forecast("TCS.NS", "rep")
    assert calls == []
    monkeypatch.setenv("ARIA_FORECAST", "1")
    pipeline._queue_forecast("TCS.NS", "rep")
    assert calls == [("TCS.NS", "rep")]

    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(jobs, "submit", boom)
    pipeline._queue_forecast("TCS.NS", None)  # must not raise
