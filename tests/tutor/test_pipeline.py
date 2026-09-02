"""modules/tutor/pipeline.py's off-topic gate -- found live via "what is
SHM" getting a full physics explanation through the generic tutor
fallback, which had no topic restriction at all. See run_pipeline's
off-topic branch for why this is an LLM yes/no gate rather than an
embedding-similarity threshold against the concept KB."""
from modules.tutor.pipeline import _is_finance_related, run_pipeline


def test_is_finance_related_true_on_yes(mock_llm):
    mock_llm.set_response("YES")
    assert _is_finance_related("what is a REIT") is True


def test_is_finance_related_false_on_no(mock_llm):
    mock_llm.set_response("NO")
    assert _is_finance_related("what is simple harmonic motion") is False


def test_is_finance_related_fails_open_on_backend_error(mock_llm):
    # A total backend outage shouldn't block a real finance question --
    # the follow-up generate_response call would hit the same failure and
    # surface it through the normal "Error:" response path anyway.
    mock_llm.set_response("Error: both backends failed")
    assert _is_finance_related("what is a REIT") is True


def test_off_topic_query_gets_refused_not_a_lecture(mock_llm):
    mock_llm.set_response("NO")
    result = run_pipeline("what is simple harmonic motion")
    assert result["domain"] == "off_topic"
    assert "outside" in result["response"].lower()
    assert "Insight:" not in result["response"]


def test_finance_adjacent_query_outside_kb_still_answered(mock_llm):
    # "REIT" isn't one of the 50 concepts in the KB, so this exercises the
    # generic-fallback path, not a confident concept match.
    mock_llm.set_response("YES")
    result = run_pipeline("what is a REIT")
    assert result["domain"] == "tutor"
