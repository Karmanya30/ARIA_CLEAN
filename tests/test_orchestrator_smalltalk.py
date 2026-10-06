"""core/orchestrator.py's smalltalk short-circuit -- found live via Tavus
CVI Mode: greeting ARIA with "hey" was routed through
modules/tutor/pipeline.py's generic fallback, whose prompt unconditionally
instructs the LLM to explain the query as a financial concept in a rigid
Insight/Analysis/Recommendation/Risk format. Spoken aloud in a real voice
call, "hey" got answered with a structured lecture on what the word "hey"
means -- the opposite of sounding like a person talking."""
from core.orchestrator import _is_smalltalk, handle_query
from core.session import clear_session


def test_greetings_are_detected_as_smalltalk():
    for text in ["hey", "Hey!", "hi", "hello there".split()[0], "thanks", "bye", "how are you"]:
        assert _is_smalltalk(text) is True


def test_real_questions_are_not_smalltalk():
    for text in [
        "hey what is my risk profile",
        "hi, how did the Nifty do this week",
        "what is compound interest",
    ]:
        assert _is_smalltalk(text) is False


def test_greeting_gets_a_natural_reply_not_a_forced_taxal_lecture(mock_llm):
    session_id = "__pytest_smalltalk__"
    clear_session(session_id)
    mock_llm.set_response("Hey there! What can I help you with today?")
    try:
        response = handle_query("hey", session_id=session_id)

        assert response["domain"] == "smalltalk"
        assert response["response"] == "Hey there! What can I help you with today?"
        # The LLM was called with the plain greeting, not wrapped in
        # tutor_prompt's "explain this concept" instructions.
        assert mock_llm.calls[-1] == "hey"
        assert "Insight:" not in mock_llm.calls[-1]
    finally:
        clear_session(session_id)


def test_real_tutor_question_still_gets_routed_normally(mock_llm):
    session_id = "__pytest_smalltalk_control__"
    clear_session(session_id)
    try:
        response = handle_query("what is diversification", session_id=session_id)
        assert response["domain"] != "smalltalk"
    finally:
        clear_session(session_id)


def test_a_greeting_with_a_vocative_is_still_small_talk():
    from core.orchestrator import is_smalltalk

    for q in ["Hi there", "hello aria!", "Hey everyone", "thanks again", "good morning team", "Hi"]:
        assert is_smalltalk(q), q
    for q in ["hi, what is a SIP?", "hello what should I invest in", "thanks for the SIP advice, what about tax"]:
        assert not is_smalltalk(q), q
