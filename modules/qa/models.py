"""Typed request/response of the one ARIA answer pipeline (modules/qa/pipeline.py)."""
from __future__ import annotations

from contextvars import ContextVar
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatMode(StrEnum):
    """The six chat modes (the strings are what the front end sends). A mode only changes PRESENTATION."""

    NORMAL = "Normal Mode"
    CONVERSATIONAL = "Conversational Mode"
    LIVE = "Live Avatar (Free)"
    TAVUS = "Tavus CVI Mode (WebRTC)"
    LOCAL = "Local Avatar (Live Face)"
    LIVETALKING = "LiveTalking Avatar (Local)"

    @classmethod
    def parse(cls, value: str | None) -> "ChatMode":
        """Unknown strings (older clients sent "Live Avatar") fall back to Normal Mode rather than failing."""
        for m in cls:
            if value in (m.value, m.name):
                return m
        return cls.LIVE if value == "Live Avatar" else cls.NORMAL

    @property
    def speaks(self) -> bool:
        """The server itself produces a short spoken rewrite (the avatar reads it aloud)."""
        return self in (ChatMode.LIVE, ChatMode.TAVUS, ChatMode.LIVETALKING)


class Channel(StrEnum):
    """Where the question came from. Never changes the answer logic, only which context is attached."""

    CHAT = "chat"
    VOICE = "voice"
    AVATAR = "avatar"
    INSTRUMENT = "instrument"
    REPORT = "report"
    MARKET_CHIP = "market_chip"


class QAContext(BaseModel):
    """What the user is looking at when they ask."""

    instrument_id: str | None = None  # Explore drawer
    company: str | None = None  # company intelligence / report page
    report_id: str | None = None
    page: str | None = None
    headline: str | None = Field(None, max_length=16000)  # market chip: the news item being asked about (untrusted text)


class QARequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    session_id: str = Field(min_length=1, max_length=200)
    owner_id: str | None = None
    request_id: str | None = None
    mode: ChatMode = ChatMode.NORMAL
    channel: Channel = Channel.CHAT
    context: QAContext = Field(default_factory=QAContext)
    correct: bool = True  # False = use the text exactly as typed
    adapt_tone: bool = True
    history: list[dict[str, Any]] | None = None  # client-side turns; only used when the server has none for this session


class QAResponse(BaseModel):
    """ChatResponse-compatible: `domain`, `query` and `response` plus whatever the answering module attached."""

    model_config = ConfigDict(extra="allow")

    domain: str
    query: str
    response: str

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class Focus(BaseModel):
    """The page/instrument/news item/company in focus for the turn in flight."""

    context: QAContext
    owner_id: str | None = None
    history: list[dict[str, Any]] | None = None  # client-side turns, used only when the server has none for the session


# Set by the pipeline for the turn in flight, read by core/orchestrator.py (which then answers from the focus).
active_focus: ContextVar[Focus | None] = ContextVar("aria_qa_focus", default=None)
