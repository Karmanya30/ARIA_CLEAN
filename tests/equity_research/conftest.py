"""Keep the research tests off the real SQLite database: report persistence is stubbed by default.
Tests that exercise storage do so explicitly (test_intel_store_api.py) with their own owner ids
and clean up after themselves."""
import pytest

from modules.equity_research.intelligence import agents, pipeline


@pytest.fixture(autouse=True)
def _no_report_persistence(monkeypatch):
    monkeypatch.setattr(pipeline, "_persist", lambda user_id, report: None)
    agents.clear_llm_cache()
