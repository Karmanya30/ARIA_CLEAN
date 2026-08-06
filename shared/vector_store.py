"""
Namespaced FAISS + Sentence-BERT vector store.

Used by Module 2's concept retrieval (namespace "concepts"); the namespace
design lets other modules reuse this for their own semantic search later
without stepping on each other's index files.
"""
from __future__ import annotations

import json

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config.paths import VECTOR_STORE_DIR
from config.settings import SBERT_DEVICE, SBERT_MODEL

_encoder: SentenceTransformer | None = None


def _get_encoder() -> SentenceTransformer:
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer(SBERT_MODEL, device=SBERT_DEVICE)
    return _encoder


def _namespace_dir(namespace: str):
    return VECTOR_STORE_DIR / namespace


def build_index(namespace: str, texts: list[str], metadata: list[dict]) -> None:
    """Build and persist a FAISS index + metadata JSON for `namespace`."""
    if len(texts) != len(metadata):
        raise ValueError("texts and metadata must be the same length")
    if not texts:
        raise ValueError("texts must not be empty")

    vectors = _get_encoder().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    index = faiss.IndexFlatIP(vectors.shape[1])  # inner product == cosine on normalized vectors
    index.add(vectors.astype(np.float32))

    ns_dir = _namespace_dir(namespace)
    ns_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(ns_dir / "index.faiss"))
    (ns_dir / "meta.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")


def index_exists(namespace: str) -> bool:
    ns_dir = _namespace_dir(namespace)
    return (ns_dir / "index.faiss").exists() and (ns_dir / "meta.json").exists()


def search(namespace: str, query: str, k: int = 5) -> list[dict]:
    """Up to `k` metadata dicts for `namespace`, most similar first, each
    with an added "score" key (cosine similarity via normalized inner
    product, roughly -1..1)."""
    if not index_exists(namespace):
        raise FileNotFoundError(
            f"No vector index for namespace '{namespace}'. Build it first, "
            "e.g. python -m scripts.build_concept_kb"
        )
    ns_dir = _namespace_dir(namespace)
    index = faiss.read_index(str(ns_dir / "index.faiss"))
    metadata = json.loads((ns_dir / "meta.json").read_text(encoding="utf-8"))

    query_vec = _get_encoder().encode([query], normalize_embeddings=True, convert_to_numpy=True)
    scores, ids = index.search(query_vec.astype(np.float32), min(k, index.ntotal))

    results = []
    for score, idx in zip(scores[0], ids[0]):
        if idx == -1:
            continue
        results.append({**metadata[idx], "score": float(score)})
    return results


class VectorStore:
    """Thin OO wrapper for callers that prefer object style."""

    def __init__(self, namespace: str):
        self.namespace = namespace

    def build(self, texts: list[str], metadata: list[dict]) -> None:
        build_index(self.namespace, texts, metadata)

    def search(self, query: str, k: int = 5) -> list[dict]:
        return search(self.namespace, query, k=k)
