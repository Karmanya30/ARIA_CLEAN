"""Mock knowledge-state helper."""

from typing import Any


class KnowledgeModel:
    def predict(self, seq: list[Any]) -> dict[str, Any]:
        return {
            "level": "beginner",
            "confidence": 0.6,
            "items_seen": len(seq),
        }
