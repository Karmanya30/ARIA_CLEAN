"""Find and open any tradable instrument (stocks, mutual funds, ETFs, crypto, bonds, indices, commodities, currencies) and
ask ARIA about it. Free data only; see modules/market/instruments.py for sources, caches and coverage."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from modules.market import instruments
from modules.qa.models import Channel, ChatMode, QAContext, QARequest

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def _get(iid: str) -> dict:
    try:
        return instruments.resolve(iid)
    except instruments.NotFound as exc:
        raise HTTPException(404, str(exc))


@router.get("/search")
def search(q: str = Query("", max_length=80), type: str = "all", limit: int = Query(20, ge=1, le=50), market: str = "all") -> dict:  # noqa: A002
    try:
        return instruments.search(q, type, limit, market)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/browse")
def browse(type: str = "stock", q: str = Query("", max_length=80), sort: str = "", page: int = Query(1, ge=1),  # noqa: A002
           page_size: int = Query(50, ge=1, le=200), amc: str = "", category: str = "", plan: str = "", option: str = "",
           prices: bool = True) -> dict:
    try:
        return instruments.browse(type, q, sort, page, page_size, amc, category, plan, option, prices)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class AskRequest(BaseModel):
    id: str
    question: str = Field(min_length=1, max_length=1500)
    session_id: str
    owner_id: str | None = None
    request_id: str | None = None
    mode: str = ChatMode.NORMAL.value
    history: list[dict[str, Any]] | None = Field(None, max_length=20)


@router.post("/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    """Thin adapter: the same answer pipeline as /api/chat, with this instrument as the page in focus."""
    from api.routes.chat import answer_http

    return answer_http(QARequest(query=req.question, session_id=req.session_id, owner_id=req.owner_id, request_id=req.request_id,
                                 mode=ChatMode.parse(req.mode), channel=Channel.INSTRUMENT,
                                 context=QAContext(instrument_id=req.id, page="explore"), history=req.history))


@router.get("/{instrument_id}/quote")
def quote(instrument_id: str) -> dict:
    return instruments.quote(_get(instrument_id))


@router.get("/{instrument_id}/chart")
def chart(instrument_id: str, range: str = "1y") -> dict:  # noqa: A002
    try:
        return instruments.chart(_get(instrument_id), range)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/{instrument_id}/profile")
def profile(instrument_id: str) -> dict:
    return instruments.profile(_get(instrument_id))


@router.get("/{instrument_id}/sip")
def sip(instrument_id: str, monthly: float = Query(5000, ge=100, le=10_000_000), years: float = Query(5, ge=1, le=30)) -> dict:
    try:
        return instruments.sip(_get(instrument_id), monthly, years)
    except instruments.Unsupported as exc:
        raise HTTPException(422, str(exc))
    except instruments.NoData as exc:
        raise HTTPException(503, f"History unavailable: {exc}")
