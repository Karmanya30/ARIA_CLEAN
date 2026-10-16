"""Everyday conversational turns, synthetic history and temporary storage only."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import orchestrator, session
from shared import dialogue, user_store


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "dialogue.db").as_posix(), connect_args={"check_same_thread": False})
    user_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(user_store, "_SessionLocal", sessionmaker(bind=engine))
    token = user_store.current_owner.set("dialogue-user")
    session._SESSIONS.clear()
    yield
    session._SESSIONS.clear()
    user_store.current_owner.reset(token)
    engine.dispose()


def seed(query, answer):
    session.execute_turn("chat", query, lambda: {"domain": "general", "response": answer})


@pytest.mark.parametrize("text", ["ok", "OK!", "okay", "okk", "k", "kk", "got it", "cool", "I see",
                                  "hmm", "makes sense", "theek hai", "acha", "samajh gaya", "👍", "thanks"])
@pytest.mark.parametrize("adapt", [True, False])
def test_acknowledgements_are_brief_without_tools_or_model(text, adapt, mock_llm, monkeypatch):
    session.get_session("chat")["adapt_tone"] = adapt
    def unexpected(*args, **kwargs):
        pytest.fail("An acknowledgement must not start a financial or tutor workflow")
    monkeypatch.setattr(orchestrator, "finance_pipeline", unexpected)
    monkeypatch.setattr(orchestrator, "tutor_pipeline", unexpected)
    result = orchestrator.handle_query(text, "chat")
    assert result["domain"] == "smalltalk" and len(result["response"].split()) <= 6
    assert mock_llm.calls == []
    assert session.get_session("chat")["history"][-1]["query"] == text


@pytest.mark.parametrize("text", ["ok how does a SIP work", "yes but don't update it", "no I meant 60000",
                                  "why does inflation rise", "continue the TCS valuation", "what does ok mean"])
def test_matching_whole_replies_does_not_swallow_real_requests(text):
    assert dialogue.act(text) is None


@pytest.mark.parametrize("text", ["yes please", "continue", "tell me more", "why?", "explain simply",
                                  "I don't understand", "matlab", "no"])
def test_followup_reaches_model_with_latest_exchange(text, monkeypatch):
    from ai.llm import groq_client
    seed("How do rainbows form?", "Sunlight bends in water droplets. Would you like an example?")
    seen = []
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda p, s, m: seen.append((p, s)) or "Here is the explanation."),))
    result = orchestrator.handle_query(text, "chat", correct=False)
    assert result["domain"] == "general"
    assert "water droplets" in seen[0][0] and text in seen[0][0]
    assert "do not force" in seen[0][1].lower()


def test_ok_accepts_a_specific_conversational_offer(mock_llm):
    seed("Explain rainbows", "Would you like a simple example?")
    result = orchestrator.handle_query("ok", "chat")
    assert result["domain"] == "general" and mock_llm.calls


@pytest.mark.parametrize("text", ["yes", "continue", "why"])
def test_missing_reference_gets_one_focused_question(text, mock_llm):
    result = orchestrator.handle_query(text, "chat")
    assert result["response"].count("?") == 1 and mock_llm.calls == []


def test_ok_keeps_missing_financial_input_pending_without_inventing_values(mock_llm):
    first = orchestrator.handle_query("Can I afford a car of 10 lakh", "chat")
    assert first["missing_field"] == "monthly_income"
    result = orchestrator.handle_query("okay", "chat")
    assert "monthly income" in result["response"]
    assert session.get_session("chat")["finance_pending"]["field"] == "monthly_income"
    assert (user_store.get_financial_profile("dialogue-user") or {}).get("monthly_income") is None
    orchestrator.handle_query("50000", "chat")
    assert user_store.get_financial_profile("dialogue-user")["monthly_income"] == 50000


@pytest.mark.parametrize("text", ["yes", "okay", "haan", "please do"])
def test_specific_profile_confirmation_still_works(text, mock_llm):
    user_store.save_financial_profile("dialogue-user", monthly_income=50000)
    session.get_session("chat")["finance_pending"] = {"field": "monthly_income", "query": None,
                                                          "confirm": {"monthly_income": 60000}}
    orchestrator.handle_query(text, "chat")
    assert user_store.get_financial_profile("dialogue-user")["monthly_income"] == 60000


@pytest.mark.parametrize("text", ["yes but don't update it", "okay don't change it", "yes, only explain it"])
def test_affirmative_prefix_is_not_permission_to_change_profile(text):
    from modules.finance import pipeline
    user_store.save_financial_profile("dialogue-user", monthly_income=50000)
    pending = {"field": "monthly_income", "confirm": {"monthly_income": 60000}}
    assert pipeline._followup(text, "dialogue-user", "chat", pending) is None
    assert user_store.get_financial_profile("dialogue-user")["monthly_income"] == 50000


def test_declining_missing_input_stops_followup_without_clearing_history(mock_llm):
    orchestrator.handle_query("Can I afford a car of 10 lakh", "chat")
    result = orchestrator.handle_query("no thanks", "chat")
    assert result["domain"] == "smalltalk" and "finance_pending" not in session.get_session("chat")
    assert len(session.get_session("chat")["history"]) == 2


@pytest.mark.parametrize("text", ["book a taxi", "describe a spaceship", "analyze this poem", "share an example",
                                  "what a coincidence", "a firmament of stars", "how to write a newsletter"])
def test_unrelated_words_do_not_match_financial_substrings(text):
    from shared.intent_classifier import classify_intent
    assert classify_intent(text) == "general"


@pytest.mark.parametrize("text", ["my dividends", "my portfolios", "mutual funds", "SIPs", "equities", "my EMIs"])
def test_word_boundaries_preserve_valid_financial_plurals(text):
    from shared.intent_classifier import classify_intent
    assert classify_intent(text) == "finance"


def test_unmatched_educational_question_has_no_forced_finance_or_quiz(monkeypatch):
    from modules.tutor import pipeline
    from ai.llm import groq_client
    monkeypatch.setattr(pipeline.m2_orchestrator, "handle", lambda *a: None)
    seen = []
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda p,s,m: seen.append((p,s)) or "Plants use sunlight to make food."),))
    answer = pipeline.run_pipeline("Explain photosynthesis")
    assert answer["response"] == "Plants use sunlight to make food."
    assert "photosynthesis" in seen[0][0] and seen[0][1] == dialogue.CONVERSATION_SYSTEM


def test_crisis_safety_runs_before_short_reply_handling(mock_llm):
    result = orchestrator.handle_query("ok I want to end my life", "chat")
    assert result["domain"] == "care" and mock_llm.calls == []


@pytest.mark.parametrize("query", ["Write a Python function for compound interest", "Write a poem about the stock market",
                                   "Share an example email about a tax refund", "Translate mutual fund into Hindi",
                                   "Explain an index in Python"])
def test_general_task_is_not_hijacked_by_financial_words(query, mock_llm, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("An explicit writing/coding task must not launch financial tools")
    monkeypatch.setattr(orchestrator, "finance_pipeline", unexpected)
    monkeypatch.setattr(orchestrator, "market_pipeline", unexpected)
    monkeypatch.setattr(orchestrator, "equity_research_pipeline", unexpected)
    result = orchestrator.handle_query(query, "chat", correct=False)
    assert result["domain"] == "general" and result["response"]


def test_missing_tutor_index_still_gives_useful_answer(mock_llm, monkeypatch):
    from modules.tutor import pipeline
    def missing(*args):
        raise FileNotFoundError("concept index unavailable")
    monkeypatch.setattr(pipeline.m2_orchestrator, "handle", missing)
    assert pipeline.run_pipeline("What is photosynthesis?")["response"] == mock_llm.response


@pytest.mark.parametrize("text", ["A dollar is divided into 100 cents.", "```python\nprint('USD 5')\n```"])
def test_general_answers_preserve_currency_and_code(text, monkeypatch):
    from ai.llm import groq_client
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda *args: text),))
    assert groq_client.generate_response("Explain this", system_prompt=dialogue.CONVERSATION_SYSTEM) == text
