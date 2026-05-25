"""Dummy vector-store interface."""

from typing import Any

_MEMORY: list[dict[str, Any]] = []


def store(item: Any, metadata: dict[str, Any] | None = None) -> bool:
    _MEMORY.append({"item": item, "metadata": metadata or {}})
    return True


def retrieve(query: str, k: int = 5) -> list[dict[str, Any]]:
    return _MEMORY[:k] if query else []


class VectorStore:
    def add(self, vectors: Any, metas: list[dict[str, Any]] | None = None) -> bool:
        store(vectors, {"metas": metas or []})
        return True

    def search(self, qvec: Any, k: int = 5) -> list[dict[str, Any]]:
        return retrieve(str(qvec), k=k)
