"""The deterministic income-clarification short-circuit in
modules/finance/pipeline.py -- fires only for personalization-signaling
queries with no income known yet, never for concept questions."""
from shared import user_store
from modules.finance.pipeline import _needs_income_clarification, run_pipeline

_TEST_USER = "__pytest_income_clarification__"


def _cleanup():
    user_store.clear_transactions(_TEST_USER)
    user_store.delete_financial_profile(_TEST_USER)


def test_signals_detected_case_insensitively():
    assert _needs_income_clarification("What is my Risk Profile?") is True
    assert _needs_income_clarification("Can I afford a new car") is True
    assert _needs_income_clarification("help me plan my budget") is True


def test_concept_question_does_not_signal():
    assert _needs_income_clarification("what is SIP") is False
    assert _needs_income_clarification("explain compound interest") is False


def test_pipeline_asks_for_income_before_computing_risk_profile(mock_llm):
    _cleanup()
    try:
        result = run_pipeline("what is my risk profile", user_id=_TEST_USER)
    finally:
        _cleanup()

    assert result["domain"] == "finance"
    assert "monthly income" in result["response"].lower()
    assert "risk" not in result  # no structured risk block -- never reached the real pipeline
    assert mock_llm.calls == []  # deterministic short-circuit, no LLM call spent


def test_pipeline_does_not_intercept_known_concept_queries(mock_llm):
    _cleanup()
    try:
        result = run_pipeline("what is SIP", user_id=_TEST_USER)
    finally:
        _cleanup()

    assert "Systematic Investment Plan" in result["response"]
