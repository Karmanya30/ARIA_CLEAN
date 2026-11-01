"""Strict schema for the structured query understanding (variants D and E). Anything that does not validate is discarded and the
system falls back to its deterministic route; model output is never trusted as-is."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["finance", "tutor", "market", "equity_research", "company_intelligence", "data_lookup", "general", "smalltalk", "clarify"]


class SubQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=600)  # self-contained: no pronoun that needs the conversation
    intent: Intent


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["company", "ticker", "fund", "index", "commodity", "crypto", "sector", "metric", "amount", "date_range", "currency", "portfolio", "benchmark", "other"]
    value: str = Field(min_length=1, max_length=120)


class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: float = Field(ge=0, le=1)
    entity_extraction: float = Field(ge=0, le=1)
    context_resolution: float = Field(ge=0, le=1)


class QueryUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    primary_intent: Intent
    secondary_intents: list[Intent] = Field(max_length=4)
    objective: str = Field(max_length=300)
    standalone_query: str = Field(min_length=1, max_length=1600)
    entities: list[Entity] = Field(max_length=12)
    required_capabilities: list[str] = Field(max_length=6)
    sub_queries: list[SubQuery] = Field(max_length=4)
    context_references: list[str] = Field(max_length=4)
    missing_information: list[str] = Field(max_length=4)
    ambiguities: list[str] = Field(max_length=4)
    requires_clarification: bool
    clarification_question: str = Field(max_length=240)
    confidence: Confidence


def provider_schema() -> dict:
    """Flat schema for providers that reject length/size keywords; the same limits are enforced locally by validation."""
    schema = QueryUnderstanding.model_json_schema()

    def scrub(node):
        if isinstance(node, dict):
            for key in ("maxLength", "minLength", "maxItems", "minimum", "maximum", "title", "default"):
                node.pop(key, None)
            for v in node.values():
                scrub(v)
        elif isinstance(node, list):
            for v in node:
                scrub(v)
    scrub(schema)
    return schema
