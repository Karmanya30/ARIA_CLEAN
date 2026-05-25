"""In-memory session state for ARIA."""

from typing import Any


_SESSIONS: dict[str, dict[str, Any]] = {}


def save_turn(session_id: str, query: str, response: dict[str, Any]) -> None:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {"history": []}
    
    _SESSIONS[session_id]["history"].append({
        "query": query,
        "response": response,
    })
    
    _SESSIONS[session_id]["last_query"] = query
    _SESSIONS[session_id]["last_response"] = response


def get_session(session_id: str = "default") -> dict[str, Any]:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {"history": []}
    return _SESSIONS[session_id]


def clear_session(session_id: str = "default") -> None:
    _SESSIONS.pop(session_id, None)
