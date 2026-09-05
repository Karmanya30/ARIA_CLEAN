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
from shared.blocks import ExplanationBlock, MCQBlock, MasteryBlock, dump_blocks, text_or_error_blocks
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

        blocks = [
            ExplanationBlock(label="Cognitive", content=taxal["cognitive"]),
            ExplanationBlock(label="Functional", content=taxal["functional"]),
            ExplanationBlock(label="Causal", content=taxal["causal"]),
            MasteryBlock(topic=result["concept_name"], concept_id=result["concept_id"], score=result["mastery"]),
        ]
        if result["quiz"]:
            blocks.append(
                MCQBlock(
                    question=result["quiz"]["question"],
                    correct_answer=result["quiz"]["correct_answer"],
                    wrong_answers=result["quiz"]["wrong_answers"],
                    explanation=result["quiz"]["explanation"],
                    concept_id=result["quiz"]["concept_id"],
                )
            )

        return {
            "domain": "tutor",
            "query": query,
            "response": response_text,
            "blocks": dump_blocks(blocks),
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
    return {
        "domain": "tutor",
        "query": query,
        "context": context,
        "response": answer,
        "blocks": text_or_error_blocks(answer),
    }


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class TutorPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
