"""api/routes/progress.py's quiz-answer endpoint -- this is what actually
closes the loop between a generated quiz and DKT mastery. The architecture
audit found the old Streamlit UI generated quizzes via a real LLM call
whenever the DQN policy picked "ask_quiz" but never rendered or graded
them, so mastery could never move off its cold-start default for a real
user; this replaces the AppTest-based regression test that used to cover
the Streamlit widget with a direct API-level equivalent."""
from fastapi.testclient import TestClient

from api.main import app
from shared.user_store import (
    LearningState,
    _SessionLocal,
    clear_transactions,
    get_learning_state,
)

client = TestClient(app)
_TEST_SESSION = "__pytest_api_progress__"


def _wipe():
    clear_transactions(_TEST_SESSION)
    with _SessionLocal() as s:
        row = s.get(LearningState, _TEST_SESSION)
        if row is not None:
            s.delete(row)
            s.commit()


def test_answering_a_quiz_moves_mastery_off_cold_start():
    _wipe()
    try:
        resp = client.post(
            "/api/quiz/answer",
            json={"session_id": _TEST_SESSION, "concept_id": "sip", "is_correct": True},
        )

        assert resp.status_code == 200
        mastery = resp.json()["mastery"]
        assert mastery["sip"] > 0.0  # moved off the all-zero cold-start default

        state = get_learning_state(_TEST_SESSION)
        assert state["history"] == [{"concept_id": "sip", "is_correct": True}]
    finally:
        _wipe()


def test_progress_endpoint_reflects_answered_quiz():
    _wipe()
    try:
        client.post(
            "/api/quiz/answer",
            json={"session_id": _TEST_SESSION, "concept_id": "sip", "is_correct": True},
        )

        resp = client.get(f"/api/progress?session_id={_TEST_SESSION}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_interactions"] == 1
        assert any(item["concept_id"] == "sip" for item in body["engaged"])
    finally:
        _wipe()


def test_progress_lists_only_the_concepts_the_learner_was_quizzed_on():
    _wipe()
    try:
        for cid, ok in (("sip", True), ("sip", False), ("inflation", True)):
            client.post("/api/quiz/answer", json={"session_id": _TEST_SESSION, "concept_id": cid, "is_correct": ok})
        got = client.get("/api/progress", params={"session_id": _TEST_SESSION}).json()
        assert {e["concept_id"] for e in got["engaged"]} == {"sip", "inflation"}
        sip = next(e for e in got["engaged"] if e["concept_id"] == "sip")
        assert (sip["answered"], sip["correct"]) == (2, 1) and got["total_interactions"] == 3
    finally:
        _wipe()
