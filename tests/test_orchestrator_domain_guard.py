"""Category routing must provide useful help without premature scope refusals.
Classification and financial safeguards remain available. Model calls are mocked.
"""
import json

import pytest

from core.orchestrator import handle_query
from core.session import clear_session
from shared.vector_store import index_exists

# The "confidently allowed" and "ambiguous bridge" tests route through
# Module 2's tutor pipeline (no finance/market keyword match), which needs
# the concept index for its retrieval step.
pytestmark = pytest.mark.skipif(
    not index_exists("concepts"),
    reason="Concept index not built; run python -m scripts.build_concept_kb",
)


def _classifier_json(**fields):
    payload = {"domain": "non_finance", "intent": "trivia", "allowed": False, "confidence": 0.95}
    payload.update(fields)
    return json.dumps(payload)


def test_confidently_non_finance_query_receives_capability_aware_help(mock_llm):
    session_id = "__pytest_guard_refuse__"
    clear_session(session_id)
    mock_llm.set_response(_classifier_json(domain="non_finance", allowed=False, confidence=0.97))
    try:
        response = handle_query("who won yesterday's cricket match", session_id=session_id)
        assert response["domain"] == "refused"  # ARIA covers finance only: a confident "not finance" gets the polite refusal
        assert "finance" in response["response"].lower()
        assert "Insight:" not in response["response"]
    finally:
        clear_session(session_id)


def test_low_confidence_non_finance_bridges_instead_of_refusing(mock_llm):
    session_id = "__pytest_guard_bridge__"
    clear_session(session_id)
    mock_llm.set_response(_classifier_json(domain="non_finance", allowed=False, confidence=0.4))
    try:
        response = handle_query("what is the capital of France", session_id=session_id)
        # Ambiguous (confidence below threshold) -- not refused, falls
        # through to the general tutor fallback instead.
        assert response["domain"] != "refused"
    finally:
        clear_session(session_id)


def test_finance_keyword_query_is_unaffected_by_guard(mock_llm):
    session_id = "__pytest_guard_finance_keyword__"
    clear_session(session_id)
    mock_llm.set_response(
        "Insight: mock.\nAnalysis: mock.\nRecommendation: mock.\nRisk: mock."
    )
    try:
        response = handle_query("what is my risk profile", session_id=session_id)
        # Precise keyword routing (domain == "finance") short-circuits
        # before the guard's else-branch is ever reached.
        assert response["domain"] != "refused"
    finally:
        clear_session(session_id)


def test_guard_unavailable_falls_back_to_prior_behavior(mock_llm):
    """Default mock response is plain text, not classifier JSON -- classify_domain
    returns available=False, and routing must be exactly what it was before
    the domain guard existed (never refuses)."""
    session_id = "__pytest_guard_unavailable__"
    clear_session(session_id)
    try:
        response = handle_query("write me a poem", session_id=session_id)
        assert response["domain"] != "refused"
    finally:
        clear_session(session_id)


def test_smalltalk_bypasses_the_guard_entirely(mock_llm):
    session_id = "__pytest_guard_smalltalk__"
    clear_session(session_id)
    mock_llm.set_response("Hey there!")
    try:
        response = handle_query("hey", session_id=session_id)
        assert response["domain"] == "smalltalk"
        # Only one LLM call (the smalltalk reply itself) -- the guard never
        # ran for this turn.
        assert len(mock_llm.calls) == 1
    finally:
        clear_session(session_id)


def test_a_short_off_topic_message_in_a_running_chat_is_still_checked_with_the_earlier_question(monkeypatch):
    """The scope check used to be skipped for any message of six words or fewer once a chat had history, so "who is virat kohli"
    and "in field of cricket" were answered. The classifier is now shown the earlier question and decides."""
    from core import orchestrator
    from shared import domain_guard

    session_id = "__pytest_guard_short__"
    clear_session(session_id)
    seen = []

    def classify(query, previous=None):
        seen.append((query, previous))
        return {"domain": "non_finance", "intent": "people", "allowed": False, "confidence": 0.95, "available": True}

    monkeypatch.setattr(domain_guard, "classify_domain", classify)
    monkeypatch.setattr(orchestrator, "get_session", lambda sid="default": {"history": [{"query": "What is a SIP?", "response": {"domain": "tutor"}}]})
    monkeypatch.setattr(orchestrator, "save_turn", lambda *a, **k: None)
    try:
        response = orchestrator._scope_refusal("who is virat kohli", "who is virat kohli", session_id)
        assert response and response["domain"] == "refused"
        assert seen == [("who is virat kohli", "What is a SIP?")]  # short message: the earlier question travels with it
    finally:
        clear_session(session_id)


def test_a_follow_up_the_classifier_allows_is_not_refused(monkeypatch):
    from core import orchestrator
    from shared import domain_guard

    monkeypatch.setattr(domain_guard, "classify_domain", lambda query, previous=None: {"domain": "finance", "intent": "follow_up", "allowed": True, "confidence": 0.9, "available": True})
    monkeypatch.setattr(orchestrator, "get_session", lambda sid="default": {"history": [{"query": "What is a SIP?", "response": {"domain": "tutor"}}]})
    assert orchestrator._scope_refusal("and for 10 years", "and for 10 years", "__pytest_guard_follow__") is None
