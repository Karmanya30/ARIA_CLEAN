"""
shared/finance_knowledge.py

Retriever over the Stage 10 "finance_knowledge" FAISS namespace -- broader
general finance-topic grounding than Module 2's 50-concept tutor KB
(modules/tutor/retriever.py). Grounds finance_prompt/tutor_prompt/
market_prompt's generic LLM fallback in real reference content instead of
raw model recall, the same discipline modules/equity_research/*.py already
applies with real scraped/live data (screener_data_prompt).

Build the index first: python -m scripts.build_finance_knowledge_kb
"""
from __future__ import annotations

from config.settings import FINANCE_KNOWLEDGE_RETRIEVAL_K, FINANCE_KNOWLEDGE_RETRIEVAL_THRESHOLD
from shared import vector_store

NAMESPACE = "finance_knowledge"


def retrieve_passages(
    query: str,
    k: int = FINANCE_KNOWLEDGE_RETRIEVAL_K,
    threshold: float = FINANCE_KNOWLEDGE_RETRIEVAL_THRESHOLD,
) -> list[dict]:
    """Up to `k` grounding passages above `threshold`, most similar first.

    Returns an empty list -- not an error -- if the index isn't built yet
    or nothing scores high enough. Callers should treat an empty result as
    "no grounded content available for this query", not block on it: this
    namespace covers ~30 curated topics, nowhere near exhaustive, so a miss
    here doesn't mean the query is off-topic (that's shared/intent_
    classifier.py and modules/tutor/pipeline.py's off-topic gate's job).
    """
    if not vector_store.index_exists(NAMESPACE):
        return []
    hits = vector_store.search(NAMESPACE, query, k=k)
    return [hit for hit in hits if hit["score"] >= threshold]


def format_passages(passages: list[dict]) -> str:
    """Render retrieved passages as a numbered reference block for
    injection into a prompt. Empty string if there's nothing to show, so
    callers can safely embed the result without a special empty-case
    branch in the prompt template itself."""
    if not passages:
        return ""
    lines = [f"[{i}] {p['title']}: {p['content']}" for i, p in enumerate(passages, 1)]
    return "\n".join(lines)


def grounding_for(query: str) -> str:
    """Convenience wrapper: retrieve + format in one call."""
    return format_passages(retrieve_passages(query))
