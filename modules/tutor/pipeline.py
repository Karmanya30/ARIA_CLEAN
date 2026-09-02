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
from shared import finance_knowledge
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

    # No confident concept match in the 50-concept KB -- generic tutor
    # prompt (still useful for greetings, meta-questions, etc.) rather
    # than a hard failure. Try the broader finance_knowledge namespace
    # first (covers real finance topics outside the 50-concept KB, e.g.
    # "what is a REIT") so the answer is grounded rather than raw recall.
    context = build_context(query)
    grounding = finance_knowledge.grounding_for(query)
    prompt = tutor_prompt(query, context, grounding=grounding)
    answer = generate_response(prompt)
    return {"domain": "tutor", "query": query, "context": context, "response": answer}


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class TutorPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
