"""Security-audit test bootstrap: scratch SQLite DB (tests/conftest.py), provider keys blanked BEFORE import, SMTP host blanked,
non-loopback sockets blocked, mock_llm on every test. No real LLM, no network, no browser, no microphone.
Run from E:\\ARIA:  OMP_NUM_THREADS=2 python -m pytest ARIA_EVALUATION/tests/security -q -p no:cacheprovider"""
import os
import socket

os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["ARIA_SMTP_HOST"] = ""
os.environ["ARIA_WEB_SEARCH"] = "0"

import pytest  # noqa: E402
from tests.conftest import *  # noqa: E402,F401,F403

_real_connect = socket.socket.connect


def _guarded(self, address, *a, **k):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in ("127.0.0.1", "::1", "localhost", "testserver"):
        raise OSError(f"security-audit guard: outbound connection to {host!r} blocked")
    return _real_connect(self, address, *a, **k)


@pytest.fixture(autouse=True)
def _no_network_no_llm(monkeypatch, mock_llm):
    monkeypatch.setattr(socket.socket, "connect", _guarded)
    return mock_llm
