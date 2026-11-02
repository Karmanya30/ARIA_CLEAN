"""Module 1's long-term financial profile -- what ARIA remembers about the user, keyed by the device-level
owner id the UI sends as `session_id`. Facts come from chat or the form; null = unknown, and a null on POST
deletes that fact."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import Field

from modules.finance.schemas import FinanceProfile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileRequest(FinanceProfile):
    session_id: str = Field(min_length=1, max_length=200)


def _view(owner: str) -> dict[str, Any]:
    from modules.finance import engine
    from shared.user_store import get_financial_profile

    saved = get_financial_profile(owner) or {}
    profile = {k: saved.get(k) for k in FinanceProfile.model_fields}
    return {"profile": profile, "sources": saved.get("sources", {}), "completeness": engine.completeness(profile)}


@router.get("")
def get_profile(session_id: str) -> dict[str, Any]:
    return _view(session_id)


@router.post("")
def save_profile(req: ProfileRequest) -> dict[str, Any]:
    from shared.user_store import save_financial_profile

    save_financial_profile(req.session_id, source="form", **req.model_dump(exclude={"session_id"}, exclude_unset=True))
    return _view(req.session_id)


@router.get("/summary")
def profile_summary(session_id: str) -> dict[str, Any]:
    from modules.finance import anomaly, engine
    from modules.finance.pipeline import _load_transactions
    from shared.user_store import get_financial_profile

    p = {k: v for k, v in (get_financial_profile(session_id) or {}).items() if v is not None}
    flags = len(anomaly.detect_for_user(_load_transactions(session_id))) if p.get("expenses") else 0
    return {"snapshot": engine.snapshot(p), "health": engine.health_score(p, flags), "goals": engine.goals(p),
            "retirement": engine.retirement(p), "tax": engine.tax_compare(p)}


@router.delete("")
def delete_profile(session_id: str) -> dict[str, bool]:
    from core.session import get_session
    from shared.user_store import clear_transactions, delete_financial_profile, delete_style

    delete_financial_profile(session_id)
    delete_style(session_id)
    clear_transactions(session_id)
    get_session(session_id).pop("finance_pending", None)
    return {"deleted": True}


@router.delete("/everything")
def erase_everything(session_id: str) -> dict[str, Any]:
    """Erase all of this user's data: profile, transactions, chats and their turns, saved research reports, learning state,
    conversation style, statement previews and audio tokens. Deleted chats are removed for good, not just hidden."""
    from sqlalchemy import delete, select

    from core.session import get_session
    from shared import user_store as us
    from shared.conversation_memory import Conversation, Turn

    counts: dict[str, int] = {}
    with us._SessionLocal() as db:
        ids = db.scalars(select(Conversation.id).where(Conversation.owner_id == session_id)).all()
        counts["turns"] = db.execute(delete(Turn).where(Turn.conversation_id.in_(ids))).rowcount if ids else 0
        counts["conversations"] = db.execute(delete(Conversation).where(Conversation.owner_id == session_id)).rowcount
        for name, model, col in (("reports", us.ResearchReportRecord, us.ResearchReportRecord.owner_id), ("transactions", us.TransactionRecord, us.TransactionRecord.user_id),
                                 ("style", us.ConversationStyle, us.ConversationStyle.owner_id), ("learning", us.LearningState, us.LearningState.user_id),
                                 ("previews", us.StatementPreviewRecord, us.StatementPreviewRecord.owner_id), ("audio", us.AudioArtifactRecord, us.AudioArtifactRecord.owner_id),
                                 ("profile", us.FinancialProfile, us.FinancialProfile.user_id)):
            counts[name] = db.execute(delete(model).where(col == session_id)).rowcount
        db.commit()
    get_session(session_id).pop("finance_pending", None)
    return {"erased": True, "counts": counts}


@router.delete("/style")
def delete_conversation_style(session_id: str) -> dict[str, bool]:
    """Forget how this user likes ARIA to talk (learned preferences and the recent-feeling tags)."""
    from shared.user_store import delete_style

    delete_style(session_id)
    return {"deleted": True}
