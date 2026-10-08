"""Spending analysis: pure insights/spent, GET /api/transactions/insights and the chat intents. LLM mocked; no mic."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.orchestrator import handle_query
from core.session import clear_session
from modules.finance import pipeline, spending
from shared import user_store

U = "__pytest_spending__"


def _t(date, category, amount, merchant):
    return {"date": date, "category": category, "amount": amount, "merchant": merchant, "channel": "statement"}


def _data():
    rows = []
    for m in ("2026-06", "2026-07", "2026-08"):
        rows += [_t(f"{m}-01", "housing", 30000, "Landlord Rent"), _t(f"{m}-04", "emi", 15000, "Hdfc Emi"),
                 _t(f"{m}-06", "entertainment", 649, "Netflix"), _t(f"{m}-08", "utilities", 1300, "Bescom"),
                 _t(f"{m}-12", "food", 1500, "Swiggy"), _t(f"{m}-20", "food", 1800 if m != "2026-08" else 20000, "Swiggy")]
    return rows


@pytest.fixture(autouse=True)
def clean():
    for fn in (user_store.delete_financial_profile, user_store.clear_transactions, clear_session):
        fn(U)
    yield
    for fn in (user_store.delete_financial_profile, user_store.clear_transactions, clear_session):
        fn(U)


def test_availability_threshold():
    out = spending.insights(_data()[:9], {"monthly_income": 100000})
    assert out["available"] is False and out["reason"] == "upload a statement or add more transactions"
    assert spending.insights(_data()[:10], None)["available"] is True


def test_savings_rate_with_and_without_income():
    on = spending.insights(_data(), {"monthly_income": 120000})
    cf = on["cashflow"]
    assert cf["emi_avg"] == 15000 and cf["income_avg"] == 120000
    assert cf["savings_rate"] == round((120000 - cf["spend_avg"] - 15000) / 120000 * 100, 1)
    assert cf["by_month"][0]["net"] == 120000 - cf["by_month"][0]["spend"] - 15000
    off = spending.insights(_data(), {})
    assert off["cashflow"]["savings_rate"] is None and off["cashflow"]["by_month"][0]["net"] is None
    assert off["categories"][0]["share_of_income"] is None and off["notes"]


def test_benchmarks_and_suggestions():
    out = spending.insights(_data(), {"monthly_income": 60000})
    food = next(c for c in out["categories"] if c["name"] == "food")
    assert food["over_benchmark"] is True and food["benchmark_pct"] == 15
    tip = next(s for s in out["suggestions"] if s["title"].startswith("Trim food"))
    assert tip["saving_per_month"] == round(food["monthly_avg"] - 0.15 * 60000)
    assert any(s["title"] == "EMIs are heavy" for s in out["suggestions"]) is False  # 25% of income
    assert out["suggestions"][0]["priority"] == "high"
    broke = spending.insights(_data(), {"monthly_income": 35000})
    assert {"EMIs are heavy", "You are overspending"} <= {s["title"] for s in broke["suggestions"]}


def test_recurring_detection():
    rec = {r["merchant"]: r for r in spending.insights(_data(), {})["recurring"]}
    assert rec["Netflix"]["months"] == 3 and rec["Netflix"]["amount"] == 649
    assert "Bescom" in rec and "Swiggy" not in rec  # two charges a month is shopping, not a bill


def test_unusual_detection():
    out = spending.insights(_data(), {})["unusual"]
    assert [(u["merchant"], u["amount"]) for u in out] == [("Swiggy", 20000)]
    assert "x your usual spend in this category" in out[0]["why"]


def test_period_filter():
    d = _data()
    assert spending.spent(d, "food", "2026-06") == 3300
    assert spending.spent(d, "food") == 3300 + 3300 + 21500
    assert spending.spent(d, month="2026-07") == 30000 + 15000 + 649 + 1300 + 3300
    assert spending.spent(d, merchant="netflix") == 649 * 3


def test_api_insights():
    c = TestClient(app)
    assert c.get("/api/transactions/insights", params={"session_id": U}).json()["available"] is False
    for t in _data():
        user_store.add_transaction(U, date=t["date"], category=t["category"], amount=t["amount"], merchant=t["merchant"], channel="statement")
    user_store.save_financial_profile(U, monthly_income=120000)
    out = c.get("/api/transactions/insights", params={"session_id": U}).json()
    assert out["available"] and out["period"]["months"] == 3 and out["cashflow"]["income_avg"] == 120000


def _load():
    for t in _data():
        user_store.add_transaction(U, date=t["date"], category=t["category"], amount=t["amount"], merchant=t["merchant"], channel="statement")
    user_store.save_financial_profile(U, monthly_income=60000)


def test_chat_without_transactions_points_to_upload(mock_llm):
    out = pipeline.run_pipeline("how much did I spend on food last month", user_id=U)
    assert out["missing_field"] == "transactions" and out["ui_action"] == "open_profile"
    assert out["response"].startswith("I don't have any transactions yet. Upload a bank statement") and mock_llm.calls == []


@pytest.mark.parametrize("q,intent", [
    ("how much did I spend on food last month", "spending_spent"),
    ("where can I cut my spending", "spending_cut"),
    ("what subscriptions do I have", "spending_recurring"),
    ("any unusual transactions", "spending_unusual"),
    ("analyse my spending", "spending_analyse"),
    ("what are my biggest expenses", "spending_top"),
    ("show my monthly spending trend", "spending_trend"),
])
def test_chat_intents_template_fallback(mock_llm, q, intent):
    _load()
    mock_llm.set_response("Error: all backends failed")
    out = pipeline.run_pipeline(q, user_id=U)
    assert out["intent"] == intent and out["engine"] and out["data_basis"] == "Based on your uploaded transactions (Jun-Aug 2026)"
    assert out["response"].startswith(("Insight:", "Upload", "Your")) or "Insight" in out["response"]


def test_chat_spent_numbers_and_llm_narration(mock_llm):
    _load()
    out = pipeline.run_pipeline("how much did I spend on food in June", user_id=U)
    assert out["engine"]["total"] == 3300 and out["engine"]["month"] == "2026-06" and "mock" in out["response"]
    assert pipeline.run_pipeline("how much did I spend on swiggy in total", user_id=U)["engine"]["total"] == 3300 + 3300 + 21500
    assert pipeline.run_pipeline("how much did I spend on food this month", user_id=U)["engine"]["total"] == 21500


def test_orchestrator_routing_and_concepts(mock_llm):
    _load()
    out = handle_query("where can I cut my spending", session_id=U)
    assert out.get("intent") == "spending_cut"
    assert pipeline.finance_intent("what is a budget") is None
    assert pipeline.finance_intent("what is a subscription") is None
    assert pipeline.finance_intent("what if I cut my food spending by 5000")[0] == "what_if"


def _month(m, other):
    return [_t(f"{m}-02", "housing", 30000, "Landlord Rent"), _t(f"{m}-04", "emi", 15000, "Hdfc Emi"),
            _t(f"{m}-10", "food", 2000, "Swiggy"), _t(f"{m}-11", "other", other, "Store")]


def test_luxury_watch_flagged_alone_with_high_priority_suggestion():
    rows = _month("2026-06", 300) + _month("2026-07", 1200) + _month("2026-08", 3500)
    rows += [_t("2026-08-25", "other", 48000, "Luxury Watch Store"), _t("2026-08-26", "other", 900, "Chemist")]
    out = spending.insights(rows, {"monthly_income": 120000})
    assert [(u["merchant"], u["amount"]) for u in out["unusual"]] == [("Luxury Watch Store", 48000)]
    tip = out["suggestions"][0]
    assert tip["title"] == "Verify the ₹48,000 charge at Luxury Watch Store on 25 Aug" and tip["priority"] == "high" and tip["saving_per_month"] is None


def test_normal_month_and_rent_never_flagged_and_single_month_ok():
    rows = _month("2026-06", 300) + _month("2026-07", 1200) + _month("2026-08", 3500) + [_t("2026-08-20", "housing", 90000, "Landlord Rent")]
    assert spending.insights(rows, {"monthly_income": 120000})["unusual"] == []
    one = _month("2026-06", 300) + _month("2026-06", 400) + _month("2026-06", 500)
    assert spending.insights(one, {})["available"] and spending.insights(one, {})["unusual"] == []


def test_stored_income_beats_profile_income_and_net_per_month():
    rows = _month("2026-06", 300) + _month("2026-07", 1200) + _month("2026-08", 3500)
    pay = [{"date": f"2026-0{m}-01", "category": "income", "amount": 100000.0, "merchant": "Acme Salary"} for m in (6, 7)]
    out = spending.insights(rows, {"monthly_income": 999}, pay)
    cf = out["cashflow"]
    assert cf["income_avg"] == round(200000 / 3, 2)  # two paycheques over three months
    assert cf["by_month"][0]["net"] == 100000 - 30000 - 2000 - 300 - 15000
    assert cf["by_month"][2]["net"] == round(200000 / 3 - 30000 - 2000 - 3500 - 15000, 2)  # no paycheque yet: average
    assert spending.insights(rows, {"monthly_income": 999}, [])["cashflow"]["income_avg"] == 999


def test_income_rows_are_invisible_to_expense_consumers():
    for t in _data():
        user_store.add_transaction(U, date=t["date"], category=t["category"], amount=t["amount"], merchant=t["merchant"])
    user_store.add_transaction(U, date="2026-06-01", category="income", amount=90000.0, merchant="Salary", kind="income")
    assert len(user_store.get_transactions(U)) == len(_data())
    assert [t["amount"] for t in user_store.get_transactions(U, kind="income")] == [90000.0]
