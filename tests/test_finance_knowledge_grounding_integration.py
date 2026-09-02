"""Confirms the finance/tutor/market pipelines actually thread
shared/finance_knowledge.py's retrieved passages into the LLM prompt for
their generic-fallback paths, not just that the retriever itself works
(see tests/test_finance_knowledge.py for that). Skipped if the
finance_knowledge index isn't built."""
import pytest

from modules.finance.pipeline import run_pipeline as finance_run_pipeline
from modules.market.pipeline import run_pipeline as market_run_pipeline
from modules.tutor.pipeline import run_pipeline as tutor_run_pipeline
from shared.vector_store import index_exists

pytestmark = pytest.mark.skipif(
    not index_exists("finance_knowledge"),
    reason="finance_knowledge index not built; run python -m scripts.build_finance_knowledge_kb",
)


def test_tutor_pipeline_grounds_a_concept_outside_the_50_concept_kb(mock_llm):
    # "REIT" isn't one of Module 2's 50 concepts (modules/tutor/pipeline.py
    # falls through to the generic prompt), but it IS in the broader
    # finance_knowledge KB -- the prompt sent to the LLM should carry the
    # real reference passage, not just the bare query.
    tutor_run_pipeline("what is a REIT")
    assert any("REIT" in call and "REAL ESTATE" in call.upper() for call in mock_llm.calls)


def test_finance_pipeline_grounds_generic_fallback_queries(mock_llm):
    finance_run_pipeline("should I use a REIT instead of buying property directly")
    assert any("REFERENCE PASSAGES" in call for call in mock_llm.calls)


def test_market_pipeline_grounds_mechanics_questions(mock_llm):
    market_run_pipeline("what is a circuit breaker in the stock market")
    assert any("REFERENCE PASSAGES" in call for call in mock_llm.calls)


def test_grounding_is_absent_for_queries_with_no_matching_passage(mock_llm):
    # A query the finance_knowledge KB has nothing relevant for shouldn't
    # get an empty/misleading reference block injected.
    finance_run_pipeline("xyzzy plugh completely made up nonsense query 12345")
    assert not any("REFERENCE PASSAGES" in call for call in mock_llm.calls)
