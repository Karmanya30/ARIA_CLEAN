"""modules/finance/pipeline._try_build_financial_profile must load real,
user-entered transactions (shared/user_store.py) instead of the previous
hardcoded empty list -- otherwise the LSTM forecaster and Isolation Forest
anomaly detector never see real input in the live chat pipeline."""
from shared import user_store
from modules.finance.pipeline import _try_build_financial_profile

_TEST_USER = "__pytest_transactions_feed_profile__"


def _cleanup():
    user_store.clear_transactions(_TEST_USER)
    user_store.delete_financial_profile(_TEST_USER)


def test_profile_carries_zero_transactions_when_none_entered():
    _cleanup()
    try:
        profile = _try_build_financial_profile("I earn 50000 a month", _TEST_USER)
        assert profile is not None
        assert profile.transactions == []
    finally:
        _cleanup()


def test_profile_carries_real_transactions_once_entered():
    _cleanup()
    try:
        for i in range(3):
            user_store.add_transaction(
                _TEST_USER, date=f"2026-07-0{i + 1}", category="food", amount=500.0 + i,
            )

        profile = _try_build_financial_profile("I earn 50000 a month", _TEST_USER)

        assert profile is not None
        assert len(profile.transactions) == 3
        assert {t.category for t in profile.transactions} == {"food"}
    finally:
        _cleanup()


def test_annual_income_is_normalized_to_monthly_profile_income():
    _cleanup()
    try:
        profile = _try_build_financial_profile("My income is 2 crores a year", _TEST_USER)
        assert profile is not None
        assert profile.monthly_income == 20_000_000 / 12
    finally:
        _cleanup()
