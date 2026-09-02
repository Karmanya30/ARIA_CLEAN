"""
Adversarial query corpus -- the point of these tests is that the pipeline
never crashes and always returns a well-formed response dict, not that
the content is perfect. LLM is mocked throughout.

Skipped end-to-end if the concept index isn't built, since several of
these route through Module 2 -- run python -m scripts.build_concept_kb
first (unit tests for pieces that don't need it, e.g. router logic, live
in tests/test_router.py and don't need this skip).
"""
import pytest

from core.orchestrator import handle_query
from shared.vector_store import index_exists

pytestmark = pytest.mark.skipif(
    not index_exists("concepts"),
    reason="Concept index not built; run python -m scripts.build_concept_kb",
)


def _assert_well_formed(result: dict) -> None:
    assert isinstance(result, dict)
    assert "response" in result
    assert isinstance(result["response"], str)


def test_empty_input_does_not_crash(mock_llm):
    _assert_well_formed(handle_query("", session_id="adv_empty"))


def test_very_long_input_does_not_crash(mock_llm):
    long_query = "what is compound interest? " * 200  # ~2000+ chars
    _assert_well_formed(handle_query(long_query, session_id="adv_long"))


def test_off_topic_query_does_not_crash(mock_llm):
    result = handle_query("what's the weather in Chennai?", session_id="adv_offtopic")
    _assert_well_formed(result)


def test_off_topic_query_gets_refused_end_to_end(mock_llm):
    # Same query as above, but with the finance-relatedness classifier
    # explicitly saying "no" -- confirms handle_query's "general" bucket
    # (core/orchestrator.py) surfaces tutor_pipeline's off_topic domain
    # instead of overwriting it back to "general".
    mock_llm.set_response("NO")
    result = handle_query("what's the weather in Chennai?", session_id="adv_offtopic_refused")
    _assert_well_formed(result)
    assert result["domain"] == "off_topic"


def test_ambiguous_query_does_not_crash(mock_llm):
    _assert_well_formed(handle_query("tell me about it", session_id="adv_ambiguous"))


def test_concept_not_in_kb_does_not_crash(mock_llm):
    result = handle_query("what is a CDO?", session_id="adv_unknown_concept")
    _assert_well_formed(result)


def test_zero_income_does_not_crash(mock_llm):
    result = handle_query(
        "I earn 0 a month, what is my risk profile", session_id="adv_zero_income"
    )
    _assert_well_formed(result)


def test_multiple_intents_in_one_query_does_not_crash(mock_llm):
    result = handle_query(
        "what is SIP and also how did the Nifty do this week", session_id="adv_multi_intent"
    )
    _assert_well_formed(result)


def test_misspelled_concept_still_resolves(mock_llm):
    result = handle_query("compoundd innterest explain", session_id="adv_misspelled")
    _assert_well_formed(result)
