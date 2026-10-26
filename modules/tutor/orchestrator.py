"""
Module 2 orchestrator — concept retrieval (SBERT+FAISS) -> DKT mastery
estimate -> DQN teaching-action selection -> TAXAL explanation -> optional
quiz, all persisted per-user via shared/user_store.py so mastery evolves
across turns.
"""
from __future__ import annotations

from typing import Any

from modules.tutor import explainer, quiz as quiz_engine
from modules.tutor import retriever, teaching
from modules.tutor.knowledge import mastery_vector
from modules.tutor.schemas import TutorResponse
from shared import user_store


def _mastery_to_level(mastery: float) -> int:
    # mastery 0.0 -> level 1; mastery 1.0 -> level 6. Levels 7-8 are
    # reserved for a user explicitly asking for more technical depth.
    return int(1 + mastery * 5) if mastery < 1.0 else 6


def _last_n_accuracy(history: list[dict], n: int = 5) -> float:
    if not history:
        return 0.5
    last = history[-n:]
    return sum(1 for h in last if h["is_correct"]) / len(last)


def concept_by_id(concept_id: str | None) -> dict | None:
    import json

    from config.paths import CONCEPTS_KB_FILE

    if not concept_id:
        return None
    return next((c for c in json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8")) if c["id"] == concept_id), None)


def handle(user_id: str, query: str, force_quiz: bool = False, fallback_concept_id: str | None = None) -> dict[str, Any] | None:
    """Returns None if the query doesn't confidently match any concept in
    the knowledge base -- the caller should ask the user to rephrase.
    `force_quiz`: the learner asked to be quizzed; `fallback_concept_id`: the concept to use when the request names none
    ("quiz me on this")."""
    concept = retriever.best(query) or (concept_by_id(fallback_concept_id) if force_quiz else None)
    if concept is None:
        return None

    state = user_store.get_learning_state(user_id)
    history = state["history"]
    masteries = mastery_vector(history)

    target_mastery = masteries.get(concept["id"], 0.0)
    prereq_masteries = [masteries[p] for p in concept.get("prerequisites", []) if p in masteries]
    prereq_avg = sum(prereq_masteries) / len(prereq_masteries) if prereq_masteries else 0.5
    difficulty_norm = (
        concept.get("difficulty_floor", 1) + concept.get("difficulty_ceiling", 8)
    ) / 16.0

    action = teaching.choose_action(
        mastery_target=target_mastery,
        avg_mastery_prereqs=prereq_avg,
        last_5_accuracy=_last_n_accuracy(history),
        session_length=min(len(history) / 20.0, 1.0),
        concept_difficulty=difficulty_norm,
    )

    level = _mastery_to_level(target_mastery)
    taxal = explainer.explain(concept["canonical_name"], level, action=action)

    quiz_item = None
    # A cold-start learner is never picked for a quiz by the teaching policy, and mastery only moves on quiz answers, so
    # the Progress page stayed empty for ever: the first explanation of a concept always comes with a quiz to try.
    first_time = not any(h["concept_id"] == concept["id"] for h in history)
    if force_quiz or action == "ask_quiz" or first_time:
        quiz_item = quiz_engine.generate_quiz(concept["canonical_name"], concept["id"], level)

    response = TutorResponse(
        concept_id=concept["id"],
        concept_name=concept["canonical_name"],
        level=level,
        action=action,
        mastery=target_mastery,
        taxal=taxal,
        quiz=quiz_item,
    )
    return response.model_dump()


def record_answer(user_id: str, concept_id: str, is_correct: bool) -> dict[str, float]:
    """Call after the user answers a quiz question — updates and persists
    mastery so the next turn reflects it immediately."""
    state = user_store.get_learning_state(user_id)
    history = state["history"] + [{"concept_id": concept_id, "is_correct": bool(is_correct)}]
    masteries = mastery_vector(history)
    user_store.save_learning_state(user_id, masteries, history)
    return masteries
