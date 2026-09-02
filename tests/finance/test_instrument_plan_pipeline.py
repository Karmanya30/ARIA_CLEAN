"""modules/finance/pipeline.py's Stage 12 wiring -- goal/horizon parsing,
the _wants_investment_plan gate (avoids a second LLM call unless actually
asked for), and that the instrument plan reaches the response."""
from shared import user_store
from modules.finance.pipeline import (
    _extract_goal,
    _extract_horizon_years,
    _wants_investment_plan,
    run_pipeline,
)

_TEST_USER = "__pytest_instrument_plan__"


def _cleanup():
    user_store.clear_transactions(_TEST_USER)
    user_store.delete_financial_profile(_TEST_USER)


def test_extract_horizon_years_common_phrasings():
    assert _extract_horizon_years("I want to invest in 20 years") == 20.0
    assert _extract_horizon_years("saving for retirement in 15 years") == 15.0
    assert _extract_horizon_years("I have a 5-year horizon") == 5.0
    assert _extract_horizon_years("what is SIP") is None


def test_extract_goal_common_phrasings():
    assert _extract_goal("saving for retirement") == "retirement"
    assert _extract_goal("I want to buy a house") == "house"
    assert _extract_goal("saving for my child's education") == "education"
    assert _extract_goal("planning my wedding expenses") == "wedding"
    assert _extract_goal("what is SIP") is None


def test_wants_investment_plan_detects_common_phrasings():
    for query in [
        "where should I invest",
        "how should I invest my savings",
        "I want to start investing, help me",
        "which instrument should I put my money in",
        "how much should I invest",
    ]:
        assert _wants_investment_plan(query) is True, query
    assert _wants_investment_plan("what is my risk profile") is False


def test_pipeline_calls_llm_for_investment_plan_narrative_when_asked(mock_llm):
    _cleanup()
    try:
        result = run_pipeline(
            "I earn 80000 a month, I'm 28, where should I invest for retirement in 20 years",
            user_id=_TEST_USER,
        )
    finally:
        _cleanup()

    assert result["domain"] == "finance"
    assert len(result["investment_plan"]) == 7
    assert "risk" in result and "sip_plan" in result
    # Two real LLM calls: the main M1_NARRATION and the instrument-plan
    # narrative -- confirms the gate actually fired the second call this
    # time (contrast with the "skips" test below).
    assert len(mock_llm.calls) == 2
    assert any("RANKED INSTRUMENT TYPES" in call for call in mock_llm.calls)


def test_pipeline_skips_the_extra_llm_call_when_not_asked(mock_llm):
    _cleanup()
    try:
        result = run_pipeline("I earn 80000 a month, what is my risk profile", user_id=_TEST_USER)
    finally:
        _cleanup()

    assert result["domain"] == "finance"
    # Only the M1_NARRATION call should have fired -- not a second one for
    # the instrument-plan narrative, since this query didn't ask for it.
    assert len(mock_llm.calls) == 1
    assert result["investment_plan"]  # still computed (cheap, no LLM) even though not narrated


def test_horizon_and_goal_persist_across_turns(mock_llm):
    _cleanup()
    try:
        run_pipeline("I earn 50000 a month, saving for retirement in 25 years", user_id=_TEST_USER)
        saved = user_store.get_financial_profile(_TEST_USER)
        assert saved["goal"] == "retirement"
        assert saved["horizon_years"] == 25.0

        # A follow-up turn with no goal/horizon restated should keep the
        # saved values, same "is not None, not truthy" pattern already
        # used for income/existing_emi.
        run_pipeline("what is my risk profile", user_id=_TEST_USER)
        still_saved = user_store.get_financial_profile(_TEST_USER)
        assert still_saved["goal"] == "retirement"
        assert still_saved["horizon_years"] == 25.0
    finally:
        _cleanup()
