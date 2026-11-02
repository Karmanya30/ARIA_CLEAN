"""Accounts-mode authorisation probes: does api.auth.authorize look at the same body the route parses?
authorize() only inspects JSON when content-type startswith "application/json" (case-sensitive) and multipart when it startswith
"multipart/form-data"; FastAPI/Starlette may parse other spellings. Synthetic accounts, scratch DB, no model."""
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from shared import user_store as store
from tests.test_accounts import PASSWORD, accounts, register  # noqa: F401


@pytest.fixture
def two(accounts):
    victim = register(accounts)
    assert accounts.post("/api/profile", json={"session_id": victim["id"], "monthly_income": 111111}).status_code == 200
    atk = TestClient(app, headers={"Origin": "http://testserver"}, raise_server_exceptions=False)
    attacker = register(atk)
    return accounts, victim, atk, attacker


def victim_income(accounts, victim):
    return accounts.get("/api/profile", params={"session_id": victim["id"]}).json()["profile"]["monthly_income"]


@pytest.mark.parametrize("ctype", [None, "Application/JSON", "application/JSON; charset=utf-8", "text/plain", "application/vnd.api+json"])
def test_profile_write_with_victim_session_id_in_odd_content_type(two, ctype):
    accounts, victim, atk, attacker = two
    headers = {"content-type": ctype} if ctype else {}
    body = json.dumps({"session_id": victim["id"], "monthly_income": 1}).encode()
    r = atk.post("/api/profile", content=body, headers=headers)
    assert victim_income(accounts, victim) == 111111, f"VICTIM DATA OVERWRITTEN with content-type={ctype!r}, status {r.status_code}"
    assert r.status_code in (401, 403, 415, 422), (ctype, r.status_code, r.text[:120])


@pytest.mark.parametrize("ctype", [None, "Application/JSON", "text/plain"])
def test_transaction_write_with_victim_session_id_in_odd_content_type(two, ctype):
    accounts, victim, atk, attacker = two
    body = json.dumps({"session_id": victim["id"], "date": "2026-01-15", "category": "food", "amount": 5}).encode()
    r = atk.post("/api/transactions", content=body, headers={"content-type": ctype} if ctype else {})
    n = len(accounts.get("/api/transactions", params={"session_id": victim["id"]}).json())
    assert n == 0, f"VICTIM DATA WRITTEN with content-type={ctype!r}, status {r.status_code}"


@pytest.mark.parametrize("ctype", ["Multipart/Form-Data", "MULTIPART/FORM-DATA"])
def test_multipart_case_variants(two, ctype):
    accounts, victim, atk, attacker = two
    boundary = "xBOUNDARYx"
    payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n{victim['id']}\r\n"
               f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.csv\"\r\nContent-Type: text/csv\r\n\r\n"
               "Date,Narration,Withdrawal Amt.,Deposit Amt.\r\n01/05/2024,ZOMATO,250,\r\n"
               f"--{boundary}--\r\n").encode()
    r = atk.post("/api/transactions/parse", content=payload, headers={"content-type": f"{ctype}; boundary={boundary}"})
    assert r.status_code in (401, 403, 415, 422), f"parse accepted another account's session_id under {ctype}: {r.status_code}"


def test_login_throttle_table_cap_blocks_every_new_email(accounts):
    """SUSPECTED->VERIFIED mechanism of QA-AUTH-002: AuthThrottleRecord is capped at 4096 rows for 15 minutes; once full, a
    login/register for any not-yet-seen email gets 429 (also for a legitimate user)."""
    with store._SessionLocal() as db:
        db.query(store.AuthThrottleRecord).delete()
        for i in range(4096):
            db.add(store.AuthThrottleRecord(key=f"synthetic-{i}-{uuid.uuid4().hex}", attempts=1, expires_at=time.time() + 900))
        db.commit()
    try:
        r = accounts.post("/api/auth/login", json={"email": "someone-new@example.test", "password": PASSWORD})
        assert r.status_code != 429, "sign-in refused for everyone while 4096 throttle rows exist"
    finally:
        with store._SessionLocal() as db:
            db.query(store.AuthThrottleRecord).delete()
            db.commit()


def test_ten_failed_logins_lock_the_real_owner_out(accounts):
    """QA-AUTH-003 (design): the throttle key is the email only, so anyone can lock a known email out for 15 minutes."""
    user = register(accounts)
    with store._SessionLocal() as db:
        email = db.get(store.AccountRecord, user["id"]).email
    other = TestClient(app, headers={"Origin": "http://testserver"}, raise_server_exceptions=False)
    codes = [other.post("/api/auth/login", json={"email": email, "password": "wrong-password-xx"}).status_code for _ in range(11)]
    owner = TestClient(app, headers={"Origin": "http://testserver"}, raise_server_exceptions=False)
    r = owner.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, f"owner locked out after attacker attempts {codes[-2:]}: {r.status_code}"


def test_short_password_on_login_is_422_not_401(accounts):
    """QA-AUTH-004 (minor): login reuses the registration schema, so a short wrong password returns a policy 422."""
    r = accounts.post("/api/auth/login", json={"email": "a@example.test", "password": "short"})
    assert r.status_code == 401


def test_chat_body_owner_id_smuggled_via_content_type_case(two):
    """Same parser mismatch on /api/chat: the query owner_id (attacker, passes the check) differs from the body owner_id (victim),
    and modules/qa/pipeline.py binds current_owner to the BODY value."""
    accounts, victim, atk, attacker = two
    sid = uuid.uuid4().hex
    body = json.dumps({"query": "hello", "session_id": sid, "owner_id": victim["id"], "request_id": uuid.uuid4().hex}).encode()
    r = atk.post("/api/chat", params={"owner_id": attacker["id"]}, content=body, headers={"content-type": "Application/JSON"})
    items = accounts.get("/api/conversations", params={"owner_id": victim["id"]}).json()["items"]
    assert sid not in [i["id"] for i in items], f"attacker wrote a conversation into the victim's history (status {r.status_code})"
