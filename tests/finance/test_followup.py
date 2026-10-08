"""Intent tools: one templated question when a needed fact is missing, a bare reply fills it, the original
question is then answered. LLM is mocked; no microphone."""
import time

import pytest

from core.orchestrator import handle_query
from core.session import clear_session
from modules.finance import pipeline
from shared import user_store

U = "__pytest_followup__"


@pytest.fixture(autouse=True)
def clean():
    for fn in (user_store.delete_financial_profile, user_store.clear_transactions, clear_session):
        fn(U)
    yield
    for fn in (user_store.delete_financial_profile, user_store.clear_transactions, clear_session):
        fn(U)


def test_missing_income_asks_one_question_without_llm(mock_llm):
    out = pipeline.run_pipeline("Can I afford a car of 10 lakh", user_id=U)
    assert out["missing_field"] == "monthly_income" and out["ui_action"] == "open_profile"
    assert "income" in out["response"].lower() and mock_llm.calls == []


def test_bare_reply_fills_the_fact_and_answers_the_original_question(mock_llm):
    user_store.save_financial_profile(U, expenses={"other": 30000}, loans=[], assets={"cash": 500000})
    first = handle_query("Can I afford a car of 10 lakh", session_id=U)
    assert first["missing_field"] == "monthly_income"
    out = handle_query("about 1.5L", session_id=U)
    assert out["intent"] == "afford" and out["engine"]["numbers"]["price"] == 1_000_000
    assert user_store.get_financial_profile(U)["monthly_income"] == 150000
    assert out["profile_basis"].startswith("Based on your profile:") and "% complete" in out["profile_basis"]


def test_llm_outage_gives_a_template_answer_not_an_error(mock_llm):
    mock_llm.set_response("Error: all backends failed")
    user_store.save_financial_profile(U, monthly_income=150000, expenses={"other": 30000}, loans=[], assets={"cash": 500000})
    out = pipeline.run_pipeline("Can I afford a car of 10 lakh", user_id=U)
    assert not out["response"].startswith("Error") and "Verdict" in out["response"]


def test_mocked_intent_call_is_fast(mock_llm):
    user_store.save_financial_profile(U, monthly_income=150000, expenses={"other": 30000}, loans=[], assets={"cash": 500000})
    start = time.perf_counter()
    pipeline.run_pipeline("Can I afford a car of 10 lakh", user_id=U)
    assert time.perf_counter() - start < 0.3


def test_goal_without_goals_points_to_the_profile(mock_llm):
    out = pipeline.run_pipeline("how is my goal progress", user_id=U)
    assert out["missing_field"] == "goals" and out["ui_action"] == "open_profile"


def test_question_after_a_missing_field_ask_is_not_taken_as_the_answer(mock_llm):
    pipeline.run_pipeline("Can I afford a car of 10 lakh", user_id=U)
    pipeline.run_pipeline("Can I start a 20k SIP?", user_id=U)
    assert (user_store.get_financial_profile(U) or {}).get("monthly_income") is None


@pytest.mark.parametrize("reply", ["about 40k", "1.5 lakh per month", "40000", "around 1.2L"])
def test_bare_amounts_are_accepted(mock_llm, reply):
    pipeline.run_pipeline("Can I afford a car of 10 lakh", user_id=U)
    pipeline.run_pipeline(reply, user_id=U)
    assert user_store.get_financial_profile(U)["monthly_income"] > 0


def test_unanswered_question_expires_after_one_turn(mock_llm):
    handle_query("Can I afford a car of 10 lakh", session_id=U)
    handle_query("explain what a mutual fund is", session_id=U)
    from core.session import get_session
    assert "finance_pending" not in get_session(U)


def test_whatif_asks_for_the_named_category_and_mentions_what_is_known(mock_llm):
    user_store.save_financial_profile(U, monthly_income=120000, expenses={"rent": 25000})
    out = pipeline.run_pipeline("What if I reduce food spending by 5000 per month?", user_id=U)
    assert out["missing_field"] == "expenses.food" and "spend on food" in out["response"] and "income" in out["response"]
    done = pipeline.run_pipeline("about 15k", user_id=U)
    assert done["intent"] == "what_if" and user_store.get_financial_profile(U)["expenses"]["food"] == 15000


def test_fact_statements_route_to_finance_and_get_an_acknowledgement(mock_llm):
    import json
    mock_llm.set_response(json.dumps({"facts": [{"field": "age", "value": 28}, {"field": "monthly_income", "value": 120000}, {"field": "expenses.rent", "value": 25000}]}))
    out = handle_query("I am 28, I earn 1.2 lakh a month and my rent is 25000", session_id=U)
    assert out["domain"] == "finance" and out["response"].startswith("Noted:") and "risk" not in out
    p = user_store.get_financial_profile(U)
    assert p["age"] == 28 and p["monthly_income"] == 120000 and p["expenses"]["rent"] == 25000


def test_rent_only_does_not_count_as_known_spending():
    from modules.finance import pipeline
    assert not pipeline._known({"expenses": {"rent": 25000}}, "expenses")
    assert pipeline._known({"expenses": {"rent": 25000, "other": 40000}}, "expenses")


def test_answer_to_a_next_question_after_stated_facts_is_taken_and_noted(monkeypatch):
    from modules.finance import pipeline
    sid, uid = "sess-next", "owner-next"
    monkeypatch.setattr(pipeline.user_store, "current_owner", type("C", (), {"get": staticmethod(lambda: uid)}))
    pipeline.user_store.delete_financial_profile(uid)
    r = pipeline.run_pipeline("I earn 1.5 lakh a month and my rent is 30000 and I am 30", user_id=sid)
    assert "Next:" in r["response"] and pipeline.get_session(sid).get("finance_pending")
    r2 = pipeline.run_pipeline("about 70k", user_id=sid)
    assert r2["domain"] == "finance" and r2["response"].startswith("Noted")
    assert pipeline.engine.total_expenses(pipeline.user_store.get_financial_profile(uid)) is not None


@pytest.mark.parametrize("q,amount", [("should I start a SIP of 15k", 15000), ("can I start a 10000 monthly sip", 10000),
                                      ("I want to invest 5000 a month in sip", 5000), ("I want to start sip 5k", 5000)])
def test_sip_amount_only_comes_from_sip_words(q, amount):
    assert pipeline.finance_intent(q) == ("afford_sip", {"amount": amount})


def test_income_is_never_taken_as_the_sip_amount(mock_llm):
    q = "I earn 95000 a month, pay 8500 EMI, should I start a SIP?"
    assert pipeline.finance_intent(q) == ("sip_capacity", {})
    out = pipeline.run_pipeline(q, user_id=U)
    assert out["missing_field"] == "expenses" and "₹95k" in out["response"] and "₹8.5k" in out["response"]
    done = pipeline.run_pipeline("about 50k", user_id=U)
    assert done["intent"] == "sip_capacity" and done["engine"]["surplus"] == 36500


def test_stated_figures_override_saved_ones_for_this_answer(mock_llm):
    user_store.save_financial_profile(U, monthly_income=200000, existing_emi=8000, expenses={"rent": 40000, "food": 20000, "other": 30000})
    out = pipeline.run_pipeline("I earn 95000 a month, pay 8500 EMI, should I start a SIP?", user_id=U)
    assert out["missing_field"] == "expenses" and "Using the" in out["response"] and "saved" in out["response"] and "₹90k" in out["response"]
    assert user_store.get_financial_profile(U)["monthly_income"] == 200000  # not overwritten without a yes
    done = pipeline.run_pipeline("about 50k", user_id=U)
    assert done["engine"]["surplus"] == 36500 and "Using the" in done["response"]
    assert user_store.get_financial_profile(U)["expenses"] == {"other": 50000}


def test_bare_answer_is_not_read_as_a_mood_check_in(mock_llm):
    user_store.save_financial_profile(U, expenses={"other": 30000}, loans=[], assets={"cash": 500000})
    handle_query("Can I afford a car of 10 lakh", session_id=U)
    out = handle_query("about 1.5L", session_id=U)
    assert out["domain"] == "finance" and out["intent"] == "afford"
