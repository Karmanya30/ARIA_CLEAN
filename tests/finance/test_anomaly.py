"""Per-user Isolation Forest -- fit fresh at request time, no training
artifact needed, so this is fully testable without running any training
script first."""
import datetime as dt
import random

from modules.finance.anomaly import detect_for_user
from modules.finance.schemas import Transaction

CATEGORIES = ["housing", "food", "transport", "utilities", "emi", "entertainment", "medical", "other"]


def _normal_transactions(n=60, seed=1) -> list[Transaction]:
    rng = random.Random(seed)
    txns = []
    for i in range(n):
        txns.append(
            Transaction(
                date=dt.date(2026, 1, 1) + dt.timedelta(days=i % 28),
                category=rng.choice(CATEGORIES),
                amount=rng.uniform(200, 2000),
                channel=rng.choice(["upi", "card", "cash"]),
            )
        )
    return txns


def test_too_few_transactions_returns_no_flags():
    assert detect_for_user(_normal_transactions(n=5)) == []


def test_catches_an_injected_large_outlier():
    txns = _normal_transactions(n=60)
    outlier = Transaction(date=dt.date(2026, 1, 15), category="food", amount=250_000, channel="upi")
    flags = detect_for_user(txns + [outlier])
    flagged_amounts = {round(f.transaction.amount, 2) for f in flags}
    assert 250_000.0 in flagged_amounts


def test_no_transactions_does_not_crash():
    assert detect_for_user(None) == []
    assert detect_for_user([]) == []
