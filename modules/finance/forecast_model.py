"""
LSTM spending forecaster — 3-month-ahead category-wise spend, quantile
regression (P10/P50/P90). Operates on income-normalized ratios (spend /
monthly_income) rather than raw rupees so the model generalizes across
users of very different income levels; predictions are scaled back to ₹
by the caller-facing `predict()` function.

Train first: python -m modules.finance.train.train_lstm_spend
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from config.model_config import (
    LSTM_DROPOUT,
    LSTM_HIDDEN,
    LSTM_HORIZON,
    LSTM_LAYERS,
    LSTM_N_CATS,
    LSTM_N_CTX,
    LSTM_QUANTILES,
    LSTM_SEQ_LEN,
)
from config.paths import LSTM_FORECAST_PATH
from modules.finance.schemas import CATEGORIES, CategoryForecast, Transaction

N_FEATURES = LSTM_N_CATS + LSTM_N_CTX


class SpendLSTM(nn.Module):
    """Stacked LSTM with three quantile regression heads (P10/P50/P90)."""

    def __init__(
        self,
        n_features: int = N_FEATURES,
        hidden: int = LSTM_HIDDEN,
        layers: int = LSTM_LAYERS,
        horizon: int = LSTM_HORIZON,
        n_categories: int = LSTM_N_CATS,
        dropout: float = LSTM_DROPOUT,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            n_features,
            hidden,
            num_layers=layers,
            batch_first=True,
            dropout=dropout if layers > 1 else 0.0,
        )
        self.head_q10 = nn.Linear(hidden, horizon * n_categories)
        self.head_q50 = nn.Linear(hidden, horizon * n_categories)
        self.head_q90 = nn.Linear(hidden, horizon * n_categories)
        self.horizon, self.n_cats = horizon, n_categories

    def forward(self, x: torch.Tensor):
        out, _ = self.lstm(x)
        h = out[:, -1, :]  # last timestep's hidden state

        def shape(y: torch.Tensor) -> torch.Tensor:
            return y.view(-1, self.horizon, self.n_cats)

        return shape(self.head_q10(h)), shape(self.head_q50(h)), shape(self.head_q90(h))


def quantile_loss(pred: torch.Tensor, target: torch.Tensor, q: float) -> torch.Tensor:
    diff = target - pred
    return torch.maximum(q * diff, (q - 1) * diff).mean()


def total_loss(q10: torch.Tensor, q50: torch.Tensor, q90: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    lo, mid, hi = LSTM_QUANTILES
    return quantile_loss(q10, y, lo) + quantile_loss(q50, y, mid) + quantile_loss(q90, y, hi)


# ── Sequence building (shared by training + inference) ─────────────────
def monthly_category_ratios(txn_df: pd.DataFrame, monthly_income: float) -> pd.DataFrame:
    """Month-indexed DataFrame of category spend / income ratios."""
    if txn_df is None or txn_df.empty or monthly_income <= 0:
        return pd.DataFrame(columns=CATEGORIES)
    df = txn_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    pivot = df.pivot_table(
        index="month", columns="category", values="amount", aggfunc="sum", fill_value=0.0
    )
    for c in CATEGORIES:
        if c not in pivot.columns:
            pivot[c] = 0.0
    return (pivot[CATEGORIES] / monthly_income).sort_index()


def _month_onehot(period) -> np.ndarray:
    vec = np.zeros(LSTM_N_CTX, dtype=np.float32)
    vec[period.month - 1] = 1.0
    return vec


def build_sequence(pivot: pd.DataFrame, seq_len: int = LSTM_SEQ_LEN) -> np.ndarray:
    """(seq_len, N_FEATURES) array from the last `seq_len` months of `pivot`,
    zero-padded at the front if fewer months of history exist."""
    months = list(pivot.index)[-seq_len:]
    rows = [
        np.concatenate([pivot.loc[m].values.astype(np.float32), _month_onehot(m)])
        for m in months
    ]
    if len(rows) < seq_len:
        pad = [np.zeros(N_FEATURES, dtype=np.float32)] * (seq_len - len(rows))
        rows = pad + rows
    return np.stack(rows)


# ── Inference ────────────────────────────────────────────────────────────
_model: SpendLSTM | None = None


def is_trained() -> bool:
    return LSTM_FORECAST_PATH.exists()


def _load() -> SpendLSTM:
    global _model
    if _model is not None:
        return _model
    if not is_trained():
        raise FileNotFoundError(
            f"{LSTM_FORECAST_PATH} not found. Train it first: "
            "python -m modules.finance.train.train_lstm_spend"
        )
    model = SpendLSTM()
    model.load_state_dict(torch.load(LSTM_FORECAST_PATH, map_location="cpu"))
    model.eval()
    _model = model
    return model


def predict(
    monthly_income: float, transactions: list[Transaction] | None = None
) -> list[CategoryForecast]:
    """3-month category-wise spend forecast in ₹, with P10/P90 bounds.
    Falls back to an all-zero forecast (no ML) if there's no transaction
    history at all to build a sequence from."""
    from modules.finance.features import transactions_to_dataframe

    txn_df = transactions_to_dataframe(transactions or [])
    pivot = monthly_category_ratios(txn_df, monthly_income)

    if len(pivot) == 0:
        return [
            CategoryForecast(
                category=c,
                forecast=[0.0] * LSTM_HORIZON,
                lower_ci=[0.0] * LSTM_HORIZON,
                upper_ci=[0.0] * LSTM_HORIZON,
            )
            for c in CATEGORIES
        ]

    model = _load()
    seq = build_sequence(pivot)
    x = torch.from_numpy(seq).unsqueeze(0).float()

    with torch.no_grad():
        q10, q50, q90 = model(x)

    q10 = np.clip(q10.squeeze(0).numpy(), 0, None) * monthly_income
    q50 = np.clip(q50.squeeze(0).numpy(), 0, None) * monthly_income
    q90 = np.clip(q90.squeeze(0).numpy(), 0, None) * monthly_income

    return [
        CategoryForecast(
            category=cat,
            forecast=[round(float(v), 2) for v in q50[:, i]],
            lower_ci=[round(float(v), 2) for v in q10[:, i]],
            upper_ci=[round(float(v), 2) for v in q90[:, i]],
        )
        for i, cat in enumerate(CATEGORIES)
    ]
