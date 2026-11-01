"""Conversation history for the sidebar: list/search, open (paged), rename, pin, archive, delete, export.

Ownership is decided in shared.conversation_history (every query is filtered by owner); a missing or foreign id is a 404.
In account mode api.auth.authorize has already checked that owner_id is the signed-in account.
"""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from shared import conversation_history as H
from shared.user_store import current_owner

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@contextmanager
def _as(owner_id: str | None):
    if not owner_id:
        raise HTTPException(403, "An owner is required.")
    token = current_owner.set(owner_id)
    try:
        yield
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        current_owner.reset(token)


class Patch(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


@router.get("")
def list_(owner_id: str | None = None, q: str = "", archived: bool = False, limit: int = 30, offset: int = 0):
    with _as(owner_id):
        return H.list_conversations(q=q, archived=archived, limit=limit, offset=max(0, offset))


@router.get("/{cid}/messages")
def messages(cid: str, owner_id: str | None = None, before: int | None = None, limit: int = 50):
    with _as(owner_id):
        return H.messages(cid, before=before, limit=limit)


@router.get("/{cid}/export")
def export(cid: str, owner_id: str | None = None, format: str = "json"):
    with _as(owner_id):
        name, media, body = H.export(cid, "markdown" if format in ("md", "markdown") else "json")
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.patch("/{cid}")
def patch(cid: str, req: Patch, owner_id: str | None = None):
    with _as(owner_id):
        out = None
        if req.title is not None:
            out = H.rename(cid, req.title)
        if req.archived is not None:
            out = H.archive(cid, req.archived)
        if req.pinned is not None:
            out = H.pin(cid, req.pinned)
    if out is None:
        raise HTTPException(422, "Nothing to change")
    return out


@router.delete("/{cid}")
def delete(cid: str, owner_id: str | None = None):
    with _as(owner_id):
        H.delete(cid)
    return {"status": "deleted"}
