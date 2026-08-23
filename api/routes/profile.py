"""Module 1's financial profile -- direct wrapper around shared/user_store.py,
same fields the old Profile tab's form collected."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileRequest(BaseModel):
    session_id: str
    monthly_income: float
    age: int = 30
    dependents: int = 0
    existing_emi: float = 0.0
    emergency_fund_months: float = 0.0
    city_tier: int = 1
    tax_regime: str = "new"


@router.get("")
def get_profile(session_id: str) -> dict[str, Any] | None:
    from shared.user_store import get_financial_profile

    return get_financial_profile(session_id)


@router.post("")
def save_profile(req: ProfileRequest) -> dict[str, str]:
    from shared.user_store import save_financial_profile

    fields = req.model_dump(exclude={"session_id"})
    save_financial_profile(req.session_id, **fields)
    return {"status": "saved"}
