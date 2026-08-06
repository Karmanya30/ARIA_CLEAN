"""Feature engineering shared by XGBoost training and inference.

Kept DataFrame-based (rather than pydantic-based) so the training script can
process ~150 synthetic users' full transaction histories quickly; the live
pipeline converts its `list[Transaction]` into the same DataFrame shape via
`transactions_to_dataframe` before calling `build_user_feature_row`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.finance.schemas import CATEGORIES, Transaction

FEATURE_NAMES = [
    "income_log",
    "age",
    "dependents",
    "debt_to_income",
    "savings_rate",
    *[f"{c}_ratio" for c in CATEGORIES],
    "discretionary_ratio",
    "essential_ratio",
    "spend_volatility",
    "max_single_txn_ratio",
    "pct_cash",
    "pct_upi",
    "log_txn_count",
    "festive_spike",
    "neg_balance_months",
    "city_tier",
]


def transactions_to_dataframe(transactions: list[Transaction]) -> pd.DataFrame:
    if not transactions:
        return pd.DataFrame(columns=["date", "category", "amount", "channel"])
    return pd.DataFrame([t.model_dump() for t in transactions])


def build_user_feature_row(
    txn_df: pd.DataFrame,
    monthly_income: float,
    age: int,
    dependents: int,
    existing_emi: float,
    city_tier: int,
) -> dict[str, float]:
    """Derive the XGBoost feature vector for one user from their transaction
    history + profile fields. Returns an all-zero row if there's not enough
    data, rather than raising — callers decide whether that's acceptable."""
    if monthly_income <= 0 or txn_df is None or txn_df.empty:
        return dict.fromkeys(FEATURE_NAMES, 0.0)

    df = txn_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")

    monthly_totals = df.groupby("month")["amount"].sum()
    n_months = max(1, len(monthly_totals))

    cat_totals = df.groupby("category")["amount"].sum()
    cat_ratio = {
        c: float(cat_totals.get(c, 0.0)) / n_months / monthly_income for c in CATEGORIES
    }

    avg_monthly_spend = float(monthly_totals.mean())
    savings_rate = 1.0 - (avg_monthly_spend / monthly_income)
    mean_total = float(monthly_totals.mean())
    spend_volatility = float(monthly_totals.std() / mean_total) if mean_total else 0.0

    pct_cash = float((df["channel"] == "cash").mean()) if "channel" in df else 0.0
    pct_upi = float((df["channel"] == "upi").mean()) if "channel" in df else 0.0

    median_total = float(monthly_totals.median())
    festive_spike = float(monthly_totals.max() / median_total) if median_total else 1.0
    neg_balance_months = int((monthly_totals > monthly_income).sum())

    row = {
        "income_log": float(np.log1p(monthly_income)),
        "age": float(age),
        "dependents": float(dependents),
        "debt_to_income": float(existing_emi / monthly_income),
        "savings_rate": float(savings_rate),
        **{f"{c}_ratio": float(cat_ratio[c]) for c in CATEGORIES},
        "discretionary_ratio": float(
            cat_ratio.get("entertainment", 0.0) + cat_ratio.get("other", 0.0)
        ),
        "essential_ratio": float(
            cat_ratio.get("housing", 0.0)
            + cat_ratio.get("food", 0.0)
            + cat_ratio.get("utilities", 0.0)
        ),
        "spend_volatility": spend_volatility,
        "max_single_txn_ratio": float(df["amount"].max() / monthly_income),
        "pct_cash": pct_cash,
        "pct_upi": pct_upi,
        "log_txn_count": float(np.log1p(len(df) / n_months)),
        "festive_spike": festive_spike,
        "neg_balance_months": float(neg_balance_months),
        "city_tier": float(city_tier),
    }
    return row
