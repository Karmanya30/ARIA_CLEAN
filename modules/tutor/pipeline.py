"""
Tutor pipeline: Module 2 orchestrator (retrieval -> DKT -> DQN -> TAXAL)
with a generic LLM fallback for queries that don't confidently match any
concept in the knowledge base.
"""
from __future__ import annotations

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import ARIA_SYSTEM_PROMPT, tutor_prompt
from modules.tutor import orchestrator as m2_orchestrator
from shared.ner import extract_entities

_OFF_TOPIC_REPLY = (
    "I'm ARIA, your finance assistant -- I focus on personal finance, "
    "investing, markets, and financial literacy. That's outside what I "
    "cover, so I can't really help with it here."
)

_OFF_TOPIC_CLASSIFIER_SYSTEM_PROMPT = (
    "Answer with exactly one word: YES if the following message is about "
    "personal finance, investing, the stock market, taxes, loans, or "
    "financial literacy/education. NO for anything else (science, "
    "geography, coding, general trivia, small talk, etc.), even if you "
    "know the answer."
)


def _is_finance_related(query: str) -> bool:
    """Cheap yes/no LLM gate for queries that reached here with no
    keyword-domain match and no confident concept-KB hit (see
    run_pipeline below).

    Not an embedding-similarity threshold against the concept KB: live
    calibration showed that doesn't separate cleanly at the boundary --
    e.g. "capital of France" scored *higher* (0.271) than the legitimate
    "what is a bond" (0.273 -- barely) and close to the actually-off-topic
    "what is SHM" (0.237), against the 50-concept index. The 50-concept
    KB is too small and narrow to carry that signal; the LLM's own world
    knowledge is what actually distinguishes "REIT" from "simple harmonic
    motion", so ask it directly instead.
    """
    verdict = generate_response(query, system_prompt=_OFF_TOPIC_CLASSIFIER_SYSTEM_PROMPT)
    # Fail open -- a backend error here shouldn't block a real finance
    # question. If the backend is genuinely down, the next
    # generate_response call below will hit the same failure and surface
    # it through the normal "Error:" response path anyway.
    return not verdict.strip().upper().startswith("N")


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

    # No confident concept match in the 50-concept KB. Before falling to
    # the generic LLM prompt -- which can otherwise explain absolutely
    # anything, found live via "what is SHM" getting a physics lecture in
    # ARIA's Insight/Analysis/Recommendation/Risk format -- gate on
    # whether the query is even finance-related at all.
    if not _is_finance_related(query):
        return {"domain": "off_topic", "query": query, "response": _OFF_TOPIC_REPLY}

    context = build_context(query)
    prompt = tutor_prompt(query, context)
    answer = generate_response(prompt, system_prompt=ARIA_SYSTEM_PROMPT)
    return {"domain": "tutor", "query": query, "context": context, "response": answer}


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


class TutorPipeline:
    def run(self, query: str, user_id: str = "default") -> dict[str, Any]:
        return run_pipeline(query, user_id=user_id)
