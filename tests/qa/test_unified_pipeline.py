"""One answer pipeline for every entry point: the SAME question goes through POST /api/chat in all four modes,
/api/instruments/ask, the market-chip (news item) form of /api/chat, the Tavus callback, the Live Avatar socket and the
company-intelligence endpoint, and each of them must reach modules.qa.pipeline with equivalent normalised input and get
the same grounding / disclaimer treatment. Network and model are stubbed."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules.qa import pipeline, trust
from modules.qa.models import Channel, ChatMode, QARequest

client = TestClient(app)

QUESTION = "wat is the p/e of infosys and is it expensive"  # text-speak on purpose: every channel must repair it the same way
NORMALISED = "what is the p/e of infosys and is it expensive"
INVENTED = "31.7"  # appears in no fetched data
MODES = [m.value for m in ChatMode]

IT = {"id": "stock:INFY.NS", "symbol": "INFY.NS", "name": "Infosys Limited", "type": "stock", "exchange": "NSE", "currency": "INR"}
QUOTE = {"id": IT["id"], "name": "Infosys Limited", "price": 1500.5, "change_pct": 0.4, "as_of": "2026-10-20T10:00:00", "pe": 24.5,
         "currency": "INR", "type": "stock", "source": "test", "stale": False}
PROFILE = {"what_is": "A listed IT services company.", "description": "IT services.", "risk_tags": [], "stats": {"return_1y_pct": 8.0}}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No network, no model, no background speech; a stub 'fetched data' that every channel must stay within."""
    from modules.market import instruments as I

    monkeypatch.setattr("modules.qa.present.register_later", lambda fn: "synthetic-audio")
    monkeypatch.setattr(I, "resolve", lambda iid: IT if iid == IT["id"] else (_ for _ in ()).throw(I.NotFound(iid)))
    monkeypatch.setattr(I, "quote", lambda it: dict(QUOTE))
    monkeypatch.setattr(I, "profile", lambda it: dict(PROFILE))
    monkeypatch.setattr(I, "sip", lambda it, m, y: (_ for _ in ()).throw(I.Unsupported("no")))
    monkeypatch.setattr("shared.news.fetch_news", lambda *a, **k: [])
    monkeypatch.setattr("modules.qa.focus.market_snapshot", lambda: None)
    # The chat-style routes end in the equity-research module; its (stubbed) answer quotes a number nobody fetched.
    monkeypatch.setattr("core.orchestrator.equity_research_pipeline", lambda q, user_id="default": {
        "domain": "investment", "query": q, "context": {"stock_data": {"pe": 24.5, "price": 1500.5}},
        "response": f"Infosys trades at a P/E of {INVENTED}, which is on the rich side. Its price is 1500.5."})


@pytest.fixture
def spy(monkeypatch):
    """Records every QARequest that reaches the pipeline (answer or lookup) and what came back."""
    seen: list[tuple[str, QARequest, object]] = []
    real_answer, real_lookup = pipeline.answer, pipeline.lookup

    def answer(req):
        out = real_answer(req)
        seen.append(("answer", req, out))
        return out

    def lookup(req, fetch):
        out = real_lookup(req, fetch)
        seen.append(("lookup", req, out))
        return out

    monkeypatch.setattr(pipeline, "answer", answer)
    monkeypatch.setattr(pipeline, "lookup", lookup)
    return seen


def _sid() -> str:
    return "qa-" + uuid.uuid4().hex[:10]


def _chat(mode, **extra):
    return client.post("/api/chat", json={"query": QUESTION, "session_id": _sid(), "mode": mode, "owner_id": "owner-1", **extra}).json()


def _instrument():
    return client.post("/api/instruments/ask", json={"id": IT["id"], "question": QUESTION, "session_id": _sid(), "owner_id": "owner-1"}).json()


def _chip():
    return client.post("/api/chat", json={"query": QUESTION, "session_id": _sid(), "owner_id": "owner-1",
                                          "system_context": "Headline: Infosys wins a deal. Sentiment score 0.4"}).json()


def _tavus():
    r = client.post(f"/v1/{_sid()}/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": QUESTION}], "stream": False})
    assert r.status_code == 200
    return r.json()


def _live():
    from ai.speech import live_tts

    live_tts.synthesize = lambda text: (b"RIFFfake", "audio/wav")
    with client.websocket_connect("/api/live/ws") as ws:
        ws.send_json({"type": "user", "text": QUESTION, "session_id": _sid(), "owner_id": "owner-1", "turn": 1})
        msgs = []
        while not msgs or msgs[-1]["type"] != "done":
            msgs.append(ws.receive_json())
    return msgs


def _intelligence(monkeypatch):
    monkeypatch.setattr("modules.equity_research.intelligence.pipeline.company_intelligence",
                        lambda q: {"domain": "company_intelligence", "company": {"name": "Infosys", "symbol": "INFY.NS"}, "intelligence": {}})
    return client.get("/api/research/intelligence", params={"q": QUESTION, "owner_id": "owner-1"}).json()


ENTRIES = [
    *[pytest.param(lambda m=m: _chat(m), Channel.CHAT, ChatMode.parse(m), id=f"chat[{m}]") for m in MODES],
    pytest.param(_instrument, Channel.INSTRUMENT, ChatMode.NORMAL, id="instrument-ask"),
    pytest.param(_chip, Channel.MARKET_CHIP, ChatMode.NORMAL, id="market-chip"),
    pytest.param(_tavus, Channel.AVATAR, ChatMode.TAVUS, id="tavus-callback"),
    pytest.param(_live, Channel.AVATAR, ChatMode.LIVE, id="live-avatar-socket"),
]


@pytest.mark.parametrize("call,channel,mode", ENTRIES)
def test_every_entry_point_reaches_the_one_pipeline_with_the_same_normalised_input(call, channel, mode, spy, mock_llm):
    mock_llm.set_response(f"Infosys trades at a P/E of {INVENTED}. Its price is 1500.5.")
    call()
    answers = [s for s in spy if s[0] == "answer"]
    assert len(answers) == 1, "exactly one pipeline call per question"
    _, req, out = answers[0]
    assert req.channel is channel and req.mode is mode
    assert pipeline.understand(req.query)[0] == NORMALISED  # same repair of the same typo, whichever door it came through
    assert out.qa["normalized_query"] == NORMALISED and out.qa["pipeline"] == "qa.v1"
    assert out.qa["mode"] == mode.value and out.qa["channel"] == channel.value
    assert {"total_ms", "understand_ms"} <= set(out.qa["latency_ms"])  # latency metrics on every channel


@pytest.mark.parametrize("call", [e.values[0] for e in ENTRIES], ids=[e.id for e in ENTRIES])
def test_every_entry_point_applies_the_same_grounding_and_disclaimer(call, spy, mock_llm):
    mock_llm.set_response(f"Infosys trades at a P/E of {INVENTED}. Its price is 1500.5.")
    call()
    out = [s for s in spy if s[0] == "answer"][0][2]
    assert INVENTED not in out.response, "a number that is in no fetched data must never reach the user"
    assert out.response.lower().count("not investment advice") == 1
    assert out.trust["disclaimer"] == trust.DISCLAIMER_LINE and out.trust["accuracy_caveat"] == trust.ACCURACY_CAVEAT
    assert out.grounding["numbers_checked"] is True and out.grounding["passed"] is False


def test_company_intelligence_goes_through_the_pipeline_too(spy, monkeypatch):
    body = _intelligence(monkeypatch)
    kind, req, out = spy[0]
    assert kind == "lookup" and req.channel is Channel.REPORT
    assert out["qa"]["normalized_query"] == NORMALISED and body["trust"]["disclaimer"] == trust.DISCLAIMER_LINE


def test_the_mode_never_changes_the_written_answer(mock_llm):
    mock_llm.set_response("Rewritten for the ear.")
    written = {m: _chat(m)["response"] for m in MODES}
    assert len(set(written.values())) == 1
    spoken = {m: _chat(m).get("spoken") for m in MODES}
    assert [m for m, s in spoken.items() if s] == [ChatMode.LIVE.value, ChatMode.TAVUS.value]  # only these two add a spoken version


def test_unknown_mode_strings_fall_back_to_normal_and_legacy_live_is_accepted():
    assert ChatMode.parse("nonsense") is ChatMode.NORMAL and ChatMode.parse("Live Avatar") is ChatMode.LIVE and ChatMode.parse(None) is ChatMode.NORMAL


# ── the invented-numbers guard, channel by channel ─────────────────────────────────────────────────────────────────────
def test_invented_numbers_are_replaced_on_the_instrument_channel(mock_llm):
    mock_llm.set_response(f"P/E is {INVENTED}.")
    r = _instrument()
    assert INVENTED not in r["response"] and r["grounding"]["fallback"] and "1,500.50" in r["response"]


def test_invented_numbers_are_replaced_on_the_market_chip_channel(mock_llm):
    mock_llm.set_response(f"It could rise {INVENTED} percent.")
    r = _chip()
    assert INVENTED not in r["response"] and r["grounding"]["fallback"] and r["domain"] == "news"


def test_invented_numbers_are_removed_from_chat_answers_in_every_mode():
    for mode in MODES:
        r = _chat(mode)
        assert INVENTED not in r["response"] and "1500.5" in r["response"]  # the grounded sentence stays
        assert r["grounding"]["removed_numbers"] == [31.7]


def test_a_grounded_chat_answer_is_left_alone(monkeypatch):
    monkeypatch.setattr("core.orchestrator.equity_research_pipeline", lambda q, user_id="default": {
        "domain": "investment", "query": q, "context": {"stock_data": {"pe": 24.5}}, "response": "Infosys trades at a P/E of 24.5, rounded 24.50."})
    r = _chat(ChatMode.NORMAL.value)
    assert "24.5" in r["response"] and r["grounding"]["passed"] is True


# ── persistence per owner, across channels ─────────────────────────────────────────────────────────────────────────────
def test_history_is_saved_per_owner_for_every_channel_and_other_owners_are_refused(mock_llm):
    mock_llm.set_response("Infosys is an IT company. Its price is 1500.5.")
    owner, sessions = "alice-" + uuid.uuid4().hex[:6], {}
    for name, body, url in (("chat", {"query": QUESTION, "mode": "Normal Mode"}, "/api/chat"),
                            ("instrument", {"question": QUESTION, "id": IT["id"]}, "/api/instruments/ask"),
                            ("chip", {"query": QUESTION, "system_context": "a headline"}, "/api/chat")):
        sessions[name] = _sid()
        assert client.post(url, json={**body, "session_id": sessions[name], "owner_id": owner}).status_code == 200
    for name, sid in sessions.items():
        turns = client.get("/api/chat/history", params={"session_id": sid, "owner_id": owner}).json()["history"]
        assert len(turns) == 1 and turns[0]["query"] == QUESTION, name
        assert turns[0]["response"]["qa"]["pipeline"] == "qa.v1" and turns[0]["response"]["trust"]
        assert client.get("/api/chat/history", params={"session_id": sid, "owner_id": "mallory"}).status_code == 403
    assert client.post("/api/chat", json={"query": "hello", "session_id": sessions["chat"], "owner_id": "mallory"}).status_code == 403
    assert client.post("/api/instruments/ask", json={"id": IT["id"], "question": "price?", "session_id": sessions["instrument"], "owner_id": "mallory"}).status_code == 403
    from shared import user_store as store
    from shared.conversation_memory import Conversation

    with store._SessionLocal() as db:
        owned = {c.id for c in db.query(Conversation).filter_by(owner_id=owner)}
    assert set(sessions.values()) <= owned


def test_the_same_request_id_replays_instead_of_answering_twice(mock_llm):
    sid, body = _sid(), {"id": IT["id"], "question": "price?", "owner_id": "o", "request_id": "r-1"}
    first = client.post("/api/instruments/ask", json={**body, "session_id": sid}).json()
    calls = len(mock_llm.calls)
    assert client.post("/api/instruments/ask", json={**body, "session_id": sid}).json()["response"] == first["response"]
    assert len(mock_llm.calls) == calls


# ── same focus semantics everywhere ────────────────────────────────────────────────────────────────────────────────────
def test_small_talk_and_crisis_inside_an_instrument_drawer_use_the_shared_handling(mock_llm):
    mock_llm.set_response("Hello! What can I help you with?")
    hi = client.post("/api/instruments/ask", json={"id": IT["id"], "question": "hi", "session_id": _sid()}).json()
    assert hi["domain"] == "smalltalk"
    care = client.post("/api/instruments/ask", json={"id": IT["id"], "question": "I want to kill myself", "session_id": _sid()}).json()
    assert care["domain"] == "care"


def test_unknown_instrument_is_a_404_and_blank_question_a_422():
    assert client.post("/api/instruments/ask", json={"id": "bogus:1", "question": "x", "session_id": "s"}).status_code == 404
    assert client.post("/api/instruments/ask", json={"id": IT["id"], "question": "  ", "session_id": "s"}).status_code == 422


def test_company_in_focus_resolves_it_for_a_chat_question(monkeypatch, mock_llm):
    seen = []
    monkeypatch.setattr("core.orchestrator.equity_research_pipeline", lambda q, user_id="default": seen.append(q) or {
        "domain": "investment", "query": q, "context": {"x": 1}, "response": "ok"})
    client.post("/api/chat", json={"query": "what is the p/e ratio", "session_id": _sid(), "context": {"company": "INFY"}})
    assert seen and "INFY" in seen[0]


# ── error degradation, channel by channel ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("call", [e.values[0] for e in ENTRIES], ids=[e.id for e in ENTRIES])
def test_a_dead_model_degrades_honestly_on_every_channel(call, mock_llm, monkeypatch):
    mock_llm.set_response("Error: all backends down")
    monkeypatch.setattr("core.orchestrator.equity_research_pipeline", lambda q, user_id="default": {
        "domain": "investment", "query": q, "context": {"x": 1}, "response": "Error: all backends down"})
    out = call()
    texts = [m.get("text", "") for m in out] if isinstance(out, list) else [str(out)]
    assert not any("all backends down" in t for t in texts), "a raw provider error must never reach the user or the speaker"
    if isinstance(out, dict) and "response" in out:
        assert not out["response"].lower().startswith("error")
        assert out.get("degraded") or out["grounding"]["fallback"]


def test_an_unexpected_failure_is_a_clean_error_not_a_hang(monkeypatch):
    monkeypatch.setattr("core.orchestrator.equity_research_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):  # surfaced to the framework (500), and the turn is marked interrupted, not left pending
        client_raise = TestClient(app, raise_server_exceptions=True)
        client_raise.post("/api/chat", json={"query": QUESTION, "session_id": _sid()})
