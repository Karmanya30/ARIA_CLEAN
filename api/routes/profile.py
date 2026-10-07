"""Module 1's long-term financial profile -- what ARIA remembers about the user, keyed by the device-level
owner id the UI sends as `session_id`. Facts come from chat or the form; null = unknown, and a null on POST
deletes that fact."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from modules.finance.schemas import FinanceProfile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileRequest(FinanceProfile):
    session_id: str


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
    from shared.user_store import clear_transactions, delete_financial_profile

    delete_financial_profile(session_id)
    clear_transactions(session_id)
    get_session(session_id).pop("finance_pending", None)
    return {"deleted": True}
