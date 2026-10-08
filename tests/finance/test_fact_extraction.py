"""Chat fact extraction: one LLM call -> validated facts; hallucinations dropped; conflicts need a 'yes'."""
import json

import pytest

from core.session import clear_session
from modules.finance import pipeline
from shared import user_store

U = "__pytest_fact_extraction__"


@pytest.fixture(autouse=True)
def clean():
    for fn in (user_store.delete_financial_profile, user_store.clear_transactions, clear_session):
        fn(U)
    yield
    for fn in (user_store.delete_financial_profile, user_store.clear_transactions, clear_session):
        fn(U)


def facts(*items):
    return json.dumps({"facts": [{"period": None, **i} for i in items]})


def test_stated_fact_is_saved_and_echoed(mock_llm):
    mock_llm.set_response(facts({"field": "monthly_income", "value": 120000, "period": "month"}, {"field": "city", "value": "Pune"}))
    notes = pipeline._remember("I live in Pune and my salary is 1.2L a month", U, U)
    saved = user_store.get_financial_profile(U)
    assert saved["monthly_income"] == 120000 and saved["city"] == "Pune"
    assert saved["sources"]["city"]["src"] == "chat" and set(saved["sources"]["city"]) == {"src", "at"}  # never the quote
    assert notes[0].startswith("Noted:") and "Profile" in notes[0]


def test_extraction_uses_the_small_groq_model(monkeypatch):
    from ai.llm.groq_client import FALLBACK_GROQ_MODEL

    seen = {}
    monkeypatch.setattr(pipeline, "generate_response", lambda prompt, system_prompt=None, model=None, groq_model=None: seen.update(g=groq_model) or "{}")
    pipeline._remember("my rent is 20k", U, U)
    assert seen["g"] == FALLBACK_GROQ_MODEL


def test_hallucinated_number_is_dropped(mock_llm):
    mock_llm.set_response(facts({"field": "assets.fd", "value": 500000}, {"field": "city", "value": "Pune"}))
    pipeline._remember("I live in Pune", U, U)
    saved = user_store.get_financial_profile(U)
    assert saved["city"] == "Pune" and "assets" not in saved


def test_annual_amount_is_stored_monthly(mock_llm):
    mock_llm.set_response(facts({"field": "monthly_income", "value": 1200000, "period": "year"}))
    pipeline._remember("my pay is 12 lakh a year", U, U)
    assert user_store.get_financial_profile(U)["monthly_income"] == 100000


def test_hypothetical_stores_nothing_and_skips_the_llm(mock_llm):
    mock_llm.set_response(facts({"field": "assets.fd", "value": 500000}))
    assert pipeline._remember("What if I put 5 lakh in an FD?", U, U) == []
    assert mock_llm.calls == [] and user_store.get_financial_profile(U) is None


def test_conflicting_value_asks_then_yes_commits(mock_llm):
    user_store.save_financial_profile(U, monthly_income=100000)
    mock_llm.set_response(facts({"field": "monthly_income", "value": 120000}))
    notes = pipeline._remember("my salary is now 1.2L", U, U)
    assert "Update monthly income from ₹1L to ₹1.2L?" in notes[0]
    assert user_store.get_financial_profile(U)["monthly_income"] == 100000
    out = pipeline.run_pipeline("yes", user_id=U)
    assert "Updated monthly income" in out["response"]
    assert user_store.get_financial_profile(U)["monthly_income"] == 120000


def test_malformed_json_falls_back_to_regex(mock_llm):
    mock_llm.set_response("sorry, here is some prose { not json")
    pipeline._remember("I earn 50000 a month and pay 8000 emi", U, U)
    saved = user_store.get_financial_profile(U)
    assert saved["monthly_income"] == 50000 and saved["existing_emi"] == 8000
