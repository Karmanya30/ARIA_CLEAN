"""
Concept retriever — Sentence-BERT + FAISS semantic search over the
50-concept knowledge base (data/raw/concepts_kb/concepts.json), gated by
a confidence threshold so a low-similarity query triggers a clarifying
question instead of a hallucinated concept match.

Build the index first: python -m scripts.build_concept_kb
"""
from __future__ import annotations

from config.settings import RETRIEVAL_K, RETRIEVAL_THRESHOLD
from shared import vector_store

NAMESPACE = "concepts"


def retrieve(query: str, k: int = RETRIEVAL_K) -> list[dict]:
    return vector_store.search(NAMESPACE, query, k=k)


def best(query: str, threshold: float = RETRIEVAL_THRESHOLD) -> dict | None:
    """Top concept match, or None if it's below the confidence threshold."""
    hits = retrieve(query, k=1)
    if hits and hits[0]["score"] >= threshold:
        return hits[0]
    return None


class Retriever:
    """Thin OO wrapper matching the original stub's calling convention."""

    def retrieve(self, query: str) -> list[dict]:
        return retrieve(query)
