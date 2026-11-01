"""Semantic route classification (Aurelio Labs `semantic-router`, MIT) on ARIA's own sentence encoder.

No new embedding service and no LLM call: the encoder is the Sentence-BERT model ARIA already loads for conversation memory and tutor
retrieval (`shared.vector_store._get_encoder`), so a classification costs one local embedding (milliseconds, no tokens).

`classify()` returns every route's score, not just the winner, because the decision layer needs the margin between the best and the
second route; raw similarity is a ranking signal, not a probability (thresholds are calibrated on the dev split only).
If `semantic-router` is not installed the same routes are scored by a small local cosine fallback so the system degrades, not breaks.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from core.intent.taxonomy import ROUTE_EXAMPLES

_lock = threading.Lock()
_state: dict = {}


@dataclass
class SemanticChoice:
    label: str | None
    score: float = 0.0
    margin: float = 0.0
    ranking: list[tuple[str, float]] = field(default_factory=list)
    engine: str = "none"
    latency_ms: float = 0.0


def _encode(texts: list[str]) -> np.ndarray:
    from shared.vector_store import _get_encoder

    vecs = np.asarray(_get_encoder().encode(list(texts), normalize_embeddings=True), dtype=np.float32)
    return vecs


def _build() -> dict:
    """Router + (for the fallback) an example matrix. Built once, lazily."""
    names = list(ROUTE_EXAMPLES)
    state: dict = {"names": names}
    try:
        from semantic_router import Route
        from semantic_router.encoders import DenseEncoder
        from semantic_router.routers import IndexedRouter

        class AriaEncoder(DenseEncoder):
            name: str = "aria-sbert"
            type: str = "aria"

            def __call__(self, docs):  # type: ignore[override]
                return _encode([str(d) for d in docs]).tolist()

        routes = [Route(name=n, utterances=ROUTE_EXAMPLES[n]) for n in names]
        state["router"] = IndexedRouter(encoder=AriaEncoder(), routes=routes, top_k=12, aggregation="mean")
        state["engine"] = "semantic-router"
    except Exception as exc:  # library missing / incompatible: fall back to the same idea in numpy
        logger.warning(f"semantic-router unavailable ({type(exc).__name__}); using the local cosine fallback")
        state["engine"] = "local-cosine"
    flat = [(n, u) for n in names for u in ROUTE_EXAMPLES[n]]
    state["labels"] = np.array([n for n, _ in flat])
    state["matrix"] = _encode([u for _, u in flat])
    return state


def _scores_local(query: str, state: dict, top_k: int = 5) -> dict[str, float]:
    sims = state["matrix"] @ _encode([query])[0]
    out = {}
    for n in state["names"]:
        s = np.sort(sims[state["labels"] == n])[::-1][:top_k]
        out[n] = float(s.mean())
    return out


def classify(query: str) -> SemanticChoice:
    started = time.perf_counter()
    with _lock:
        if not _state:
            _state.update(_build())
    state = _state
    scores: dict[str, float] = {}
    engine = "local-cosine"
    if state.get("router") is not None:
        try:
            choices = state["router"](query, limit=len(state["names"]), threshold=0.0)
            choices = choices if isinstance(choices, list) else [choices]
            scores = {c.name: float(c.confidence or 0.0) for c in choices if c.name}
            engine = "semantic-router"
        except Exception as exc:
            logger.warning(f"semantic-router call failed ({type(exc).__name__}); using the local scorer for this query")
    if not scores:
        scores = _scores_local(query, state)
    ranking = sorted(scores.items(), key=lambda kv: -kv[1])
    best = ranking[0] if ranking else (None, 0.0)
    second = ranking[1][1] if len(ranking) > 1 else 0.0
    return SemanticChoice(label=best[0], score=best[1], margin=best[1] - second, ranking=ranking, engine=engine,
                          latency_ms=round((time.perf_counter() - started) * 1000, 2))
