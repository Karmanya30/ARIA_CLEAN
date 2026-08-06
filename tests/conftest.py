"""Shared pytest fixtures. Unit tests never hit a real LLM API -- see
mock_llm below, which patches every module that imported
`generate_response` by value (Python binds a local reference on
`from x import y`, so the source module alone isn't enough to patch)."""
from __future__ import annotations

import pytest

# Every module found (via grep) doing `from ai.llm.groq_client import
# generate_response` -- each needs its own patch target.
_IMPORTERS = [
    "core.orchestrator",
    "modules.equity_research.financial_pipeline",
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

    def __call__(self, prompt, system_prompt=None):
        self.calls.append(prompt)
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

    for module_path in _IMPORTERS:
        try:
            module = __import__(module_path, fromlist=["generate_response"])
        except ImportError:
            continue
        if hasattr(module, "generate_response"):
            monkeypatch.setattr(module, "generate_response", fake)

    return fake
