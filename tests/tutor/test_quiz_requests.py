"""A learner can ask to be quizzed, and a first explanation of a concept always comes with a quiz (otherwise the policy never
picks one for a cold-start learner and the Progress page stays empty)."""
from modules.tutor import orchestrator, pipeline


def test_quiz_request_detection():
    for q in ("Quiz me on this", "quiz me on SIP", "Test my knowledge of compound interest", "give me a practice question"):
        assert pipeline.is_quiz_request(q)
    assert not pipeline.is_quiz_request("What is a SIP?")


def test_first_explanation_carries_a_quiz_and_a_quiz_request_without_a_name_reuses_the_last_concept(monkeypatch):
    concept = {"id": "sip", "canonical_name": "SIP", "prerequisites": []}
    monkeypatch.setattr(orchestrator.retriever, "best", lambda q: concept if "sip" in q.lower() else None)
    monkeypatch.setattr(orchestrator.user_store, "get_learning_state", lambda u: {"history": [], "mastery": {}})
    monkeypatch.setattr(orchestrator.teaching, "choose_action", lambda **k: "give_example")
    monkeypatch.setattr(orchestrator.explainer, "explain", lambda *a, **k: {"cognitive": "c", "functional": "f", "causal": "k", "level": 1})
    monkeypatch.setattr(orchestrator.quiz_engine, "generate_quiz", lambda *a, **k: {"question": "?", "correct_answer": "a", "wrong_answers": ["b", "c", "d"], "explanation": "e", "concept_id": "sip"})
    monkeypatch.setattr(orchestrator, "concept_by_id", lambda cid: concept if cid == "sip" else None)
    assert orchestrator.handle("u", "Explain SIP")["quiz"]
    assert orchestrator.handle("u", " on this", force_quiz=True, fallback_concept_id="sip")["concept_id"] == "sip"
    assert orchestrator.handle("u", " on this", force_quiz=True) is None
