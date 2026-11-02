"""Reuse the repository's own test bootstrap (scratch SQLite DB, private auth mode, rate limit off, model flags off, mock_llm).
Run from the repo root:
  python -m pytest ARIA_EVALUATION/tests/api ARIA_EVALUATION/tests/workflow -q -p no:cacheprovider
Safety: provider keys are blanked BEFORE the app is imported (load_dotenv does not override existing variables), every test runs
with the repo's mock_llm, and any socket connect to a non-loopback address raises. No real LLM, no network."""
import os
import socket

os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["ARIA_SMTP_HOST"] = ""  # .env may configure real SMTP; the feedback route must never send mail from a test

import pytest  # noqa: E402
from tests.conftest import *  # noqa: E402,F401,F403  (sets DB_URL etc. at import time; exposes mock_llm)

_real_connect = socket.socket.connect


def _guarded(self, address, *a, **k):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in ("127.0.0.1", "::1", "localhost", "testserver"):
        raise OSError(f"QA guard: outbound connection to {host!r} blocked")
    return _real_connect(self, address, *a, **k)


@pytest.fixture(autouse=True)
def _no_network_no_llm(monkeypatch, mock_llm):
    monkeypatch.setattr(socket.socket, "connect", _guarded)
    return mock_llm
