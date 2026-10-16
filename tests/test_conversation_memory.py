"""Synthetic memory evaluation; no real user data or external model calls."""
import json
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from shared import conversation_memory as m, user_store
from core import session

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "memory.db").as_posix(), connect_args={"check_same_thread": False})
    user_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(user_store, "_SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setenv("ARIA_MEMORY_SEMANTIC", "0")
    monkeypatch.setenv("ARIA_MEMORY_TOKEN_BUDGET", "6000")
    monkeypatch.delenv("ARIA_TOKENIZER_PATH", raising=False)
    m._tokenizer.cache_clear()
    session._SESSIONS.clear()
    token = user_store.current_owner.set("alice")
    yield
    user_store.current_owner.reset(token)
    session._SESSIONS.clear()
    engine.dispose()


def turn(sid, query, answer="Recorded.", **artifacts):
    return session.execute_turn(sid, query, lambda: {"response": answer, **artifacts})


def test_archive_recovers_after_cache_loss():
    turn("one", "Acme WACC is 12.5% on 2026-01-03")
    session._SESSIONS.clear()
    assert session.get_session("one")["history"][0]["query"] == "Acme WACC is 12.5% on 2026-01-03"


def test_recent_followup_contains_both_roles():
    turn("one", "Analyze Acme", "Acme's debt is 42 crore.")
    c = m.build_context("one", "what about it?")
    assert "42 crore" in c["text"]
    assert c["diagnostics"]["reference_resolved"]


def test_cross_conversation_exact_number_and_date():
    turn("old", "Acme hurdle rate 12.5% agreed 2026-01-03")
    c = m.build_context("new", "Acme hurdle rate")
    assert "12.5%" in c["text"] and "2026-01-03" in c["text"]


def test_corrections_preserve_old_and_new_in_temporal_order():
    turn("old", "Acme revenue assumption 120 crore")
    turn("new", "Correction: Acme revenue assumption is 140 crore instead")
    c = m.build_context("third", "Acme revenue assumption")
    assert c["text"].index("120 crore") < c["text"].index("140 crore")
    assert "supersede" in m.MEMORY_RULES


def test_combines_multiple_prior_tasks():
    turn("a", "Acme target margin is 18%")
    turn("b", "Acme WACC assumption 11%")
    c = m.build_context("c", "Acme valuation assumptions")
    assert "18%" in c["text"] and "11%" in c["text"]


def test_exact_keyword_finds_old_detail_beyond_recent_window():
    turn("a", "Project Copperfin agreed exit multiple is 17.3")
    for i in range(15):
        turn("a", f"Unrelated lunch item {i}")
    c = m.build_context("a", "Copperfin exit multiple")
    assert "17.3" in c["text"]


def test_semantic_channel_can_find_different_words(monkeypatch):
    turn("a", "Liquidity buffer should cover six months")
    monkeypatch.setenv("ARIA_MEMORY_SEMANTIC", "1")
    monkeypatch.setattr(m, "_embedding", lambda text: [1.0, 0.0])
    c = m.build_context("b", "emergency runway")
    assert "six months" in c["text"] and c["diagnostics"]["semantic"] == "ok"


def test_semantic_failure_preserves_lexical_retrieval(monkeypatch):
    turn("a", "Copperfin memo")
    monkeypatch.setenv("ARIA_MEMORY_SEMANTIC", "1")
    def unavailable(text):
        raise RuntimeError("offline")
    monkeypatch.setattr(m, "_embedding", unavailable)
    c = m.build_context("b", "Copperfin")
    assert "Copperfin" in c["text"] and c["diagnostics"]["semantic"] == "unavailable"


def test_tool_result_and_document_references_are_retrieved():
    turn("a", "Acme audit", tool_results={"cashflow": 812, "document_id": "filing-2025"})
    c = m.build_context("b", "Acme audit")
    assert "812" in c["text"] and "filing-2025" in c["text"]


def test_long_context_is_bounded_without_mutating_archive(monkeypatch):
    for i in range(12):
        turn("a", f"Acme detail {i} " + "word " * 100)
    monkeypatch.setenv("ARIA_MEMORY_TOKEN_BUDGET", "1200")
    c = m.build_context("a", "Acme")
    assert c["diagnostics"]["memory_tokens"] <= 1200
    assert c["diagnostics"]["excluded_ids"]
    assert len(session.get_session("a")["history"]) == 12


def test_updates_are_visible_without_stale_retrieval_cache():
    turn("a", "Acme rate 12%")
    assert "12%" in m.build_context("b", "Acme")["text"]
    turn("a", "Correction Acme rate 13%")
    assert "13%" in m.build_context("b", "Acme")["text"]


def test_owner_isolation_and_known_conversation_denied():
    turn("private", "Acme secret margin 99%")
    token = user_store.current_owner.set("bob")
    try:
        assert "99%" not in m.build_context("bob-chat", "Acme")["text"]
        with pytest.raises(PermissionError):
            session.get_session("private")
        with pytest.raises(PermissionError):
            session.clear_session("private")
    finally:
        user_store.current_owner.reset(token)


def test_successful_retry_replays_without_duplicate_generation():
    calls = []
    def answer():
        calls.append(1)
        return {"response": "done"}
    a = session.execute_turn("a", "question", answer, "request1")
    assert session.execute_turn("a", "question", answer, "request1") == a
    assert len(calls) == 1 and len(session.get_session("a")["history"]) == 1
    with pytest.raises(ValueError):
        session.execute_turn("a", "different", answer, "request1")


def test_interrupted_request_is_archived_and_retryable():
    def interrupted():
        raise RuntimeError("connection lost")
    with pytest.raises(RuntimeError):
        session.execute_turn("a", "important input", interrupted, "request1")
    with user_store._SessionLocal() as db:
        row = db.scalar(select(m.Turn))
        assert row.status == "interrupted" and row.query == "important input"
    session.execute_turn("a", "important input", lambda: {"response": "recovered"}, "request1")
    assert len(session.get_session("a")["history"]) == 1


def test_failed_model_output_is_not_replayed_as_success():
    session.execute_turn("a", "question", lambda: {"response": "Error: offline"}, "r")
    got = session.execute_turn("a", "question", lambda: {"response": "Now available"}, "r")
    assert got["response"] == "Now available"


def test_clear_hides_history_without_deleting_source_records():
    turn("a", "Acme private figure")
    session.clear_session("a")
    assert session.get_session("a")["history"] == []
    assert not m.retrieve("b", "Acme")[0]
    with user_store._SessionLocal() as db:
        assert db.scalar(select(m.Turn)).query == "Acme private figure"


def test_task_state_checkpoint_survives_restart():
    session.get_session("a")["finance_pending"] = {"field": "age"}
    # execute_turn reloads canonical state, so checkpoint explicit module changes first.
    m.checkpoint("a", session.get_session("a"))
    session._SESSIONS.clear()
    assert session.get_session("a")["finance_pending"] == {"field": "age"}


def test_provider_receives_history_without_changing_stable_prefix(monkeypatch):
    from ai.llm import groq_client as llm
    turn("a", "Acme historical price was 123 on 2025-01-01")
    calls = []
    monkeypatch.setattr(llm, "_BACKENDS", (("test", lambda p,s,m: calls.append((p,s)) or "Evidence answer."),))
    with m.context_for("a", "why that price?"):
        llm.generate_response("why that price?")
    assert "123" in calls[0][0] and "Historical prices" in calls[0][0]
    assert calls[0][1] == "You are a helpful AI assistant."
    assert m.active_context.get() is None


def test_classification_never_receives_private_history(monkeypatch):
    from ai.llm import groq_client as llm
    turn("a", "private financial note")
    calls = []
    monkeypatch.setattr(llm, "_BACKENDS", (("test", lambda p,s,m: calls.append(p) or "yes"),))
    with m.context_for("a", "note"):
        llm.generate_response("classify", system_prompt="Only JSON")
    assert calls == ["classify"]


def test_general_question_and_missing_evidence_receive_help(monkeypatch):
    from core.orchestrator import handle_query
    seen = []
    def answer(prompt, system_prompt=None):
        seen.append(system_prompt)
        return "Here is a Python example."
    monkeypatch.setattr("ai.llm.groq_client.generate_response", answer)
    result = handle_query("write me a Python program", "a", correct=False)
    assert result["domain"] == "general" and result["response"]
    assert "Never invent" in seen[0] and "safety" in seen[0] and "missing" in seen[0]


def test_system_context_path_is_persisted_and_scoped(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    from api.routes import chat
    monkeypatch.setattr(chat, "register_later", lambda fn: "audio-test")
    monkeypatch.setattr("ai.llm.groq_client.generate_response", lambda *a, **k: "News answer.")
    client = TestClient(app)
    payload = {"query": "Explain this", "session_id": "news", "owner_id": "alice", "system_context": "headline", "request_id": "r"}
    assert client.post("/api/chat", json=payload).status_code == 200
    assert client.post("/api/chat", json=payload).json()["audio_token"] == "audio-test"
    hist = client.get("/api/chat/history", params={"session_id": "news", "owner_id": "alice"})
    assert len(hist.json()["history"]) == 1
    assert client.get("/api/chat/history", params={"session_id": "news", "owner_id": "bob"}).status_code == 403


def test_debug_mode_is_opt_in_and_returns_no_transcript(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    params = {"session_id": "a", "owner_id": "alice", "query": "Acme"}
    assert client.get("/api/chat/context", params=params).status_code == 404
    turn("a", "Acme secret")
    monkeypatch.setenv("ARIA_CONTEXT_DEBUG", "1")
    response = client.get("/api/chat/context", params=params)
    assert response.status_code == 200 and "secret" not in response.text


def test_database_claim_blocks_duplicate_workers_and_recovers_expired_lease(monkeypatch):
    request = m.begin("a", "input", "r")
    with pytest.raises(m.RequestBusy):
        m.begin("a", "input", "r")
    with user_store._SessionLocal() as db:
        lease = db.get(m.RequestLease, request["id"])
        lease.expires_at = 0
        db.commit()
    replacement = m.begin("a", "input", "r")
    token = m.active_request.set(request)
    try:
        with pytest.raises(m.RequestBusy):
            m.complete("a", "input", {"response": "late result"})
    finally:
        m.active_request.reset(token)
    token = m.active_request.set(replacement)
    try:
        m.complete("a", "input", {"response": "new result"})
    finally:
        m.active_request.reset(token)
    assert m.load("a")["history"][0]["response"]["response"] == "new result"


def test_exception_after_module_save_does_not_mark_partial_response_complete():
    def interrupted():
        session.save_turn("a", "input", {"response": "partial"})
        raise RuntimeError("failed before final result")
    with pytest.raises(RuntimeError):
        session.execute_turn("a", "input", interrupted)
    assert m.load("a")["history"] == []
    with user_store._SessionLocal() as db:
        assert db.scalar(select(m.Turn)).status == "interrupted"


def test_saved_research_episode_is_retrieved_with_provenance():
    with user_store._SessionLocal() as db:
        db.add(user_store.ResearchReportRecord(id="r1", owner_id="alice", symbol="ACME", company="Acme",
                                               version=1, report_json=json.dumps({"fair_value": 321, "sources": ["filing-2025"]})))
        db.commit()
    c = m.build_context("new", "Acme fair value")
    assert "321" in c["text"] and "filing-2025" in c["text"] and "report:r1" in c["text"]


def test_research_cache_keys_include_owner_and_model(monkeypatch):
    from modules.equity_research.intelligence import agents
    agents.clear_llm_cache()
    calls = []
    monkeypatch.setattr(agents, "_ask_uncached", lambda *args: calls.append(args) or {"text": "ok"})
    agents._ask("system", "prompt", {}, "model-a")
    agents._ask("system", "prompt", {}, "model-a")
    agents._ask("system", "prompt", {}, "model-b")
    token = user_store.current_owner.set("bob")
    try:
        agents._ask("system", "prompt", {}, "model-a")
    finally:
        user_store.current_owner.reset(token)
    assert len(calls) == 3
    agents.clear_llm_cache()


def test_provider_cache_metrics_log_only_counts(monkeypatch):
    from types import SimpleNamespace
    from ai.llm import groq_client as llm
    captured = []
    class Log:
        def bind(self, **fields):
            captured.append(fields)
            return self
        def info(self, message):
            pass
    monkeypatch.setattr(llm, "logger", Log())
    llm._record_usage("groq", "test", SimpleNamespace(usage={"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 80}, "completion_tokens": 5}), .1)
    assert captured[0]["cached_tokens"] == 80 and captured[0]["latency_ms"] == 100


def test_pronoun_followup_retains_live_financial_tool_routing(monkeypatch, mock_llm):
    from core import orchestrator
    turn("a", "Analyze TCS", "We discussed its valuation.")
    session.get_session("a")["adapt_tone"] = False
    calls = []
    monkeypatch.setattr(orchestrator, "equity_research_pipeline", lambda q, **kw: calls.append(q) or {"domain": "equity_research", "response": "Fetched quote."})
    result = orchestrator.handle_query("what about its share price?", "a", correct=False)
    assert calls and "TCS" in calls[0]
    assert result["query"] == "what about its share price?"
    assert result["domain"] == "equity_research"
