"""Module 1's transaction entry -- feeds the LSTM spend forecaster and
Isolation Forest anomaly detector, which otherwise only ever see an empty
list (see modules/finance/pipeline.py's _load_transactions)."""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionRequest(BaseModel):
    session_id: str
    date: str
    category: str
    amount: float
    merchant: str | None = None
    channel: str | None = None


@router.get("")
def list_transactions(session_id: str) -> list[dict[str, Any]]:
    from shared.user_store import get_transactions

    return get_transactions(session_id)


@router.post("")
def add_transaction(req: TransactionRequest) -> dict[str, str]:
    from shared.user_store import add_transaction

    add_transaction(
        req.session_id, date=req.date, category=req.category, amount=req.amount,
        merchant=req.merchant, channel=req.channel,
    )
    return {"status": "added"}


@router.delete("")
def clear_all_transactions(session_id: str) -> dict[str, str]:
    from shared.user_store import clear_transactions

    clear_transactions(session_id)
    return {"status": "cleared"}


@router.post("/sample")
def load_sample_transactions(req: dict[str, str]) -> dict[str, str]:
    """Deterministic synthetic transactions spanning two months, including
    one deliberate outlier -- enough to clear anomaly.py's MIN_TRANSACTIONS
    (10) and give the forecaster a real multi-month sequence, so trying the
    forecast/anomaly models doesn't require manually adding 15+ rows."""
    from shared.user_store import add_transaction

    session_id = req["session_id"]
    rng = random.Random(f"sample_txns_{session_id}")
    today = date.today()
    rows = [
        (5, "housing", 18000, "Rent", "netbanking"),
        (7, "food", 3200, "BigBasket", "upi"),
        (12, "food", 850, "Zomato", "upi"),
        (14, "transport", 1200, "Ola", "upi"),
        (18, "utilities", 2400, "Electricity Board", "netbanking"),
        (20, "entertainment", 600, "Netflix", "card"),
        (25, "food", 4100, "Local Market", "cash"),
        (35, "housing", 18000, "Rent", "netbanking"),
        (38, "food", 2900, "BigBasket", "upi"),
        (42, "transport", 950, "Uber", "upi"),
        (45, "medical", 1500, "Apollo Pharmacy", "card"),
        (48, "utilities", 2600, "Electricity Board", "netbanking"),
        (52, "other", 55000, "Electronics Store", "card"),  # deliberate outlier
        (55, "entertainment", 700, "Netflix", "card"),
        (58, "food", 3400, "BigBasket", "upi"),
    ]
    for days_ago, category, amount, merchant, channel in rows:
        jitter = rng.randint(-50, 50)
        add_transaction(
            session_id,
            date=(today - timedelta(days=days_ago)).isoformat(),
            category=category,
            amount=max(1.0, amount + jitter),
            merchant=merchant,
            channel=channel,
        )
    return {"status": "loaded", "count": str(len(rows))}
