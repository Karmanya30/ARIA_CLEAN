"""Data contracts for Module 2 — Intelligent Financial Tutor."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Concept(BaseModel):
    id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    category: str
    prerequisites: list[str] = Field(default_factory=list)
    difficulty_floor: int = 1
    difficulty_ceiling: int = 8
    keywords: list[str] = Field(default_factory=list)
    seed_definition: str
    related_concepts: list[str] = Field(default_factory=list)


class TaxalExplanation(BaseModel):
    cognitive: str
    functional: str
    causal: str
    level: int


class QuizItem(BaseModel):
    question: str
    correct_answer: str
    wrong_answers: list[str]
    explanation: str
    concept_id: str


class TutorResponse(BaseModel):
    concept_id: str
    concept_name: str
    level: int
    action: str
    mastery: float
    taxal: TaxalExplanation
    quiz: QuizItem | None = None
