"""
Tutor pipeline: Module 2 orchestrator (retrieval -> DKT -> DQN -> TAXAL)
with a generic LLM fallback for queries that don't confidently match any
concept in the knowledge base.
"""
from __future__ import annotations

import re
from typing import Any

from loguru import logger

from ai.llm.groq_client import generate_response
from modules.tutor import orchestrator as m2_orchestrator
from shared.ner import extract_entities


def build_context(query: str) -> dict[str, Any]:
    return {"entities": extract_entities(query)}


_QUIZ_ASK = re.compile(r"\b(quiz|test me|test my|mcqs?|practice questions?|check my understanding)\b", re.I)


def is_quiz_request(query: str) -> bool:
    return bool(_QUIZ_ASK.search(query))


def _last_concept_id(user_id: str) -> str | None:
    """The concept of the most recent tutor reply in this conversation ("quiz me on this")."""
    from core.session import get_session

    for turn in reversed(get_session(user_id).get("history", [])):
        cid = (turn.get("response") or {}).get("quiz", {}) or {}
        cid = cid.get("concept_id") or (turn.get("response") or {}).get("concept_id")
        if cid:
            return cid
    return None


def run_pipeline(query: str, user_id: str = "default") -> dict[str, Any]:
    want_quiz = is_quiz_request(query)
    try:
        if want_quiz:
            result = m2_orchestrator.handle(user_id, _QUIZ_ASK.sub(" ", query), force_quiz=True, fallback_concept_id=_last_concept_id(user_id))
        else:
            result = m2_orchestrator.handle(user_id, query)
    except FileNotFoundError:
        logger.warning("Tutor resources unavailable; using conversational fallback")
        result = None
    if result is not None:
        taxal = result["taxal"]
        response_text = (
            f"Cognitive: {taxal['cognitive']}\n"
            f"Functional: {taxal['functional']}\n"
            f"Causal: {taxal['causal']}"
        )
        if want_quiz and result["quiz"]:
            response_text = f"Here's a quick question on {result['concept_name']}. Pick the answer you think is right."
        return {
            "domain": "tutor",
            "query": query,
            "response": response_text,
            "concept": result["concept_name"],
            "concept_id": result["concept_id"],
            "level": result["level"],
            "action": result["action"],
            "mastery": result["mastery"],
            "taxal": taxal,
            "quiz": result["quiz"],
        }

    # No confident concept match -- generic tutor prompt (still useful for
    # greetings, meta-questions, etc.) rather than a hard failure.
    # No finance concept was retrieved: answer normally rather than forcing a finance lesson.
    from shared.dialogue import CONVERSATION_SYSTEM
    from shared.conversation_memory import augment
    answer = generate_response(augment(query, CONVERSATION_SYSTEM), system_prompt=CONVERSATION_SYSTEM)
    return {"domain": "tutor", "query": query, "context": {}, "response": answer}


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class TutorPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
