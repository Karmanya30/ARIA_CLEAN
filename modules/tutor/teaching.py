"""
DQN teaching-strategy agent — chooses the next tutoring action (simplify /
give example / quiz / deepen / analogy / teach prerequisite) to move a
learner toward mastery efficiently. Trained via reinforcement learning
against a small simulated tutoring environment (self-play, no external
dataset needed) — see modules/tutor/train/train_dqn_teacher.py.

Train first: python -m modules.tutor.train.train_dqn_teacher
"""
from __future__ import annotations

import numpy as np

from config.paths import DQN_TEACHER_PATH
from config.settings import TEACHING_ACTIONS

_model = None


def is_trained() -> bool:
    return DQN_TEACHER_PATH.with_suffix(".zip").exists()


def _load():
    global _model
    if _model is not None:
        return _model
    if not is_trained():
        raise FileNotFoundError(
            f"{DQN_TEACHER_PATH}.zip not found. Train it first: "
            "python -m modules.tutor.train.train_dqn_teacher"
        )
    from stable_baselines3 import DQN

    _model = DQN.load(str(DQN_TEACHER_PATH))
    return _model


def choose_action(
    mastery_target: float,
    avg_mastery_prereqs: float,
    last_5_accuracy: float,
    session_length: float,
    concept_difficulty: float,
) -> str:
    model = _load()
    state = np.array(
        [mastery_target, avg_mastery_prereqs, last_5_accuracy, session_length, concept_difficulty],
        dtype=np.float32,
    )
    action_idx, _ = model.predict(state, deterministic=True)
    return TEACHING_ACTIONS[int(action_idx)]


class TeachingAgent:
    """Thin OO wrapper matching the original stub's calling convention."""

    def choose(self, **kwargs) -> str:
        return choose_action(**kwargs)
