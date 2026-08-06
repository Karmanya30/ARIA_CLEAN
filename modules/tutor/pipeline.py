"""
Tutor pipeline: Module 2 orchestrator (retrieval -> DKT -> DQN -> TAXAL)
with a generic LLM fallback for queries that don't confidently match any
concept in the knowledge base.
"""
from __future__ import annotations

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import tutor_prompt
from modules.tutor import orchestrator as m2_orchestrator
from shared.ner import extract_entities


def build_context(query: str) -> dict[str, Any]:
    return {"entities": extract_entities(query)}


def run_pipeline(query: str, user_id: str = "default") -> dict[str, Any]:
    result = m2_orchestrator.handle(user_id, query)
    if result is not None:
        taxal = result["taxal"]
        response_text = (
            f"Cognitive: {taxal['cognitive']}\n"
            f"Functional: {taxal['functional']}\n"
            f"Causal: {taxal['causal']}"
        )
        return {
            "domain": "tutor",
            "query": query,
            "response": response_text,
            "concept": result["concept_name"],
            "level": result["level"],
            "action": result["action"],
            "mastery": result["mastery"],
            "taxal": taxal,
            "quiz": result["quiz"],
        }

    # No confident concept match -- generic tutor prompt (still useful for
    # greetings, meta-questions, etc.) rather than a hard failure.
    context = build_context(query)
    prompt = tutor_prompt(query, context)
    answer = generate_response(prompt)
    return {"domain": "tutor", "query": query, "context": context, "response": answer}


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class TutorPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
