"""Tutor pipeline: context + prompt + Groq response."""

from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import tutor_prompt
from modules.tutor.knowledge import KnowledgeModel
from modules.tutor.retriever import Retriever
from modules.tutor.teaching import TeachingAgent


def build_context(query: str) -> dict[str, Any]:
    docs = Retriever().retrieve(query)
    lesson = TeachingAgent().teach(docs)
    knowledge = KnowledgeModel().predict(docs)
    return {
        "docs": docs,
        "lesson": lesson,
        "knowledge": knowledge,
    }


def build_prompt(query: str, context: dict[str, Any] | None = None) -> str:
    return tutor_prompt(query, context or build_context(query))


def run_pipeline(query: str) -> dict[str, Any]:
    context = build_context(query)
    prompt = build_prompt(query, context)
    answer = generate_response(prompt)
    return {
        "domain": "tutor",
        "query": query,
        "context": context,
        "response": answer,
    }


class TutorPipeline:
    def run(self, query: str) -> dict[str, Any]:
        return run_pipeline(query)
