"""Module 2's learning progress -- per-concept mastery + interaction
history, plus quiz-answer grading (the loop that actually moves DKT
mastery off its cold-start default; see modules/tutor/orchestrator.py)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["progress"])


class QuizAnswerRequest(BaseModel):
    session_id: str
    concept_id: str
    is_correct: bool


@router.get("/progress")
def get_progress(session_id: str) -> dict[str, Any]:
    from config.paths import CONCEPTS_KB_FILE
    from shared.user_store import get_learning_state

    state = get_learning_state(session_id)
    concepts = json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8"))
    names = {c["id"]: c["canonical_name"] for c in concepts}

    engaged = sorted(
        (
            {"concept_id": cid, "name": names.get(cid, cid), "mastery": score}
            for cid, score in state.get("mastery", {}).items()
            if score > 0
        ),
        key=lambda item: item["mastery"],
        reverse=True,
    )
    return {"engaged": engaged, "total_interactions": len(state.get("history", []))}


@router.post("/quiz/answer")
def answer_quiz(req: QuizAnswerRequest) -> dict[str, Any]:
    from modules.tutor.orchestrator import record_answer

    mastery = record_answer(req.session_id, req.concept_id, req.is_correct)
    return {"mastery": mastery}
