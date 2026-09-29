"""Persistence, history, download, regenerate and owner isolation for saved research reports.
These tests use the real SQLite store with throwaway owner ids and always clean up."""
import json
import uuid

import pytest
from _intel_fixtures import good_llm, make_snapshot
from fastapi.testclient import TestClient

from api.main import app
from modules.equity_research.intelligence import agents, pipeline as intel
from modules.equity_research.intelligence.data import Target
from modules.equity_research.intelligence.pipeline import _persist as real_persist
from shared import user_store

client = TestClient(app)


@pytest.fixture
def owner():
    owner_id = f"__pytest_{uuid.uuid4().hex}"
    yield owner_id
    with user_store._SessionLocal() as s:
        s.query(user_store.ResearchReportRecord).filter(user_store.ResearchReportRecord.owner_id.in_([owner_id, owner_id + "_b"])).delete(synchronize_session=False)
        s.commit()


@pytest.fixture
def make_report(monkeypatch):
    """Generate a real report from fixture data, with real persistence turned back on."""
    def _make(user_id: str, kind: str = "operating") -> dict:
        monkeypatch.setattr(intel, "_persist", real_persist)
        monkeypatch.setattr(intel, "resolve_target", lambda q: Target("TESTCO", "TESTCO.NS", "Test"))
        monkeypatch.setattr(intel, "gather", lambda t: make_snapshot(kind))
        monkeypatch.setattr(agents, "generate_response", good_llm())
        return intel.run_research("equity research report on Testco", user_id=user_id)
    return _make


# ── store ──────────────────────────────────────────────────────────────────
def test_generated_report_is_saved_and_versions_increment(owner, make_report):
    first, second = make_report(owner), make_report(owner)
    assert first["report_id"] and first["report"]["meta"]["version"] == 1 and second["report"]["meta"]["version"] == 2
    listing = user_store.list_research_reports(owner)
    assert [r["version"] for r in listing] == [2, 1] and {r["symbol"] for r in listing} == {"TESTCO.NS"}
    meta = listing[0]
    assert meta["status"] in ("publishable", "caveated") and meta["stance"] and meta["data_as_of"] == "2026-09-29" and meta["created_at"]


def test_saved_report_round_trips_completely(owner, make_report):
    res = make_report(owner)
    stored = user_store.get_research_report(owner, res["report_id"])
    assert stored["meta"]["id"] == res["report_id"]
    for key in ("cover", "stance", "forecast", "assumption_table", "scenarios", "facts", "audit", "markdown", "valuation", "debate"):
        assert stored[key] == json.loads(json.dumps(res["report"][key])), key


def test_reports_belong_to_their_owner_only(owner, make_report):
    res = make_report(owner)
    assert user_store.get_research_report(owner + "_b", res["report_id"]) is None
    assert user_store.list_research_reports(owner + "_b") == []
    assert user_store.delete_research_report(owner + "_b", res["report_id"]) is False
    assert user_store.delete_research_report(owner, res["report_id"]) is True
    assert user_store.get_research_report(owner, res["report_id"]) is None


def test_versions_are_counted_per_company_and_owner(owner, make_report):
    make_report(owner)
    make_report(owner + "_b")
    assert user_store.list_research_reports(owner + "_b")[0]["version"] == 1  # another owner starts at 1
    assert make_report(owner, "bank")["report"]["meta"]["version"] == 1  # a different company starts its own version count
    assert make_report(owner)["report"]["meta"]["version"] == 2  # the same company under the same owner: next version


def test_the_request_scoped_owner_overrides_the_session_id(owner, make_report):
    token = user_store.current_owner.set(owner)
    try:
        res = make_report("some-tab-session")
    finally:
        user_store.current_owner.reset(token)
    assert user_store.list_research_reports(owner)[0]["id"] == res["report_id"]
    assert user_store.list_research_reports("some-tab-session") == []


def test_a_storage_failure_returns_the_report_unsaved(monkeypatch, make_report, owner):
    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(user_store, "save_research_report", boom)
    res = make_report(owner)
    assert res["report_id"] is None and res["report"]["stance"] and "meta" not in res["report"]


# ── API ────────────────────────────────────────────────────────────────────
def test_history_view_and_get_endpoints(owner, make_report):
    rid = make_report(owner)["report_id"]
    listing = client.get("/api/research/reports", params={"owner_id": owner}).json()
    assert [r["id"] for r in listing] == [rid]
    body = client.get(f"/api/research/reports/{rid}", params={"owner_id": owner}).json()
    assert body["meta"]["version"] == 1 and body["cover"]["symbol"] == "TESTCO.NS"
    page = client.get(f"/api/research/reports/{rid}/html", params={"owner_id": owner})
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html") and "v1" in page.text and "Summary" in page.text


def test_downloads_in_every_format_with_sensible_filenames(owner, make_report):
    rid = make_report(owner)["report_id"]
    for fmt, needle, ctype in (("html", "<!doctype html>", "text/html"), ("md", "# ", "text/markdown"), ("json", '"facts"', "application/json")):
        r = client.get(f"/api/research/reports/{rid}/download", params={"owner_id": owner, "format": fmt})
        assert r.status_code == 200 and needle in r.text and r.headers["content-type"].startswith(ctype)
        disposition = r.headers["content-disposition"]
        assert disposition.startswith("attachment") and f"TESTCO.NS_equity_research_v1_" in disposition and disposition.endswith(f'.{fmt}"')
    assert json.loads(client.get(f"/api/research/reports/{rid}/download", params={"owner_id": owner, "format": "json"}).text)["meta"]["id"] == rid
    assert client.get(f"/api/research/reports/{rid}/download", params={"owner_id": owner, "format": "exe"}).status_code == 400


def test_other_owners_and_unknown_ids_get_404(owner, make_report):
    rid = make_report(owner)["report_id"]
    for path in (f"/api/research/reports/{rid}", f"/api/research/reports/{rid}/html", f"/api/research/reports/{rid}/download", "/api/research/reports/nope"):
        assert client.get(path, params={"owner_id": owner + "_b"}).status_code == 404
    assert client.get("/api/research/reports/nope", params={"owner_id": owner}).status_code == 404
    assert client.delete(f"/api/research/reports/{rid}", params={"owner_id": owner + "_b"}).status_code == 404


def test_regenerate_saves_the_next_version_and_delete_removes_one(owner, make_report):
    rid = make_report(owner)["report_id"]
    r = client.post(f"/api/research/reports/{rid}/regenerate", json={"owner_id": owner})
    assert r.status_code == 200 and r.json()["meta"]["version"] == 2 and r.json()["report_id"] != rid
    assert len(client.get("/api/research/reports", params={"owner_id": owner}).json()) == 2
    assert client.delete(f"/api/research/reports/{rid}", params={"owner_id": owner}).json() == {"status": "deleted"}
    remaining = client.get("/api/research/reports", params={"owner_id": owner}).json()
    assert [x["version"] for x in remaining] == [2]


def test_chat_route_saves_reports_under_the_device_owner(owner, monkeypatch):
    monkeypatch.setattr(intel, "_persist", real_persist)
    monkeypatch.setattr(intel, "resolve_target", lambda q: Target("TESTCO", "TESTCO.NS", "Test"))
    monkeypatch.setattr(intel, "gather", lambda t: make_snapshot())
    monkeypatch.setattr(agents, "generate_response", good_llm())
    from core import orchestrator

    monkeypatch.setattr(orchestrator, "validate_output", lambda q, r: {"available": False})
    import ai.llm.audio_script as audio_script
    import ai.speech.tts as tts

    monkeypatch.setattr(audio_script, "generate_audio_script", lambda text: "spoken")  # no LLM / network for TTS
    monkeypatch.setattr(tts, "synthesize", lambda text: None)
    res = client.post("/api/chat", json={"query": "give me an equity research report on TCS", "session_id": "tab-1", "owner_id": owner}).json()
    assert res["report_id"] and user_store.list_research_reports(owner)[0]["id"] == res["report_id"]
    assert user_store.list_research_reports("tab-1") == []  # not tied to the per-tab session
