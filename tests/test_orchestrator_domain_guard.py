"""core/orchestrator.py's domain-guard wiring -- the confident-refusal
short-circuit and the fail-open/ambiguous-bridge behavior. LLM mocked
throughout; see shared/domain_guard.py for the classifier itself."""
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


def test_confidently_non_finance_query_is_refused_before_any_pipeline_runs(mock_llm):
    session_id = "__pytest_guard_refuse__"
    clear_session(session_id)
    mock_llm.set_response(_classifier_json(domain="non_finance", allowed=False, confidence=0.97))
    try:
        response = handle_query("who won yesterday's cricket match", session_id=session_id)
        assert response["domain"] == "refused"
        assert "financial intelligence assistant" in response["response"]
        # Only the classifier call happened -- the main narration pipeline
        # (which would have produced an "Insight:"-formatted answer) never ran.
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
