"""TAXAL explanation generator — wraps build_taxal_prompt (Cognitive /
Functional / Causal) and parses the LLM's structured response."""
from __future__ import annotations

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import build_taxal_prompt
from modules.finance import personal
from modules.tutor.schemas import TaxalExplanation

_TAGS = ["COGNITIVE:", "FUNCTIONAL:", "CAUSAL:"]


def _section(text: str, tag: str) -> str:
    if tag not in text:
        return ""
    rest = text.split(tag, 1)[1]
    for other in _TAGS:
        if other != tag and other in rest:
            rest = rest.split(other, 1)[0]
    return rest.strip()


def _parse_taxal(text: str, level: int) -> TaxalExplanation:
    return TaxalExplanation(
        cognitive=_section(text, "COGNITIVE:"),
        functional=_section(text, "FUNCTIONAL:"),
        causal=_section(text, "CAUSAL:"),
        level=level,
    )


def explain(concept_name: str, level: int, action: str | None = None) -> TaxalExplanation:
    prompt = build_taxal_prompt(concept_name, level, action=action, learner=personal.learner_context(personal.profile()))
    text = generate_response(prompt)
    return _parse_taxal(text, level)
