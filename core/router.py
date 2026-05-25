"""Keyword router for ARIA domains."""

from shared.intent_classifier import classify_intent


def route_query(query: str) -> str:
    """Return the module name that should handle the query."""
    return classify_intent(query)


def route(query: str) -> str:
    """Backward-compatible alias for older call sites."""
    return route_query(query)
