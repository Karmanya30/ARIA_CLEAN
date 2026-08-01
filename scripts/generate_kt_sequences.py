"""
scripts/generate_kt_sequences.py

Simulates learner-interaction sequences for training the DKT model using
an Item Response Theory model: P(correct) = sigmoid(ability - difficulty),
with a bonus for concepts whose prerequisites the learner has already
mastered. This is standard practice for bootstrapping Knowledge Tracing
research when real student interaction data isn't available (the line of
work DKT itself, Piech et al. 2015, comes from) — the architecture and
learned representations trained on this are real, only the training
corpus is synthetic.

Usage:
    python -m scripts.generate_kt_sequences
"""
from __future__ import annotations

import json
import random

import numpy as np

from config.paths import CONCEPTS_KB_FILE, KT_SEQUENCES_DIR

RANDOM_STATE = 42
N_LEARNERS = 200
MIN_INTERACTIONS = 50
MAX_INTERACTIONS = 90
PREREQ_BOOST = 0.8  # ability boost per already-mastered prerequisite
REPETITION_BOOST = 0.35  # per-attempt "practice makes perfect" effect, capped
REPETITION_CAP = 5
REVIEW_PROBABILITY = 0.6  # chance to re-practice a not-yet-mastered concept vs. explore new


def load_concepts() -> list[dict]:
    return json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8"))


def simulate_learner(
    concept_ids: list[str],
    concept_index: dict[str, int],
    prereqs: dict[str, list[str]],
    difficulty: dict[str, float],
    ability: float,
    n_steps: int,
    rng: random.Random,
    np_rng: np.random.Generator,
) -> list[dict]:
    mastered: set[str] = set()  # concepts answered correctly 2+ times in a row
    attempted: set[str] = set()
    attempt_count: dict[str, int] = {}
    correct_streak: dict[str, int] = {}
    history = []

    for _ in range(n_steps):
        eligible_new = [
            cid
            for cid in concept_ids
            if cid not in attempted and all(p in attempted for p in prereqs[cid])
        ]
        review_candidates = [cid for cid in attempted if correct_streak.get(cid, 0) < 2]

        if review_candidates and (not eligible_new or rng.random() < REVIEW_PROBABILITY):
            # Realistic spaced repetition: practice struggling concepts more.
            weights = [1.0 / (1 + correct_streak.get(cid, 0)) for cid in review_candidates]
            cid = rng.choices(review_candidates, weights=weights, k=1)[0]
        elif eligible_new:
            cid = rng.choice(eligible_new)
        else:
            cid = rng.choice(concept_ids)

        prereq_bonus = PREREQ_BOOST * sum(1 for p in prereqs[cid] if p in mastered)
        repetition_bonus = REPETITION_BOOST * min(attempt_count.get(cid, 0), REPETITION_CAP)
        p_correct = 1.0 / (1.0 + np.exp(-(ability - difficulty[cid] + prereq_bonus + repetition_bonus)))
        is_correct = bool(np_rng.random() < p_correct)

        history.append(
            {"concept_id": cid, "concept_idx": concept_index[cid], "is_correct": is_correct}
        )
        attempted.add(cid)
        attempt_count[cid] = attempt_count.get(cid, 0) + 1
        correct_streak[cid] = correct_streak.get(cid, 0) + 1 if is_correct else 0
        if correct_streak[cid] >= 2:
            mastered.add(cid)

    return history


def main() -> None:
    rng = random.Random(RANDOM_STATE)
    np_rng = np.random.default_rng(RANDOM_STATE)

    concepts = load_concepts()
    concept_ids = [c["id"] for c in concepts]
    concept_index = {cid: i for i, cid in enumerate(concept_ids)}
    prereqs = {c["id"]: c["prerequisites"] for c in concepts}
    difficulty = {cid: float(np_rng.normal(0, 1)) for cid in concept_ids}

    learners = []
    for i in range(N_LEARNERS):
        ability = float(np_rng.normal(0, 1))
        n_steps = rng.randint(MIN_INTERACTIONS, MAX_INTERACTIONS)
        history = simulate_learner(
            concept_ids, concept_index, prereqs, difficulty, ability, n_steps, rng, np_rng
        )
        learners.append({"learner_id": f"sim_{i:04d}", "history": history})

    KT_SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = KT_SEQUENCES_DIR / "sequences.json"
    out_path.write_text(json.dumps(learners), encoding="utf-8")
    print(f"Generated {len(learners)} simulated learner sequences -> {out_path}")


if __name__ == "__main__":
    main()
