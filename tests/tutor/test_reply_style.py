"""Reply style: an explanation answers the question and stops. No quiz unless asked, no internal section labels, no empty headings."""
import pytest

from modules.tutor import orchestrator, pipeline
from modules.tutor.pipeline import taxal_text
from modules.tutor.schemas import TaxalExplanation


def _stub(monkeypatch, taxal):
    monkeypatch.setattr(orchestrator.explainer, "explain", lambda *a, **k: TaxalExplanation(level=1, **taxal))
    monkeypatch.setattr(orchestrator.quiz_engine, "generate_quiz", lambda *a, **k: {"question": "?", "correct_answer": "a", "wrong_answers": ["b", "c", "d"], "explanation": "e", "concept_id": "sip"})


@pytest.mark.parametrize("q", ["What is a SIP?", "Explain compound interest", "explain SIP with an example", "what does NAV mean"])
def test_informational_questions_get_no_quiz(monkeypatch, q):
    _stub(monkeypatch, dict(cognitive="A SIP invests a fixed amount regularly.", functional="Each month it buys units.", causal="It averages the price."))
    r = pipeline.run_pipeline(q, user_id="style_u")
    if r.get("concept_id"):
        assert not r["quiz"]
        assert "Submit" not in r["response"] and "Cognitive" not in r["response"]


def test_quiz_still_works_when_asked(monkeypatch):
    _stub(monkeypatch, dict(cognitive="x", functional="y", causal="z"))
    assert pipeline.is_quiz_request("Quiz me on SIP")
    assert orchestrator.handle("style_u", "SIP", force_quiz=True)["quiz"]


def test_text_has_no_labels_markers_or_empty_sections():
    t = taxal_text({"cognitive": "**Cognitive:** a", "functional": "  ", "causal": "Causal: b **c**"})
    assert t == "a\n\nb c"
    assert taxal_text({}) == ""
