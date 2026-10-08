"""
Quiz engine — generates one MCQ per concept via the shared LLM client
(Groq, falling back to Gemini), using the M2_QUIZ prompt template, and
parses the QUESTION/CORRECT/WRONG_1-3/EXPLANATION format it enforces.
"""
from __future__ import annotations

import re

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import M2_QUIZ
from shared.human_state import quiet
from modules.finance import personal
from modules.tutor.schemas import QuizItem

_FIELDS = ["QUESTION", "CORRECT", "WRONG_1", "WRONG_2", "WRONG_3", "EXPLANATION"]


def _parse_quiz_text(text: str, concept_id: str) -> QuizItem | None:
    values: dict[str, str] = {}
    for i, field in enumerate(_FIELDS):
        next_fields = _FIELDS[i + 1 :]
        if next_fields:
            pattern = rf"{field}:\s*(.*?)(?=(?:{'|'.join(next_fields)}):|$)"
        else:
            pattern = rf"{field}:\s*(.*)"
        match = re.search(pattern, text, re.DOTALL)
        if not match or not match.group(1).strip():
            return None
        values[field] = match.group(1).strip()

    return QuizItem(
        question=values["QUESTION"],
        correct_answer=values["CORRECT"],
        wrong_answers=[values["WRONG_1"], values["WRONG_2"], values["WRONG_3"]],
        explanation=values["EXPLANATION"],
        concept_id=concept_id,
    )


def generate_quiz(concept_name: str, concept_id: str, level: int = 3) -> QuizItem | None:
    """None if the LLM output didn't match the expected format — callers
    should re-prompt once or fall back gracefully, never crash."""
    prompt = M2_QUIZ.format(concept=concept_name, level=max(1, min(8, level)))
    if learner := personal.learner_context(personal.profile()):
        prompt += f"\nUse these numbers in any \u20b9 example: {learner}"
    with quiet():  # output is parsed by format: no tone guide
        text = generate_response(prompt)
    return _parse_quiz_text(text, concept_id)


def grade(quiz: QuizItem, selected_answer: str) -> bool:
    return selected_answer.strip().lower() == quiz.correct_answer.strip().lower()


class QuizEngine:
    """Thin OO wrapper for callers that prefer object style."""

    def generate(self, concept_name: str, concept_id: str, level: int = 3) -> QuizItem | None:
        return generate_quiz(concept_name, concept_id, level)

    def grade(self, quiz: QuizItem, selected_answer: str) -> bool:
        return grade(quiz, selected_answer)
