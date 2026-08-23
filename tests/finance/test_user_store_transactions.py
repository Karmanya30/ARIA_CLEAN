"""shared/user_store.py's transaction CRUD and risk_top_features round-trip
-- both added to close the "real trained model, empty input" gap documented
in the architecture audit. Uses a uniquely-prefixed user_id and cleans up
after itself since user_store writes to the real SQLite file, not an
in-memory test DB."""
import pytest

from shared import user_store

_TEST_USER = "__pytest_user_store_transactions__"


@pytest.fixture(autouse=True)
def _cleanup():
    user_store.clear_transactions(_TEST_USER)
    user_store.delete_financial_profile(_TEST_USER)
    yield
    user_store.clear_transactions(_TEST_USER)
    user_store.delete_financial_profile(_TEST_USER)


def test_add_and_get_transactions_round_trip():
    user_store.add_transaction(
        _TEST_USER, date="2026-07-01", category="food", amount=500.0,
        merchant="Zomato", channel="upi",
    )
    user_store.add_transaction(
        _TEST_USER, date="2026-07-05", category="transport", amount=200.0,
    )

    rows = user_store.get_transactions(_TEST_USER)

    assert len(rows) == 2
    assert rows[0]["category"] == "food"
    assert rows[0]["amount"] == 500.0
    assert rows[0]["merchant"] == "Zomato"
    assert rows[1]["merchant"] is None


def test_get_transactions_is_scoped_per_user():
    user_store.add_transaction(_TEST_USER, date="2026-07-01", category="food", amount=100.0)
    user_store.add_transaction(_TEST_USER + "_other", date="2026-07-01", category="food", amount=999.0)

    rows = user_store.get_transactions(_TEST_USER)

    assert len(rows) == 1
    assert rows[0]["amount"] == 100.0
    user_store.clear_transactions(_TEST_USER + "_other")


def test_clear_transactions_removes_all_rows_for_user():
    user_store.add_transaction(_TEST_USER, date="2026-07-01", category="food", amount=100.0)

    user_store.clear_transactions(_TEST_USER)

    assert user_store.get_transactions(_TEST_USER) == []


def test_risk_top_features_round_trips_through_save_and_get():
    top_features = [("debt_to_income", 1.2158), ("utilities_ratio", -0.9723)]

    user_store.save_financial_profile(
        _TEST_USER, monthly_income=60000.0, risk_label="Moderate",
        risk_confidence=0.83, risk_top_features=top_features,
    )
    profile = user_store.get_financial_profile(_TEST_USER)

    assert profile["risk_top_features"] == [list(pair) for pair in top_features]


def test_missing_risk_top_features_defaults_to_empty_list():
    user_store.save_financial_profile(_TEST_USER, monthly_income=60000.0)

    profile = user_store.get_financial_profile(_TEST_USER)

    assert profile["risk_top_features"] == []
