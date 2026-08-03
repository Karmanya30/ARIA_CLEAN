"""TAXAL explanation generator -- LLM mocked, never hits a real API."""
from modules.tutor.explainer import _parse_taxal, explain


def test_parse_taxal_all_three_sections():
    text = (
        "COGNITIVE:\nA definition.\n\n"
        "FUNCTIONAL:\nA usage example.\n\n"
        "CAUSAL:\nWhy it happens."
    )
    result = _parse_taxal(text, level=2)
    assert result.cognitive == "A definition."
    assert result.functional == "A usage example."
    assert result.causal == "Why it happens."
    assert result.level == 2


def test_parse_taxal_malformed_output_returns_empty_sections_not_crash():
    result = _parse_taxal("Sorry, I can't help with that.", level=1)
    assert result.cognitive == ""
    assert result.functional == ""
    assert result.causal == ""


def test_explain_uses_mocked_llm(mock_llm):
    mock_llm.set_response("COGNITIVE:\nDef.\n\nFUNCTIONAL:\nUse.\n\nCAUSAL:\nWhy.")
    result = explain("Compound Interest", level=3, action="give_example")
    assert result.cognitive == "Def."
    assert len(mock_llm.calls) == 1
    assert "Compound Interest" in mock_llm.calls[0]
