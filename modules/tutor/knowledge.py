"""
Deep Knowledge Tracing (DKT) — Piech et al. (2015) style LSTM mastery
tracker. Predicts, for every one of the 50 concepts, the probability the
learner would answer correctly if quizzed right now, given their full
interaction history so far.

Train first: python -m modules.tutor.train.train_lstm_kt
"""
from __future__ import annotations

import json

import torch
import torch.nn as nn

from config.model_config import DKT_DROPOUT, DKT_HIDDEN, DKT_LAYERS, DKT_N_CONCEPTS
from config.paths import CONCEPTS_KB_FILE, DKT_MODEL_PATH


class DKT(nn.Module):
    """Input: (B, T, 2K) one-hot over (concept, correctness).
    Output: (B, T, K) sigmoid mastery probability per concept."""

    def __init__(
        self,
        n_concepts: int = DKT_N_CONCEPTS,
        hidden: int = DKT_HIDDEN,
        layers: int = DKT_LAYERS,
        dropout: float = DKT_DROPOUT,
    ):
        super().__init__()
        self.n = n_concepts
        self.lstm = nn.LSTM(
            2 * n_concepts,
            hidden,
            num_layers=layers,
            batch_first=True,
            dropout=dropout if layers > 1 else 0.0,
        )
        self.head = nn.Linear(hidden, n_concepts)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, _ = self.lstm(x)
        return torch.sigmoid(self.head(h))


def encode_interaction(
    concept_idxs: list[int], corrects: list[int], n_concepts: int = DKT_N_CONCEPTS
) -> torch.Tensor:
    t_len = len(concept_idxs)
    x = torch.zeros(t_len, 2 * n_concepts)
    for t, (c, y) in enumerate(zip(concept_idxs, corrects)):
        idx = c if y == 1 else c + n_concepts
        x[t, idx] = 1.0
    return x


# ── concept id <-> index mapping, fixed by the KB file's order ─────────
_CONCEPT_IDS: list[str] | None = None


def concept_ids() -> list[str]:
    global _CONCEPT_IDS
    if _CONCEPT_IDS is None:
        concepts = json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8"))
        _CONCEPT_IDS = [c["id"] for c in concepts]
    return _CONCEPT_IDS


def concept_index(concept_id: str) -> int:
    return concept_ids().index(concept_id)


# ── inference ────────────────────────────────────────────────────────
_model: DKT | None = None


def is_trained() -> bool:
    return DKT_MODEL_PATH.exists()


def _load() -> DKT:
    global _model
    if _model is not None:
        return _model
    if not is_trained():
        raise FileNotFoundError(
            f"{DKT_MODEL_PATH} not found. Train it first: "
            "python -m modules.tutor.train.train_lstm_kt"
        )
    model = DKT()
    model.load_state_dict(torch.load(DKT_MODEL_PATH, map_location="cpu"))
    model.eval()
    _model = model
    return model


def mastery_vector(history: list[dict]) -> dict[str, float]:
    """Current mastery probability for every concept, given a user's
    interaction history: [{"concept_id": str, "is_correct": bool}, ...].
    Returns all-zero mastery (cold start) if there's no history yet."""
    ids = concept_ids()
    if not history:
        return dict.fromkeys(ids, 0.0)

    model = _load()
    concept_idxs = [concept_index(h["concept_id"]) for h in history]
    corrects = [int(h["is_correct"]) for h in history]
    x = encode_interaction(concept_idxs, corrects).unsqueeze(0)

    with torch.no_grad():
        probs = model(x)[0, -1, :]  # last timestep

    return {cid: float(probs[i]) for i, cid in enumerate(ids)}


class KnowledgeModel:
    """Thin OO wrapper matching the original stub's calling convention."""

    def predict(self, history: list[dict]) -> dict[str, float]:
        return mastery_vector(history)
