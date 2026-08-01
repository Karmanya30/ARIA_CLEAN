"""
Isolation Forest — per-user transaction anomaly/fraud detection.

Fit fresh for each user, on their own transaction history, at request
time — a single global model would only catch "unusual in general," not
"unusual for this specific person," which is the actually useful signal
for a personal-finance assistant (per BTP report design).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from config.model_config import (
    IF_CONTAMINATION,
    IF_MAX_SAMPLES,
    IF_N_ESTIMATORS,
    IF_RANDOM_STATE,
)
from modules.finance.schemas import AnomalyFlag, Transaction

MIN_TRANSACTIONS = 10  # below this, there isn't enough history to fit a model


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["log_amount"] = np.log1p(df["amount"])
    df["day_of_week"] = df["date"].dt.dayofweek.astype(float)

    cat_median = df.groupby("category")["amount"].transform("median").replace(0, 1.0)
    df["amount_vs_median"] = df["amount"] / cat_median

    cat_mean = df.groupby("category")["amount"].transform("mean")
    cat_std = df.groupby("category")["amount"].transform("std").replace(0, np.nan).fillna(1.0)
    df["category_zscore"] = (df["amount"] - cat_mean) / cat_std

    return df[["log_amount", "day_of_week", "amount_vs_median", "category_zscore"]].fillna(0.0)


def _reason(feat_row: "pd.Series", txn: Transaction) -> str:
    if feat_row["amount_vs_median"] > 5:
        return (
            f"Amount ₹{txn.amount:,.0f} is {feat_row['amount_vs_median']:.1f}x this "
            f"user's median '{txn.category}' transaction."
        )
    if abs(feat_row["category_zscore"]) > 3:
        return f"Amount is a strong outlier for '{txn.category}' relative to this user's usual spend."
    return "Combination of amount, timing and category deviates from this user's usual pattern."


def detect_for_user(transactions: list[Transaction] | None) -> list[AnomalyFlag]:
    transactions = transactions or []
    if len(transactions) < MIN_TRANSACTIONS:
        return []

    df = pd.DataFrame([t.model_dump() for t in transactions])
    x = _build_features(df)

    model = IsolationForest(
        n_estimators=IF_N_ESTIMATORS,
        contamination=IF_CONTAMINATION,
        max_samples=IF_MAX_SAMPLES,
        random_state=IF_RANDOM_STATE,
        n_jobs=-1,
    )
    preds = model.fit_predict(x)
    scores = -model.score_samples(x)  # higher = more anomalous

    flags = []
    for i, txn in enumerate(transactions):
        if preds[i] == -1:
            flags.append(
                AnomalyFlag(transaction=txn, score=float(scores[i]), reason=_reason(x.iloc[i], txn))
            )
    return sorted(flags, key=lambda f: f.score, reverse=True)


class AnomalyDetector:
    """Thin OO wrapper for callers that prefer object style."""

    def detect(self, transactions: list[Transaction] | None) -> list[AnomalyFlag]:
        return detect_for_user(transactions)
