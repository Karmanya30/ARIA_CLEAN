"""Durable conversation history with a compatibility cache for module state."""
from contextlib import contextmanager
from threading import RLock
from typing import Any
from shared import conversation_memory as memory

_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCKS: dict[str, RLock] = {}
_LOCK_GUARD = RLock()

@contextmanager
def session_lock(session_id: str):
    with _LOCK_GUARD:
        lock = _LOCKS.setdefault(session_id, RLock())
    with lock:
        yield

def save_turn(session_id: str, query: str, response: dict[str, Any]) -> None:
    with session_lock(session_id):
        state = get_session(session_id)
        # The outer request commits completion only after all response work succeeds.
        if memory.active_request.get() is not None:
            memory.active_request.get()["result"] = response
            memory.snapshot(memory.active_request.get(), response)
        else:
            memory.complete(session_id, query, response)
            state.update(memory.load(session_id))
        memory.checkpoint(session_id, state)

def get_session(session_id: str = "default") -> dict[str, Any]:
    memory.conversation(session_id)
    with session_lock(session_id):
        if session_id not in _SESSIONS:
            _SESSIONS[session_id] = memory.load(session_id)
        return _SESSIONS[session_id]

def clear_session(session_id: str = "default") -> None:
    with session_lock(session_id):
        memory.clear(session_id)
        _SESSIONS.pop(session_id, None)

def execute_turn(session_id: str, query: str, action, request_id: str | None = None):
    """Archive input before work, replay successful retries, checkpoint on exit."""
    if memory.active_request.get() is not None and memory.active_request.get()["session_id"] == session_id:
        return action()
    with session_lock(session_id):
        request = memory.begin(session_id, query, request_id)
        if request["status"] == "complete":
            return request["response"]
        restored = memory.load(session_id)
        cached = _SESSIONS.get(session_id, {})
        restored.update({k: v for k, v in cached.items() if k not in ("history", "last_query", "last_response")})
        _SESSIONS[session_id] = restored
        token = memory.active_request.set(request)
        try:
            with memory.context_for(session_id, query):
                result = action()
            memory.complete(session_id, query, result)
            memory.checkpoint(session_id, get_session(session_id))
            _SESSIONS[session_id].update(memory.load(session_id))
            return result
        except BaseException:
            memory.fail(request)
            raise
        finally:
            memory.active_request.reset(token)
