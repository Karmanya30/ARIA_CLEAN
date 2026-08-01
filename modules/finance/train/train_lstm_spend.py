"""
modules/finance/train/train_lstm_spend.py

Trains the LSTM spend forecaster on synthetic transaction data. Each
synthetic user has exactly LSTM_SEQ_LEN + LSTM_HORIZON = 15 months of
history, so this builds one (12-month input -> 3-month target) window per
user. Run scripts/generate_synthetic_transactions.py first.

Usage:
    python -m modules.finance.train.train_lstm_spend
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

from config.model_config import (
    LSTM_BATCH_SIZE,
    LSTM_EARLY_STOPPING_PATIENCE,
    LSTM_EPOCHS,
    LSTM_GRAD_CLIP,
    LSTM_HORIZON,
    LSTM_LR,
    LSTM_SEQ_LEN,
    LSTM_WEIGHT_DECAY,
    RANDOM_STATE,
)
from config.paths import LSTM_FORECAST_PATH, TRANSACTIONS_DIR
from modules.finance.forecast_model import SpendLSTM, build_sequence, monthly_category_ratios, total_loss


def build_dataset() -> tuple[np.ndarray, np.ndarray]:
    metadata_path = TRANSACTIONS_DIR / "_metadata.csv"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"{metadata_path} not found. Run "
            "`python -m scripts.generate_synthetic_transactions` first."
        )
    metadata = pd.read_csv(metadata_path)

    x_rows, y_rows = [], []
    for _, meta in metadata.iterrows():
        txn_df = pd.read_parquet(TRANSACTIONS_DIR / f"{meta['user_id']}.parquet")
        pivot = monthly_category_ratios(txn_df, meta["monthly_income"])
        if len(pivot) < LSTM_SEQ_LEN + LSTM_HORIZON:
            continue  # not enough history for a full window

        context_months = pivot.iloc[:LSTM_SEQ_LEN]
        target_months = pivot.iloc[LSTM_SEQ_LEN : LSTM_SEQ_LEN + LSTM_HORIZON]

        x_rows.append(build_sequence(context_months, seq_len=LSTM_SEQ_LEN))
        y_rows.append(target_months.values.astype(np.float32))

    return np.stack(x_rows), np.stack(y_rows)


def main() -> None:
    torch.manual_seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)

    x, y = build_dataset()
    n = len(x)
    idx = np.random.permutation(n)
    n_val = max(1, int(n * 0.2))
    val_idx, train_idx = idx[:n_val], idx[n_val:]

    x_train = torch.from_numpy(x[train_idx]).float()
    y_train = torch.from_numpy(y[train_idx]).float()
    x_val = torch.from_numpy(x[val_idx]).float()
    y_val = torch.from_numpy(y[val_idx]).float()

    train_loader = DataLoader(
        TensorDataset(x_train, y_train), batch_size=LSTM_BATCH_SIZE, shuffle=True
    )

    model = SpendLSTM()
    optimizer = torch.optim.Adam(model.parameters(), lr=LSTM_LR, weight_decay=LSTM_WEIGHT_DECAY)

    best_val_loss = float("inf")
    best_state = None
    patience_left = LSTM_EARLY_STOPPING_PATIENCE

    for epoch in range(LSTM_EPOCHS):
        model.train()
        for xb, yb in train_loader:
            optimizer.zero_grad()
            q10, q50, q90 = model(xb)
            loss = total_loss(q10, q50, q90, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), LSTM_GRAD_CLIP)
            optimizer.step()

        model.eval()
        with torch.no_grad():
            q10, q50, q90 = model(x_val)
            val_loss = total_loss(q10, q50, q90, y_val).item()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_left = LSTM_EARLY_STOPPING_PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                print(f"Early stopping at epoch {epoch + 1} (best val loss {best_val_loss:.5f})")
                break

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"epoch {epoch + 1:>3d}  val_loss={val_loss:.5f}")

    model.load_state_dict(best_state)

    # Report P50 MAE as a % of income (matches the acceptance criterion:
    # MAE < 15% of monthly income on held-out synthetic users).
    model.eval()
    with torch.no_grad():
        _, q50, _ = model(x_val)
    mae_ratio = (q50 - y_val).abs().mean().item()
    print(f"Held-out P50 MAE: {mae_ratio * 100:.2f}% of monthly income (target < 15%)")

    LSTM_FORECAST_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), LSTM_FORECAST_PATH)
    print(f"Saved model -> {LSTM_FORECAST_PATH}")


if __name__ == "__main__":
    main()
