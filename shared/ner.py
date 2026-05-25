"""Simple keyword and token extraction."""

from dataclasses import dataclass, field
import re


@dataclass
class FinancialEntities:
    tokens: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def extract_entities(text: str) -> dict[str, list[str]]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text.lower())
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    keywords = [
        token
        for token in tokens
        if token in {"stock", "investment", "tax", "trend", "market", "learn", "explain"}
    ]
    return {"tokens": tokens, "numbers": numbers, "keywords": keywords}


def extract_financial_entities(text: str) -> FinancialEntities:
    data = extract_entities(text)
    return FinancialEntities(
        tokens=data["tokens"],
        numbers=data["numbers"],
        keywords=data["keywords"],
    )
