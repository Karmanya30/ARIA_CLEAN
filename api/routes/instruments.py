"""Find and open any tradable instrument (stocks, mutual funds, ETFs, crypto, bonds, indices, commodities, currencies) and
ask ARIA about it. Free data only; see modules/market/instruments.py for sources, caches and coverage."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from api.audio_store import register_later
from api.text_utils import speech_text
from modules.market import instrument_chat, instruments

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def _get(iid: str) -> dict:
    try:
        return instruments.resolve(iid)
    except instruments.NotFound as exc:
        raise HTTPException(404, str(exc))


@router.get("/search")
def search(q: str = Query("", max_length=80), type: str = "all", limit: int = Query(20, ge=1, le=50)) -> dict:  # noqa: A002
    try:
        return instruments.search(q, type, limit)
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
    history: list[dict[str, Any]] | None = None


@router.post("/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    from core.session import save_turn

    it = _get(req.id)
    result = instrument_chat.ask(it, req.question.strip(), req.owner_id, req.history)
    save_turn(req.session_id, req.question.strip(), result)

    def make_audio() -> str | None:  # same background TTS as /api/chat; the reply does not wait for it
        try:
            from ai.llm.audio_script import generate_audio_script
            from ai.speech.tts import synthesize

            return synthesize(speech_text(generate_audio_script(result["response"])))
        except Exception as exc:
            logger.warning(f"TTS generation failed; the reply stays text-only: {exc}")
            return None

    result["audio_token"] = register_later(make_audio)
    return result


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
