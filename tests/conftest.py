"""Shared pytest fixtures. Unit tests never hit a real LLM API -- see
mock_llm below, which patches every module that imported
`generate_response` by value (Python binds a local reference on
`from x import y`, so the source module alone isn't enough to patch)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Set before API/store imports: even legacy tests with fixed owner IDs must
# never open the application's configured database. Keep fixtures/KB readable.
_test_storage = tempfile.TemporaryDirectory(prefix="aria-pytest-", ignore_cleanup_errors=True)
os.environ["DB_URL"] = "sqlite:///" + (Path(_test_storage.name) / "regression.db").as_posix()
os.environ["ARIA_EXPENSIVE_REQUESTS_PER_MINUTE"] = "0"  # isolated limit tests supply their own rate
os.environ["ARIA_AUTH_MODE"] = "private"  # account tests explicitly opt in; ignore deployment mode

os.environ.setdefault("ARIA_INTENT_RESOLVER", "0")  # intent tests opt in explicitly; no live calls in regressions
os.environ.setdefault("ARIA_MEMORY_SEMANTIC", "0")  # no embedding model loads unless a test opts in
os.environ.setdefault("ARIA_WARMUP", "0")  # no model loading in the API's startup hook during tests
os.environ.setdefault("ARIA_SENTIMENT", "0")  # tests never load FinBERT unless a test opts in
os.environ.setdefault("ARIA_FORECAST", "0")  # tests never run the forecast engine unless a test opts in
os.environ.setdefault("ARIA_SCENARIO_BACKTEST", "0")  # tests never queue the scenario backtest unless a test opts in
os.environ.setdefault("FI_NEWS_RSS", "0")  # tests never call live news feeds (tests/test_news.py turns them on with canned XML)

# Every module found (via grep) doing `from ai.llm.groq_client import
# generate_response` -- each needs its own patch target.
_IMPORTERS = [
    "core.orchestrator",
    "modules.equity_research.financial_pipeline",
    "modules.equity_research.intelligence.agents",
    "modules.equity_research.investment",
    "modules.finance.orchestrator",
    "modules.finance.pipeline",
    "modules.market.pipeline",
    "modules.tutor.explainer",
    "modules.tutor.pipeline",
    "modules.tutor.quiz",
]

DEFAULT_MOCK_RESPONSE = "Insight: mock.\nAnalysis: mock.\nRecommendation: mock.\nRisk: mock."


class _MockLLM:
    def __init__(self):
        self.response = DEFAULT_MOCK_RESPONSE
        self.calls: list[str] = []
        self.models: list[str | None] = []

    def __call__(self, prompt, system_prompt=None, model=None, groq_model=None):
        self.calls.append(prompt)
        self.models.append(model)
        return self.response

    def set_response(self, text: str) -> None:
        self.response = text


@pytest.fixture
def mock_llm(monkeypatch):
    """Patches generate_response everywhere it's imported. Use
    `mock_llm.set_response("...")` to control what the "LLM" says, and
    `mock_llm.calls` to inspect what prompts were sent to it."""
    import ai.llm.groq_client as groq_client

    fake = _MockLLM()
    monkeypatch.setattr(groq_client, "generate_response", fake)
    monkeypatch.setattr(groq_client, "generate_structured", lambda *args, **kwargs: None)

    for module_path in _IMPORTERS:
        try:
            module = __import__(module_path, fromlist=["generate_response"])
        except ImportError:
            continue
        if hasattr(module, "generate_response"):
            monkeypatch.setattr(module, "generate_response", fake)

    return fake
