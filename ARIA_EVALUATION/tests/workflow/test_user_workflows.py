"""End-to-end API workflows (in-process, scratch DB, no model, no network). Chat uses "hello" (small-talk path, no LLM)."""
import uuid

from fastapi.testclient import TestClient

from api.main import app
from tests.test_accounts import PASSWORD, accounts, register  # noqa: F401

CSV = (b"Date,Narration,Withdrawal Amt.,Deposit Amt.\n01/05/2024,ZOMATO ORDER,250.50,\n"
       b"02/05/2024,SALARY ACME,,50000\n03/05/2024,ELECTRICITY BILL,2400,\n")


def test_profile_lifecycle():
    c, o = TestClient(app), "wf-" + uuid.uuid4().hex
    assert c.post("/api/profile", json={"session_id": o, "monthly_income": 85000, "age": 31}).status_code == 200
    assert c.get("/api/profile", params={"session_id": o}).json()["profile"]["monthly_income"] == 85000
    assert c.get("/api/profile/summary", params={"session_id": o}).status_code == 200
    assert c.delete("/api/profile", params={"session_id": o}).status_code == 200
    assert not c.get("/api/profile", params={"session_id": o}).json()["profile"]["monthly_income"]


def test_transactions_sample_insights_clear_and_statement_import():
    c, o = TestClient(app), "wf-" + uuid.uuid4().hex
    assert c.post("/api/transactions/sample", json={"session_id": o}).status_code == 200
    assert len(c.get("/api/transactions", params={"session_id": o}).json()) >= 10
    assert c.get("/api/transactions/insights", params={"session_id": o}).status_code == 200
    assert c.delete("/api/transactions", params={"session_id": o}).status_code == 200
    assert c.get("/api/transactions", params={"session_id": o}).json() == []
    p = c.post("/api/transactions/parse", data={"session_id": o}, files={"file": ("s.csv", CSV, "text/csv")})
    assert p.status_code == 200, p.text
    imp = c.post("/api/transactions/import", json={"session_id": o, "import_id": p.json()["import_id"]})
    assert imp.status_code == 200, imp.text
    again = c.post("/api/transactions/import", json={"session_id": o, "import_id": p.json()["import_id"]})
    assert again.status_code in (200, 404)  # re-import must not duplicate rows (checked next)
    descr = [t.get("merchant") or t.get("description") for t in c.get("/api/transactions", params={"session_id": o}).json()]
    assert len(descr) == len(set(map(str, descr))) or len(descr) <= 3
    # another owner cannot import this preview
    other = "wf-" + uuid.uuid4().hex
    p2 = c.post("/api/transactions/parse", data={"session_id": o}, files={"file": ("s.csv", CSV, "text/csv")}).json()["import_id"]
    assert c.post("/api/transactions/import", json={"session_id": other, "import_id": p2}).status_code == 404


def test_chat_to_history_to_export_to_delete():
    c, o, sid = TestClient(app), "wf-" + uuid.uuid4().hex, uuid.uuid4().hex
    r = c.post("/api/chat", json={"query": "hello", "session_id": sid, "owner_id": o, "request_id": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    got = c.get("/api/conversations", params={"owner_id": o}).json()["items"]
    assert [i["id"] for i in got] == [sid]
    assert c.patch(f"/api/conversations/{sid}", params={"owner_id": o}, json={"title": "Greeting", "pinned": True}).json()["title"] == "Greeting"
    mid = c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"][0]["message_id"]
    assert c.put(f"/api/conversations/{sid}/messages/{mid}/rating", params={"owner_id": o}, json={"rating": 1}).status_code == 200
    assert "greeting" in c.get(f"/api/conversations/{sid}/export", params={"owner_id": o, "format": "md"}).headers["content-disposition"]
    # a second turn in the same session lands in the same conversation
    c.post("/api/chat", json={"query": "thanks", "session_id": sid, "owner_id": o, "request_id": uuid.uuid4().hex})
    assert len(c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"]) == 2
    # /api/chat/clear hides history from the reopened conversation
    assert c.post("/api/chat/clear", json={"session_id": sid, "owner_id": o}).status_code == 200
    assert c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"] == []
    assert c.delete(f"/api/conversations/{sid}", params={"owner_id": o}).status_code == 200
    assert c.get("/api/conversations", params={"owner_id": o}).json()["items"] == []


def test_chat_duplicate_request_id_does_not_duplicate_turn():
    c, o, sid, rid = TestClient(app), "wf-" + uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    body = {"query": "hello", "session_id": sid, "owner_id": o, "request_id": rid}
    assert c.post("/api/chat", json=body).status_code == 200
    assert c.post("/api/chat", json=body).status_code in (200, 409)
    assert len(c.get(f"/api/conversations/{sid}/messages", params={"owner_id": o}).json()["turns"]) == 1


def test_account_lifecycle(accounts):
    user = register(accounts)
    assert accounts.get("/api/auth/session").json()["user"]["id"] == user["id"]
    assert accounts.post("/api/profile", json={"session_id": user["id"], "monthly_income": 60000}).status_code == 200
    assert accounts.get("/api/profile", params={"session_id": "someone-else"}).status_code == 403
    email = accounts.get("/api/auth/session").json()["user"].get("email")
    accounts.post("/api/auth/logout")
    assert accounts.get("/api/profile", params={"session_id": user["id"]}).status_code == 401
    if email:
        assert accounts.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code in (400, 401, 403)
        assert accounts.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        assert accounts.get("/api/profile", params={"session_id": user["id"]}).json()["profile"]["monthly_income"] == 60000
