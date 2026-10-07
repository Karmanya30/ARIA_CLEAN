"""/api/profile: partial updates, null deletes, delete-my-data, per-owner isolation, no stored defaults."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules.finance.pipeline import _try_build_financial_profile
from shared import user_store

client = TestClient(app)
A, B = "__pytest_profile_a__", "__pytest_profile_b__"


@pytest.fixture(autouse=True)
def clean():
    for u in (A, B):
        client.delete(f"/api/profile?session_id={u}")
    yield
    for u in (A, B):
        client.delete(f"/api/profile?session_id={u}")


def post(owner, **fields):
    return client.post("/api/profile", json={"session_id": owner, **fields})


def get(owner):
    return client.get(f"/api/profile?session_id={owner}").json()


def test_partial_updates_merge_and_record_sources():
    post(A, age=30, expenses={"food": 5000})
    body = post(A, expenses={"rent": 20000}).json()
    assert body["profile"]["age"] == 30 and body["profile"]["expenses"] == {"food": 5000, "rent": 20000}
    assert body["sources"]["age"]["src"] == "form" and body["sources"]["age"]["at"]
    assert "age" not in body["completeness"]["missing"] and body["completeness"]["pct"] > 0


def test_null_deletes_one_fact_only():
    post(A, age=30, monthly_income=50000, expenses={"food": 5000, "rent": 20000})
    body = post(A, age=None, expenses={"food": None}).json()
    assert body["profile"]["age"] is None and "age" not in body["sources"]
    assert body["profile"]["monthly_income"] == 50000 and body["profile"]["expenses"] == {"rent": 20000}


def test_no_defaults_are_stored():
    _try_build_financial_profile("I earn 50000 a month", A)
    p = get(A)["profile"]
    assert p["monthly_income"] == 50000
    assert p["age"] is None and p["dependents"] is None and p["tax_regime"] is None and p["city_tier"] is None
    assert {"age", "dependents"} <= set(get(A)["completeness"]["missing"])


def test_owners_are_isolated_and_delete_removes_everything():
    post(A, monthly_income=50000)
    client.post("/api/transactions", json={"session_id": A, "date": "2026-07-01", "category": "food", "amount": 100})
    assert get(B)["profile"]["monthly_income"] is None
    assert client.delete(f"/api/profile?session_id={A}").json() == {"deleted": True}
    assert get(A)["profile"]["monthly_income"] is None and user_store.get_transactions(A) == []


def test_invalid_values_are_rejected():
    assert post(A, age=10).status_code == 422
    assert post(A, risk_tolerance="Reckless").status_code == 422


def test_summary_shape():
    post(A, monthly_income=100000, expenses={"food": 20000, "rent": 30000, "other": 0}, loans=[], assets={"cash": 300000},
         goals=[{"name": "Car", "target": 800000, "years": 4}], age=30, risk_tolerance="Moderate")
    s = client.get(f"/api/profile/summary?session_id={A}").json()
    assert set(s) == {"snapshot", "health", "goals", "retirement", "tax"}
    assert s["snapshot"]["monthly_surplus"] == 50000 and 0 <= s["health"]["score"] <= 100
    assert s["goals"][0]["on_track"] is True and s["retirement"]["corpus"] > 0 and s["tax"]["better"] in ("old", "new")
    empty = client.get(f"/api/profile/summary?session_id={B}").json()
    assert empty["retirement"] is None and empty["tax"] is None and empty["goals"] == []
