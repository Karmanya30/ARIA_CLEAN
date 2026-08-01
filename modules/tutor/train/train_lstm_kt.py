"""
modules/tutor/train/train_lstm_kt.py

Trains the DKT model on simulated IRT-based learner interactions.
Run scripts/generate_kt_sequences.py first.

Usage:
    python -m modules.tutor.train.train_lstm_kt
"""
from __future__ import annotations

import json

import numpy as np
import torch
import torch.nn as nn
from torch.nn.utils.rnn import pad_sequence

from config.model_config import (
    DKT_BATCH_SIZE,
    DKT_EARLY_STOPPING_PATIENCE,
    DKT_EPOCHS,
    DKT_GRAD_CLIP,
    DKT_LR,
    DKT_N_CONCEPTS,
    DKT_WEIGHT_DECAY,
    RANDOM_STATE,
)
from config.paths import DKT_MODEL_PATH, KT_SEQUENCES_DIR
from modules.tutor.knowledge import DKT, encode_interaction

N = DKT_N_CONCEPTS


def load_sequences() -> list[dict]:
    path = KT_SEQUENCES_DIR / "sequences.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m scripts.generate_kt_sequences` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_training_tensors(learners: list[dict]):
    """Input covers interaction steps [0, T-2]; targets are the concept and
    correctness of steps [1, T-1] (standard next-step DKT training)."""
    inputs, next_idx, next_correct, lengths = [], [], [], []
    for learner in learners:
        history = learner["history"]
        if len(history) < 2:
            continue
        concept_idxs = [h["concept_idx"] for h in history]
        corrects = [int(h["is_correct"]) for h in history]

        inputs.append(encode_interaction(concept_idxs[:-1], corrects[:-1], n_concepts=N))
        next_idx.append(torch.tensor(concept_idxs[1:], dtype=torch.long))
        next_correct.append(torch.tensor(corrects[1:], dtype=torch.float32))
        lengths.append(len(history) - 1)

    padded_x = pad_sequence(inputs, batch_first=True)
    padded_next_idx = pad_sequence(next_idx, batch_first=True)
    padded_next_correct = pad_sequence(next_correct, batch_first=True)
    return padded_x, padded_next_idx, padded_next_correct, torch.tensor(lengths, dtype=torch.long)


def _gather_predictions(preds: torch.Tensor, next_idx: torch.Tensor) -> torch.Tensor:
    return torch.gather(preds, 2, next_idx.unsqueeze(-1)).squeeze(-1)


def _valid_mask(preds: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
    return torch.arange(preds.size(1)).unsqueeze(0) < lengths.unsqueeze(1)


def masked_bce_loss(preds, next_idx, next_correct, lengths) -> torch.Tensor:
    gathered = _gather_predictions(preds, next_idx)
    mask = _valid_mask(preds, lengths).float()
    bce = nn.functional.binary_cross_entropy(
        gathered.clamp(1e-6, 1 - 1e-6), next_correct, reduction="none"
    )
    return (bce * mask).sum() / mask.sum()


def masked_auc(preds, next_idx, next_correct, lengths) -> float:
    from sklearn.metrics import roc_auc_score

    gathered = _gather_predictions(preds, next_idx)
    mask = _valid_mask(preds, lengths)
    y_true = next_correct[mask].detach().numpy()
    y_score = gathered[mask].detach().numpy()
    if len(set(y_true.tolist())) < 2:
        return float("nan")
    return roc_auc_score(y_true, y_score)


def main() -> None:
    torch.manual_seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)

    learners = load_sequences()
    rng = np.random.default_rng(RANDOM_STATE)
    idx = rng.permutation(len(learners))
    n_val = max(1, int(len(learners) * 0.2))
    val_learners = [learners[i] for i in idx[:n_val]]
    train_learners = [learners[i] for i in idx[n_val:]]

    x_train, next_idx_train, next_correct_train, len_train = build_training_tensors(train_learners)
    x_val, next_idx_val, next_correct_val, len_val = build_training_tensors(val_learners)

    model = DKT()
    optimizer = torch.optim.Adam(model.parameters(), lr=DKT_LR, weight_decay=DKT_WEIGHT_DECAY)

    n_train = x_train.size(0)
    best_val_loss = float("inf")
    best_state = None
    patience_left = DKT_EARLY_STOPPING_PATIENCE

    for epoch in range(DKT_EPOCHS):
        model.train()
        perm = torch.randperm(n_train)
        for start in range(0, n_train, DKT_BATCH_SIZE):
            batch_idx = perm[start : start + DKT_BATCH_SIZE]
            optimizer.zero_grad()
            preds = model(x_train[batch_idx])
            loss = masked_bce_loss(
                preds, next_idx_train[batch_idx], next_correct_train[batch_idx], len_train[batch_idx]
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), DKT_GRAD_CLIP)
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_preds = model(x_val)
            val_loss = masked_bce_loss(val_preds, next_idx_val, next_correct_val, len_val).item()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_left = DKT_EARLY_STOPPING_PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                print(f"Early stopping at epoch {epoch + 1} (best val loss {best_val_loss:.4f})")
                break

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"epoch {epoch + 1:>3d}  val_loss={val_loss:.4f}")

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        val_preds = model(x_val)
    auc = masked_auc(val_preds, next_idx_val, next_correct_val, len_val)
    print(f"Held-out AUC: {auc:.3f} (target > 0.80)")

    DKT_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), DKT_MODEL_PATH)
    print(f"Saved model -> {DKT_MODEL_PATH}")


if __name__ == "__main__":
    main()
