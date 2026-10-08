"""
Concept retriever — Sentence-BERT + FAISS semantic search over the
50-concept knowledge base (data/raw/concepts_kb/concepts.json), gated by
a confidence threshold so a low-similarity query triggers a clarifying
question instead of a hallucinated concept match.

Build the index first: python -m scripts.build_concept_kb
"""
from __future__ import annotations

import re

from config.settings import RETRIEVAL_K, RETRIEVAL_THRESHOLD
from shared import vector_store

NAMESPACE = "concepts"


def retrieve(query: str, k: int = RETRIEVAL_K) -> list[dict]:
    return vector_store.search(NAMESPACE, query, k=k)


def best(query: str, threshold: float = RETRIEVAL_THRESHOLD) -> dict | None:
    """Top concept match, or None if it's below the confidence threshold."""
    hits = retrieve(query, k=1)
    if hits and hits[0]["score"] >= threshold and (hits[0]["score"] >= _SURE or _names_every_term(query, hits[0])):
        return hits[0]
    return None


_SURE = 0.6  # below this a nearest-neighbour match must also share the query's own words ("expense ratio" is not the P/E ratio)
_FILLER = {"what", "whats", "is", "an", "a", "the", "are", "explain", "define", "meaning", "of", "how", "does", "do", "to", "me", "tell", "about"}


def _names_every_term(query: str, hit: dict) -> bool:
    names = " ".join([hit.get("canonical_name", ""), hit.get("id", ""), *hit.get("aliases", [])]).lower().replace("_", " ")
    return all(w[:4] in names for w in re.findall(r"[a-z]+", query.lower()) if w not in _FILLER)


class Retriever:
    """Thin OO wrapper matching the original stub's calling convention."""

    def retrieve(self, query: str) -> list[dict]:
        return retrieve(query)
