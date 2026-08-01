"""
modules/tutor/train/train_dqn_teacher.py

Trains the DQN teaching-strategy agent against a small simulated tutoring
environment: choosing actions (simplify / give example / quiz / deepen /
analogy / teach prerequisite) to move a simulated learner's mastery of one
concept toward 0.85 efficiently. Self-play against the environment below —
no external dataset needed, matching the RL nature of this component.

Usage:
    python -m modules.tutor.train.train_dqn_teacher
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from stable_baselines3 import DQN

from config.model_config import (
    DQN_BATCH_SIZE,
    DQN_BUFFER_SIZE,
    DQN_EXPLORATION_FINAL_EPS,
    DQN_EXPLORATION_FRACTION,
    DQN_GAMMA,
    DQN_LEARNING_RATE,
    DQN_TARGET_UPDATE_INTERVAL,
    DQN_TOTAL_TIMESTEPS,
    DQN_TRAIN_FREQ,
    RANDOM_STATE,
)
from config.paths import DQN_TEACHER_PATH
from config.settings import TEACHING_ACTIONS

MASTERY_TARGET_THRESHOLD = 0.85
MAX_STEPS = 10

# Base mastery gain per action -- calibrated so "ask_quiz" and "give_example"
# (active recall / worked examples) beat passive actions, matching
# real learning-science findings without over-fitting to a specific study.
BASE_GAIN = {
    "simplify_level_down": 0.05,
    "give_example": 0.08,
    "ask_quiz": 0.10,
    "increase_level": 0.03,
    "use_analogy": 0.07,
    "teach_prerequisite": 0.06,
}


class TutoringEnv(gym.Env):
    """5-dim state: [mastery_target, avg_mastery_prereqs, last_5_accuracy,
    session_length, concept_difficulty]. 6 discrete actions = TEACHING_ACTIONS."""

    def __init__(self):
        super().__init__()
        self.action_space = spaces.Discrete(len(TEACHING_ACTIONS))
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(5,), dtype=np.float32)
        self.state = np.zeros(5, dtype=np.float32)
        self.steps = 0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.state = self._sample_initial_state()
        self.steps = 0
        return self.state, {}

    def step(self, action_idx: int):
        action = TEACHING_ACTIONS[int(action_idx)]
        mastery_before = float(self.state[0])
        mastery_after, quiz_ok = self._transition(action)

        reward = -0.1  # per-action cost -> encourages efficient teaching
        if quiz_ok is True:
            reward += 1.0
        elif quiz_ok is False:
            reward -= 0.5
        if mastery_after >= MASTERY_TARGET_THRESHOLD and mastery_before < MASTERY_TARGET_THRESHOLD:
            reward += 2.0

        self.state = np.array([mastery_after, *self.state[1:]], dtype=np.float32)
        self.steps += 1
        terminated = bool(mastery_after >= MASTERY_TARGET_THRESHOLD or self.steps >= MAX_STEPS)
        return self.state, reward, terminated, False, {}

    def _sample_initial_state(self) -> np.ndarray:
        return np.array(
            [
                self.np_random.uniform(0.0, 0.4),  # mastery_target
                self.np_random.uniform(0.3, 0.9),  # avg_mastery_prereqs
                self.np_random.uniform(0.3, 0.7),  # last_5_accuracy
                0.0,  # session_length
                self.np_random.uniform(0.2, 0.8),  # concept_difficulty
            ],
            dtype=np.float32,
        )

    def _transition(self, action: str) -> tuple[float, bool | None]:
        base_gain = BASE_GAIN[action]
        prereq_bonus = 0.05 * (self.state[1] - 0.5)  # stronger prereq mastery -> faster gain
        gain = base_gain + prereq_bonus + float(self.np_random.normal(0, 0.02))
        new_mastery = float(np.clip(self.state[0] + gain, 0, 1))

        quiz_ok = None
        if action == "ask_quiz":
            quiz_ok = bool(self.np_random.random() < new_mastery)
        return new_mastery, quiz_ok


def main() -> None:
    env = TutoringEnv()
    model = DQN(
        "MlpPolicy",
        env,
        learning_rate=DQN_LEARNING_RATE,
        buffer_size=DQN_BUFFER_SIZE,
        batch_size=DQN_BATCH_SIZE,
        train_freq=DQN_TRAIN_FREQ,
        target_update_interval=DQN_TARGET_UPDATE_INTERVAL,
        exploration_fraction=DQN_EXPLORATION_FRACTION,
        exploration_final_eps=DQN_EXPLORATION_FINAL_EPS,
        gamma=DQN_GAMMA,
        seed=RANDOM_STATE,
        verbose=0,
    )
    model.learn(total_timesteps=DQN_TOTAL_TIMESTEPS, progress_bar=False)

    # Mean reward per episode should be positive once converged -- the -0.1
    # per-step cost makes a random/unconverged policy net negative.
    rewards = []
    for _ in range(50):
        obs, _ = env.reset()
        done = False
        total = 0.0
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(action)
            total += reward
            done = terminated or truncated
        rewards.append(total)
    print(f"Mean episode reward over 50 eval episodes: {np.mean(rewards):.3f} (target > 0)")

    DQN_TEACHER_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(DQN_TEACHER_PATH))
    print(f"Saved model -> {DQN_TEACHER_PATH}.zip")


if __name__ == "__main__":
    main()
