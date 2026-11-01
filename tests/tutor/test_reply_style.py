"""Reply style: an explanation answers the question and stops. No quiz unless asked, no internal section labels, no empty headings."""
import pytest

from modules.tutor import orchestrator, pipeline
from modules.tutor.pipeline import taxal_text
from modules.tutor.schemas import TaxalExplanation


def _stub(monkeypatch, taxal):
    """A concept is always found and the teaching policy always votes for a quiz: the answer must still carry none."""
    concept = {"id": "sip", "canonical_name": "SIP", "prerequisites": []}
    monkeypatch.setattr(orchestrator.retriever, "best", lambda q: concept)
    monkeypatch.setattr(orchestrator, "concept_by_id", lambda cid: concept)
    monkeypatch.setattr(orchestrator.user_store, "get_learning_state", lambda u: {"history": [], "mastery": {}})
    monkeypatch.setattr(orchestrator.teaching, "choose_action", lambda **k: "ask_quiz")
    monkeypatch.setattr(orchestrator.explainer, "explain", lambda *a, **k: TaxalExplanation(level=1, **taxal))
    monkeypatch.setattr(orchestrator.quiz_engine, "generate_quiz", lambda *a, **k: {"question": "?", "correct_answer": "a", "wrong_answers": ["b", "c", "d"], "explanation": "e", "concept_id": "sip"})


@pytest.mark.parametrize("q", ["What is a SIP?", "Explain compound interest", "explain SIP with an example", "what does NAV mean"])
def test_informational_questions_get_no_quiz(monkeypatch, q):
    _stub(monkeypatch, dict(cognitive="**Cognitive:** A SIP invests a fixed amount regularly.", functional="Each month it buys units.", causal=""))
    r = pipeline.run_pipeline(q, user_id="style_u")
    assert r["concept_id"] == "sip" and not r["quiz"]
    assert "Submit" not in r["response"] and "Cognitive" not in r["response"] and "**" not in r["response"]
    assert r["response"] == "A SIP invests a fixed amount regularly." + chr(10) * 2 + "Each month it buys units."


def test_quiz_when_asked(monkeypatch):
    _stub(monkeypatch, dict(cognitive="x", functional="y", causal="z"))
    r = pipeline.run_pipeline("Quiz me on SIP", user_id="style_u")
    assert r["quiz"] and "quick question" in r["response"]


def test_text_has_no_labels_markers_or_empty_sections():
    t = taxal_text({"cognitive": "**Cognitive:** a", "functional": "  ", "causal": "Causal: b **c**"})
    assert t == "a\n\nb c"
    assert taxal_text({}) == ""
