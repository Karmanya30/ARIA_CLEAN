"""shared/finance_knowledge.py -- the Stage 10 grounding retriever over the
broader finance_knowledge FAISS namespace (distinct from Module 2's
50-concept tutor KB). Skipped if the index isn't built -- run
`python -m scripts.build_finance_knowledge_kb` first."""
import pytest

from shared.finance_knowledge import format_passages, grounding_for, retrieve_passages
from shared.vector_store import index_exists

pytestmark = pytest.mark.skipif(
    not index_exists("finance_knowledge"),
    reason="finance_knowledge index not built; run python -m scripts.build_finance_knowledge_kb",
)


def test_direct_topic_query_finds_its_own_entry():
    hits = retrieve_passages("what is a REIT")
    assert hits
    assert hits[0]["id"] == "reit"


def test_off_topic_query_returns_no_passages():
    assert retrieve_passages("capital of France") == []
    assert retrieve_passages("what is simple harmonic motion") == []


def test_concept_already_in_the_tutor_kb_is_not_required_here():
    # finance_knowledge only needs to cover what's NOT in the 50-concept
    # tutor KB -- this just confirms a miss here doesn't error, since
    # empty is a legitimate, expected result (modules/tutor/pipeline.py
    # only reaches this after its own KB already missed).
    assert isinstance(retrieve_passages("some completely made up query xyz123"), list)


def test_format_passages_renders_a_numbered_block():
    hits = retrieve_passages("what is arbitrage")
    text = format_passages(hits)
    assert text.startswith("[1]")
    assert "Arbitrage" in text


def test_format_passages_empty_list_returns_empty_string():
    assert format_passages([]) == ""


def test_grounding_for_is_retrieve_plus_format():
    assert grounding_for("what is a REIT") == format_passages(retrieve_passages("what is a REIT"))
