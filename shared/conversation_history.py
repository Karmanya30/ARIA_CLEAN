"""Conversation list, search, rename, pin, archive, delete, export and paged messages for the history sidebar.

Every query is filtered by the owner (the signed-in account, or the device owner in private mode), so a conversation id from
another owner is indistinguishable from one that does not exist. The turns stay in chat_turns, the single source of truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select

from shared import user_store as store
from shared.conversation_memory import Conversation, Turn, owner

MAX_LIMIT = 100


def _mine(db, cid: str) -> Conversation:
    row = db.get(Conversation, cid)
    if row is None or row.owner_id != owner(cid) or row.deleted_at:
        raise LookupError("Conversation not found")
    return row


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _summary(row: Conversation, count: int, snippet: str | None = None) -> dict:
    return {"id": row.id, "title": row.title or "New chat", "pinned": bool(row.pinned), "archived": bool(row.archived),
            "created_at": row.created_at, "updated_at": row.updated_at, "messages": count, **({"snippet": snippet} if snippet else {})}


def list_conversations(*, q: str = "", archived: bool = False, limit: int = 30, offset: int = 0) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))
    me = owner("")
    with store._SessionLocal() as db:
        counts = (select(Turn.conversation_id, func.count(Turn.id).label("n")).where(Turn.status == "complete")
                  .group_by(Turn.conversation_id).subquery())
        stmt = (select(Conversation, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.conversation_id == Conversation.id)
                .where(Conversation.owner_id == me, Conversation.deleted_at.is_(None), Conversation.archived == int(archived),
                       func.coalesce(counts.c.n, 0) > 0))  # a conversation with no saved answer yet is not worth listing
        snippets: dict[str, str] = {}
        if q.strip():
            pat = _like(q.strip())
            hits = db.execute(select(Turn.conversation_id, Turn.query).where(
                Turn.status == "complete", or_(Turn.query.ilike(pat, escape="\\"), Turn.response_json.ilike(pat, escape="\\")))
                .order_by(Turn.id.desc())).all()
            for cid, query in hits:
                snippets.setdefault(cid, query[:140])
            stmt = stmt.where(or_(Conversation.title.ilike(pat, escape="\\"), Conversation.id.in_(list(snippets))))
        stmt = stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc(), Conversation.id).offset(offset).limit(limit + 1)
        rows = db.execute(stmt).all()
        page = rows[:limit]
        return {"items": [_summary(c, n, snippets.get(c.id)) for c, n in page],
                "next_offset": offset + limit if len(rows) > limit else None}


def _update(cid: str, **fields) -> dict:
    with store._SessionLocal() as db:
        row = _mine(db, cid)
        for k, v in fields.items():
            setattr(row, k, v)
        db.commit()
        n = db.scalar(select(func.count(Turn.id)).where(Turn.conversation_id == cid, Turn.status == "complete"))
        return _summary(row, n)


def rename(cid: str, title: str) -> dict:
    title = " ".join(title.split())[:120]
    if not title:
        raise ValueError("Title cannot be empty")
    return _update(cid, title=title)


def pin(cid: str, on: bool) -> dict:
    return _update(cid, pinned=int(on))


def archive(cid: str, on: bool) -> dict:
    return _update(cid, archived=int(on), **({"pinned": 0} if on else {}))  # an archived chat is not pinned


def delete(cid: str) -> None:
    _update(cid, deleted_at=datetime.now(timezone.utc).isoformat())


def messages(cid: str, *, before: int | None = None, limit: int = 50) -> dict:
    """The newest `limit` complete turns older than `before`, oldest first; `next_before` is set while earlier ones exist."""
    limit = max(1, min(limit, MAX_LIMIT))
    with store._SessionLocal() as db:
        conv = _mine(db, cid)
        cond = [Turn.conversation_id == cid, Turn.id > conv.cleared_through, Turn.status == "complete"]
        if before:
            cond.append(Turn.id < before)
        rows = db.scalars(select(Turn).where(and_(*cond)).order_by(Turn.id.desc()).limit(limit + 1)).all()
        page = rows[:limit][::-1]
        return {"conversation": _summary(conv, len(page)), "turns": [
            {"message_id": r.id, "query": r.query, "response": json.loads(r.response_json), "created_at": r.created_at,
             "audio_token": json.loads(r.response_json).get("audio_token"), "rating": r.rating} for r in page],
            "next_before": page[0].id if len(rows) > limit and page else None}


def rate(cid: str, message_id: int, value: int | None) -> None:
    if value not in (1, -1, None):
        raise ValueError("rating must be 1, -1 or null")
    with store._SessionLocal() as db:
        _mine(db, cid)
        turn = db.get(Turn, message_id)
        if turn is None or turn.conversation_id != cid:
            raise LookupError("Message not found")
        turn.rating = value
        db.commit()


def export(cid: str, fmt: str = "json") -> tuple[str, str, str]:
    """(filename, media type, body) with every saved turn, not just the visible page."""
    with store._SessionLocal() as db:
        conv = _mine(db, cid)
        rows = db.scalars(select(Turn).where(Turn.conversation_id == cid, Turn.status == "complete").order_by(Turn.id)).all()
        turns = [(r.created_at, r.query, json.loads(r.response_json)) for r in rows]
        title = conv.title or "New chat"
    slug = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in title.lower()).strip("-")[:40] or "chat"  # ASCII only: header values must be Latin-1
    if fmt == "markdown":
        body = f"# {title}\n\n" + "\n\n".join(f"**You** ({t})\n\n{q}\n\n**ARIA**\n\n{r.get('response', '')}" for t, q, r in turns)
        return f"{slug}.md", "text/markdown; charset=utf-8", body
    body = json.dumps({"id": cid, "title": title, "turns": [{"created_at": t, "query": q, "response": r} for t, q, r in turns]},
                      ensure_ascii=False, indent=2)
    return f"{slug}.json", "application/json", body
