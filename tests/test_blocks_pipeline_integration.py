"""Confirms every pipeline's response dict carries a `blocks` list (Stage
13's contract) -- not a flag-day break: `response["response"]` (the plain
string) is still present everywhere too, this only adds the new key
alongside it. See tests/test_blocks.py for the block schema itself."""
from core.orchestrator import _smalltalk_reply
from core.session import clear_session
from modules.finance.pipeline import run_pipeline as finance_run_pipeline
from modules.tutor.pipeline import run_pipeline as tutor_run_pipeline
from shared import user_store

_TEST_USER = "__pytest_blocks_integration__"


def _cleanup():
    user_store.clear_transactions(_TEST_USER)
    user_store.delete_financial_profile(_TEST_USER)


def test_smalltalk_reply_has_a_text_block(mock_llm):
    result = _smalltalk_reply("hey")
    assert result["blocks"] == [{"type": "text", "content": result["response"]}]


def test_finance_structured_path_has_metric_risk_breakdown_blocks(mock_llm):
    _cleanup()
    try:
        result = finance_run_pipeline("I earn 60000 a month, I'm 28, what is my risk profile", user_id=_TEST_USER)
    finally:
        _cleanup()

    block_types = [b["type"] for b in result["blocks"]]
    assert "text" in block_types
    assert "metric" in block_types
    assert "risk" in block_types
    assert "breakdown" in block_types


def test_finance_income_clarification_has_a_text_block(mock_llm):
    _cleanup()
    try:
        result = finance_run_pipeline("what is my risk profile", user_id=_TEST_USER)
    finally:
        _cleanup()

    assert result["blocks"] == [{"type": "text", "content": result["response"]}]


def test_tutor_generic_fallback_has_a_text_block(mock_llm):
    result = tutor_run_pipeline("some obscure query with no kb match")
    assert result["blocks"][0]["type"] == "text"


def test_error_response_becomes_an_alert_block_not_a_text_block(mock_llm):
    mock_llm.set_response("Error: both backends failed")
    result = tutor_run_pipeline("some obscure query with no kb match")
    assert result["blocks"] == [
        {
            "type": "alert",
            "severity": "error",
            "message": "ARIA's language model is temporarily unavailable (both Groq and Gemini failed to respond).",
        }
    ]
