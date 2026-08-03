"""Concept retriever. Skipped if the FAISS index isn't built -- run
`python -m scripts.build_concept_kb` first."""
import pytest

from shared.vector_store import index_exists
from modules.tutor.retriever import best

pytestmark = pytest.mark.skipif(
    not index_exists("concepts"),
    reason="Concept index not built; run python -m scripts.build_concept_kb",
)


def test_well_formed_query_matches():
    result = best("What is compound interest?")
    assert result is not None
    assert result["id"] == "compound_interest"


def test_off_topic_query_returns_none():
    assert best("what's the weather in Chennai?") is None


def test_unrelated_finance_jargon_not_in_kb_returns_none():
    assert best("what is a CDO?") is None
