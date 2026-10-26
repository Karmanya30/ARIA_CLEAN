"""Resolver contract, selection, safe dispatch and transport. No live API calls."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared import intent_resolver as resolver, user_store
from core import orchestrator, session


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "intent.db").as_posix(), connect_args={"check_same_thread": False})
    user_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(user_store, "_SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setenv("ARIA_INTENT_RESOLVER", "1")
    token = user_store.current_owner.set("intent-user")
    session._SESSIONS.clear()
    yield
    session._SESSIONS.clear()
    user_store.current_owner.reset(token)
    engine.dispose()


HISTORY = [{"message_id": 7, "query": "Research report on TCS", "response": {"response": "TCS report: valuation and risks."}}]


def prediction(intent="equity_research", query="Research report on Infosys", **overrides):
    result = {"intent": intent, "standalone_query": query, "referenced_topic": "Infosys",
              "required_capability": resolver._CAPABILITY[intent], "missing_inputs": [],
              "confidence": .95, "clarification_question": "", "source_turn_ids": ["7"]}
    result.update(overrides)
    return result


@pytest.mark.parametrize("query,history,pending,clear", [
    ("ok", HISTORY, None, False), ("yes", HISTORY, None, False),
    ("Write a Python program", HISTORY, None, False), ("What is compound interest?", [], None, True),
    ("Can I afford a car?", [], None, True), ("40000", HISTORY, {"field": "monthly_income"}, False),
    ("How is Nifty today?", [], None, True), ("hello", [], None, True),
    ("What is the weather in Chennai?", [], None, True),
])
def test_clear_requests_and_simple_replies_do_not_call_resolver(query, history, pending, clear):
    call = Mock()
    answer, diagnostic = resolver.resolve(query, history, pending, clear_route=clear, caller=call)
    assert answer is None and diagnostic["status"] == "fast_path"
    call.assert_not_called()


@pytest.mark.parametrize("query", ["do the same for Infosys", "the second one", "use the earlier assumptions", "help me work this out"])
def test_ambiguous_requests_are_selected(query):
    assert resolver.needs_resolution(query, HISTORY, None, clear_route=False)


def test_same_model_receives_both_sides_of_recent_exchange_without_profiles():
    call = Mock(return_value=prediction())
    answer, diagnostic = resolver.resolve("do the same for Infosys", HISTORY, caller=call)
    assert answer.intent == "equity_research" and diagnostic["status"] == "resolved"
    payload = json.loads(call.call_args.args[0])
    assert payload["recent_turns"][0]["assistant"] == "TCS report: valuation and risks."
    assert "profile" not in payload
    assert call.call_args.kwargs["timeout"] == 8
    assert resolver.current_interpretation.get() is None


@pytest.mark.parametrize("changes", [
    {"intent": "execute"}, {"confidence": 2}, {"confidence": True}, {"extra": "save_profile"},
    {"required_capability": "financial_calculation"}, {"source_turn_ids": ["other-user-turn"]},
    {"source_turn_ids": []}, {"standalone_query": "Research Infosys at price 987654"},
    {"standalone_query": "Research Infosys at price 7"},
])
def test_invalid_or_ungrounded_interpretations_fall_back(changes):
    answer, diagnostic = resolver.resolve("do the same for Infosys", HISTORY, caller=lambda *a, **kw: prediction(**changes))
    assert answer is None and diagnostic["status"] == "invalid"


@pytest.mark.parametrize("query,rewrite", [("same for 5000", "same for Infosys"),
                                          ("do not use the earlier assumptions", "Use earlier assumptions")])
def test_rewrite_cannot_drop_current_numbers_or_negation(query, rewrite):
    answer, diagnostic = resolver.resolve(query, HISTORY, caller=lambda *a, **kw: prediction(query=rewrite))
    assert answer is None and diagnostic["status"] == "invalid"


@pytest.mark.parametrize("changes", [{"confidence": .5}, {"missing_inputs": ["which comparison"]},
                                     {"intent": "clarify", "required_capability": "clarification"}])
def test_uncertainty_requests_one_clarification_instead_of_executing(changes):
    answer, diagnostic = resolver.resolve("do the same for Infosys", HISTORY, caller=lambda *a, **kw: prediction(**changes))
    assert answer.intent == "clarify" and answer.clarification_question
    assert diagnostic["status"] == "clarification"


def test_timeout_attempts_once_and_falls_back():
    call = Mock(side_effect=TimeoutError("private request content"))
    answer, diagnostic = resolver.resolve("do the same for Infosys", HISTORY, caller=call)
    assert answer is None and diagnostic["status"] == "unavailable" and call.call_count == 1


def test_disabled_resolver_uses_existing_behavior(monkeypatch):
    monkeypatch.setenv("ARIA_INTENT_RESOLVER", "0")
    call = Mock()
    resolver.resolve("do the same for Infosys", HISTORY, caller=call)
    call.assert_not_called()


def test_input_context_is_bounded_and_sources_are_request_local():
    data = resolver._evidence("review that", [{"message_id": i, "query": "q" * 2000,
                                               "response": {"response": "a" * 5000}} for i in range(100)])
    assert len(data["recent_turns"]) <= 4 and len(json.dumps(data).encode()) < 13000
    assert {t["id"] for t in data["recent_turns"]} <= {"96", "97", "98", "99"}


@pytest.mark.parametrize("intent,standalone", [
    ("equity_research", "Research report on Infosys"), ("market", "How is Nifty doing today?"),
    ("tutor", "Explain compound interest"), ("general", "Explain rainbows"),
    ("finance", "Can I afford a car of 10 lakh?"),
])
def test_interpretation_dispatches_to_existing_workflow_and_preserves_original(intent, standalone, monkeypatch):
    from ai.llm import groq_client
    session.execute_turn("chat", "Research TCS and a car costing 10 lakh", lambda: {"response": "Earlier research."})
    source = str(session.get_session("chat")["history"][-1]["message_id"])
    session.get_session("chat")["adapt_tone"] = False
    monkeypatch.setattr(groq_client, "generate_structured", lambda *a, **kw: prediction(intent, standalone, source_turn_ids=[source]))
    calls = []
    def stub(route):
        return lambda q, **kw: calls.append((route, q, kw)) or {"domain": route, "response": "done"}
    for name, route in (("equity_research_pipeline", "equity_research"), ("market_pipeline", "market"),
                        ("finance_pipeline", "finance"), ("tutor_pipeline", "tutor"), ("_general_reply", "general")):
        monkeypatch.setattr(orchestrator, name, stub(route))
    raw = "do the same for Infosys"
    result = orchestrator.handle_query(raw, "chat", correct=False)
    assert calls[0][0] == intent and result["query"] == raw
    if intent == "finance":
        assert calls[0][1] == raw and calls[0][2]["intent_query"] == standalone
    else:
        assert calls[0][1] == standalone
    assert result["intent_resolution"]["status"] == "resolved"
    assert session.get_session("chat")["history"][-1]["query"] == raw
    assert resolver.current_interpretation.get() is None


def test_interpreted_finance_never_extracts_profile_facts_from_model_text(monkeypatch):
    from modules.finance import pipeline
    seen = []
    monkeypatch.setattr(pipeline, "_remember", lambda q, *a: seen.append(q) or [])
    monkeypatch.setattr(pipeline, "_run_tool", lambda *a, **kw: {"domain": "finance", "response": "done"})
    pipeline.run_pipeline("would that work for me?", user_id="chat", intent_query="Can I afford a car of 10 lakh?")
    assert seen == ["would that work for me?"]
    assert user_store.get_financial_profile("intent-user") is None


def test_interpreted_calculation_resumes_after_real_missing_input(mock_llm):
    from modules.finance import pipeline
    user_store.save_financial_profile("intent-user", expenses={"other": 10000}, loans=[], assets={"cash": 500000})
    first = pipeline.run_pipeline("Would that fit my budget?", user_id="chat", intent_query="Can I afford a car of 10 lakh?")
    assert first["missing_field"] == "monthly_income"
    pending = session.get_session("chat")["finance_pending"]
    assert pending["query"] == "Would that fit my budget?" and "10 lakh" in pending["intent_query"]
    result = pipeline.run_pipeline("50000", user_id="chat")
    assert result["intent"] == "afford" and result["engine"]["numbers"]["price"] == 1000000
    assert user_store.get_financial_profile("intent-user")["monthly_income"] == 50000


def test_resolver_cannot_change_explicit_company():
    answer, diagnostic = resolver.resolve("do the same for Infosys", HISTORY,
                                          caller=lambda *a, **kw: prediction(query="Research report on TCS"))
    assert answer is None and diagnostic["status"] == "invalid"


def test_resolver_cannot_change_lakh_to_crore():
    history = [{"message_id": 7, "query": "A car of 10 lakh", "response": {"response": "We can calculate affordability."}}]
    answer, diagnostic = resolver.resolve("do the same for my car", history,
        caller=lambda *a, **kw: prediction("finance", "Can I afford a car of 10 crore?"))
    assert answer is None and diagnostic["status"] == "invalid"


def test_transport_uses_same_model_strict_schema_no_retries_and_no_text_cleanup(monkeypatch):
    from ai.llm import groq_client
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(prediction())))], usage=None)
    monkeypatch.setattr(groq_client, "_make_groq_client", lambda: client)
    monkeypatch.setattr(groq_client, "MODEL_NAME", "openai/gpt-oss-120b")
    assert groq_client.generate_structured("input", system_prompt="JSON", schema=resolver._schema())["intent"] == "equity_research"
    client.with_options.assert_called_once_with(timeout=8.0, max_retries=0)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == groq_client.MODEL_NAME and kwargs["temperature"] == 0
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["max_completion_tokens"] == 1024


def test_transport_failure_does_not_retry_or_expose_request(monkeypatch):
    from ai.llm import groq_client
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = RuntimeError("secret value")
    monkeypatch.setattr(groq_client, "_make_groq_client", lambda: client)
    assert groq_client.generate_structured("input", system_prompt="JSON", schema=resolver._schema()) is None
    assert client.chat.completions.create.call_count == 1


def test_other_configured_model_uses_json_mode_with_local_schema_validation(monkeypatch):
    from ai.llm import groq_client
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(prediction())))], usage=None)
    monkeypatch.setattr(groq_client, "_make_groq_client", lambda: client)
    monkeypatch.setattr(groq_client, "MODEL_NAME", "custom-configured-model")
    assert groq_client.generate_structured("input", system_prompt="JSON", schema=resolver._schema())
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "custom-configured-model"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "standalone_query" in kwargs["messages"][0]["content"]
