"""Conversation history: persistence, ownership, second device, search, rename/pin/archive/delete, export, paging, migration."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from shared import conversation_memory as cm
from shared import user_store as store
from tests.test_accounts import PASSWORD, accounts, register  # noqa: F401


def seed(owner_id, query, answer="An answer.", sid=None, ok=True):
    """One saved turn, written the way the pipeline writes it (no model call)."""
    sid = sid or uuid.uuid4().hex
    token = store.current_owner.set(owner_id)
    try:
        req = cm.begin(sid, query)
        cm.active_request.set(req)
        cm.complete(sid, query, {"response": answer if ok else "Error: boom", "domain": "general"})
        cm.active_request.set(None)
    finally:
        store.current_owner.reset(token)
    return sid


@pytest.fixture
def private():
    return TestClient(app), uuid.uuid4().hex


def ls(c, o, **kw):
    r = c.get("/api/conversations", params={"owner_id": o, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def ids(c, o, **kw):
    return [i["id"] for i in ls(c, o, **kw)["items"]]


def test_saved_chat_is_listed_with_an_auto_title_and_restores(private):
    c, o = private
    sid = seed(o, "what is a sip and how does it work in india for a beginner who wants to start investing?")
    item = ls(c, o)["items"][0]
    assert item["id"] == sid and item["title"].startswith("What is a sip") and item["title"].endswith("…") and len(item["title"]) <= 60
    m = c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()
    assert [t["response"]["response"] for t in m["turns"]] == ["An answer."]


def test_failed_answer_is_not_listed(private):
    c, o = private
    seed(o, "this will fail", ok=False)
    assert ls(c, o)["items"] == []


def test_rename_pin_archive_delete_and_search(private):
    c, o = private
    a, b, d = seed(o, "tell me about gold prices"), seed(o, "explain compound interest"), seed(o, "my budget plan")

    def p(sid, **body):
        return c.patch(f"/api/conversations/{sid}", params={"owner_id": o}, json=body)

    assert p(a, title="  Gold   notes ").json()["title"] == "Gold notes"
    assert p(a, title="   ").status_code == 422
    p(b, pinned=True)
    assert ids(c, o)[0] == b  # pinned first
    p(d, archived=True)
    assert d not in ids(c, o) and ids(c, o, archived=True) == [d]
    assert ids(c, o, q="gold") == [a]
    assert ids(c, o, q="compound") == [b]  # found by message text, not the title
    assert ids(c, o, q="%") == []  # wildcards are literal
    assert c.delete(f"/api/conversations/{a}", params={"owner_id": o}).status_code == 200
    assert a not in ids(c, o)
    assert c.get(f"/api/conversations/{a}/messages", params={"owner_id": o}).status_code == 404


def test_pagination_of_list_and_messages(private):
    c, o = private
    for i in range(7):
        seed(o, f"question {i}")
    first = ls(c, o, limit=3)
    assert len(first["items"]) == 3 and first["next_offset"] == 3
    assert len(ls(c, o, limit=3, offset=3)["items"]) == 3
    last = ls(c, o, limit=3, offset=6)
    assert len(last["items"]) == 1 and last["next_offset"] is None
    sid = seed(o, "q0")
    for i in range(1, 6):
        seed(o, f"q{i}", sid=sid)
    page = c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o, "limit": 4}).json()
    assert [t["query"] for t in page["turns"]] == ["q2", "q3", "q4", "q5"] and page["next_before"]
    older = c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o, "limit": 4, "before": page["next_before"]}).json()
    assert [t["query"] for t in older["turns"]] == ["q0", "q1"] and older["next_before"] is None


def test_export_has_every_turn(private):
    c, o = private
    sid = seed(o, "first")
    seed(o, "second", sid=sid)
    body = c.get(f"/api/conversations/{sid}/export", params={"owner_id": o}).json()
    assert [t["query"] for t in body["turns"]] == ["first", "second"]
    md = c.get(f"/api/conversations/{sid}/export", params={"owner_id": o, "format": "markdown"})
    assert "attachment" in md.headers["content-disposition"] and "second" in md.text


def test_another_owner_cannot_see_change_or_export(private):
    c, o = private
    sid = seed(o, "private thing")
    other = uuid.uuid4().hex
    assert ls(c, other)["items"] == []
    assert c.get(f"/api/conversations/{sid}/messages", params={"owner_id": other}).status_code == 404
    assert c.patch(f"/api/conversations/{sid}", params={"owner_id": other}, json={"title": "x"}).status_code == 404
    assert c.delete(f"/api/conversations/{sid}", params={"owner_id": other}).status_code == 404
    assert c.get(f"/api/conversations/{sid}/export", params={"owner_id": other}).status_code == 404
    assert c.get("/api/conversations").status_code == 403
    assert ls(c, o)["items"][0]["title"] == "Private thing"


def test_account_second_device_logout_login_and_isolation(accounts):
    user = register(accounts)
    sid = seed(user["id"], "my retirement question")
    with store._SessionLocal() as db:
        email = db.get(store.AccountRecord, user["id"]).email
    # a second device: a fresh client signing in with the same credentials sees the conversation with no local state
    device2 = TestClient(app, headers={"Origin": "http://testserver"})
    assert device2.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert [i["id"] for i in device2.get("/api/conversations", params={"owner_id": user["id"]}).json()["items"]] == [sid]
    # logout, then log in again on the first device: still there
    accounts.post("/api/auth/logout")
    assert accounts.get("/api/conversations", params={"owner_id": user["id"]}).status_code == 401
    accounts.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert accounts.get(f"/api/conversations/{sid}/messages", params={"owner_id": user["id"]}).json()["turns"][0]["query"] == "my retirement question"
    # another account cannot name the first as owner, nor open its conversation under its own id
    other_client = TestClient(app, headers={"Origin": "http://testserver"})
    other = register(other_client)
    assert other_client.get("/api/conversations", params={"owner_id": user["id"]}).status_code == 403
    assert other_client.get(f"/api/conversations/{sid}/messages", params={"owner_id": other["id"]}).status_code == 404


def test_migration_fills_dates_and_keeps_rows():
    sid = seed("legacy-owner", "an old question")
    with store._engine.begin() as c:
        c.execute(text("UPDATE chat_conversations SET created_at=NULL, updated_at=NULL WHERE id=:i"), {"i": sid})
    cm._migrate()
    with store._engine.begin() as c:
        row = c.execute(text("SELECT created_at, updated_at FROM chat_conversations WHERE id=:i"), {"i": sid}).one()
    assert row[0] and row[1]


def test_writing_to_a_deleted_chat_brings_it_back(private):
    c, o = private
    sid = seed(o, "hello there")
    c.delete(f"/api/conversations/{sid}", params={"owner_id": o})
    seed(o, "still here", sid=sid)
    assert ids(c, o) == [sid]


def test_real_chat_request_is_saved_and_listed(private):
    """The whole path, not a seeded row: POST /api/chat, then the list, the reopened messages and a fresh client."""
    c, o = private
    sid = uuid.uuid4().hex
    r = c.post("/api/chat", json={"query": "hello", "session_id": sid, "owner_id": o, "request_id": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    got = ls(TestClient(app), o)["items"]  # a brand-new client = another browser holding only the owner id
    assert [i["id"] for i in got] == [sid] and got[0]["title"] == "Hello"
    turns = TestClient(app).get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"]
    assert turns[0]["query"] == "hello" and turns[0]["response"]["response"]


def test_rating_is_saved_per_message_and_owner_scoped(private):
    c, o = private
    sid = seed(o, "rate me")
    mid = c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"][0]["message_id"]
    url = f"/api/conversations/{sid}/messages/{mid}/rating"
    assert c.put(url, params={"owner_id": o}, json={"rating": -1}).status_code == 200
    assert c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"][0]["rating"] == -1
    assert c.put(url, params={"owner_id": o}, json={"rating": 5}).status_code == 422
    assert c.put(url, params={"owner_id": uuid.uuid4().hex}, json={"rating": 1}).status_code == 404
    assert c.put(f"/api/conversations/{sid}/messages/999999/rating", params={"owner_id": o}, json={"rating": 1}).status_code == 404


def test_export_with_a_non_latin_title_does_not_fail(private):
    c, o = private
    sid = seed(o, "नमस्ते SIP क्या है")
    r = c.patch(f"/api/conversations/{sid}", params={"owner_id": o}, json={"title": "म्यूचुअल फंड"})
    assert r.status_code == 200
    r = c.get(f"/api/conversations/{sid}/export", params={"owner_id": o})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]


def test_deleted_chat_is_forgotten_by_memory(private):
    c, o = private
    a = seed(o, "my daughter's school fee is 1.2 lakh")
    b = seed(o, "something else entirely")
    assert c.delete(f"/api/conversations/{a}", params={"owner_id": o}).status_code == 200
    token = store.current_owner.set(o)
    try:
        found, _ = cm.retrieve(b, "daughter school fee")
    finally:
        store.current_owner.reset(token)
    assert not any("school fee" in r["text"] for r in found)
