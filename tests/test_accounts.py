"""Real account/session/ownership persistence; no external identity or private data."""
import json
import os
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from api import auth, audio_store
from api.main import app
from shared import user_store as store
from starlette.websockets import WebSocketDisconnect

PASSWORD = "synthetic-test-password-123"


@pytest.fixture
def accounts(monkeypatch):
    monkeypatch.setenv("ARIA_AUTH_MODE", "accounts")
    monkeypatch.setenv("ARIA_APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("ARIA_AUTH_ALLOW_SIGNUP", "1")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    return TestClient(app, headers={"Origin": "http://testserver"})


def register(client):
    email = uuid.uuid4().hex + "@example.test"
    result = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200, result.text
    return result.json()["user"]


def test_private_mode_preserved_and_registration_disabled(monkeypatch):
    monkeypatch.setenv("ARIA_AUTH_MODE", "private")
    client = TestClient(app)
    assert client.get("/api/auth/session").json()["mode"] == "private"
    assert client.post("/api/auth/register", json={"email": "test@example.test", "password": PASSWORD}).status_code == 404
    assert client.get("/api/profile", params={"session_id": "private-synthetic-owner"}).status_code == 200


def test_registration_hash_cookie_refresh_and_fresh_process(accounts):
    user = register(accounts)
    cookie = accounts.cookies.get(auth.COOKIE)
    assert accounts.get("/api/auth/session").json()["user"] == user
    assert accounts.get("/api/auth/session").headers["cache-control"] == "no-store"
    with store._SessionLocal() as db:
        row = db.get(store.AccountRecord, user["id"])
        assert row.password_hash != PASSWORD and auth.password_matches(PASSWORD, row.password_hash)
        assert db.get(store.AuthSessionRecord, cookie) is None
        assert db.get(store.AuthSessionRecord, auth.fingerprint(cookie)).account_id == user["id"]
    code = "import json,sys; from starlette.requests import HTTPConnection; from api.auth import principal; print(json.dumps(principal(HTTPConnection({'type':'http','headers':[(b'cookie',('aria_auth='+sys.argv[1]).encode())]}))))"
    result = subprocess.run([sys.executable, "-c", code, cookie], capture_output=True, text=True,
                            env={**os.environ, "DB_URL": store.DB_URL}, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == user


def test_unauthenticated_and_cross_account_reads_and_writes_rejected(accounts):
    assert accounts.get("/api/profile?session_id=anyone").status_code == 401
    first = register(accounts)
    assert accounts.post("/api/profile", json={"session_id": first["id"], "monthly_income": 50000}).status_code == 200
    other = TestClient(app, headers={"Origin": "http://testserver"})
    second = register(other)
    for path in ("profile", "transactions", "transactions/insights"):
        assert other.get("/api/" + path, params={"session_id": first["id"]}).status_code == 403
    assert other.post("/api/profile", json={"session_id": first["id"], "monthly_income": 1}).status_code == 403
    assert other.delete("/api/profile", params={"session_id": first["id"]}).status_code == 403
    assert other.get("/api/research/reports", params={"owner_id": first["id"]}).status_code == 403
    assert other.get("/api/profile", params={"session_id": second["id"]}).json()["profile"]["monthly_income"] is None
    assert accounts.get("/api/profile", params={"session_id": first["id"]}).json()["profile"]["monthly_income"] == 50000


def test_csrf_origin_and_duplicate_owner_parameters(accounts):
    user = register(accounts)
    payload = {"session_id": user["id"], "monthly_income": 123}
    assert accounts.post("/api/profile", json=payload, headers={"Origin": "https://attacker.test"}).status_code == 403
    assert accounts.get(f"/api/profile?session_id={user['id']}&session_id=victim").status_code == 403
    assert accounts.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}, headers={"Origin": "https://attacker.test"}).status_code == 403


def test_login_rotation_logout_all_and_expiry(accounts):
    user = register(accounts)
    original = accounts.cookies.get(auth.COOKIE)
    other = TestClient(app, headers={"Origin": "http://testserver"})
    assert other.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 200
    assert other.cookies.get(auth.COOKIE) != original
    assert other.post("/api/auth/logout-all", json={}).status_code == 200
    assert accounts.get("/api/profile", params={"session_id": user["id"]}).status_code == 401
    assert accounts.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 200
    token = accounts.cookies.get(auth.COOKIE)
    with store._SessionLocal() as db:
        db.get(store.AuthSessionRecord, auth.fingerprint(token)).expires_at = 0
        db.commit()
    assert accounts.get("/api/auth/session").json()["user"] is None


def test_login_failure_budget_and_registration_switch(accounts, monkeypatch):
    user = register(accounts)
    for _ in range(10):
        assert accounts.post("/api/auth/login", json={"email": user["email"], "password": "incorrect-password-value"}).status_code == 401
    assert accounts.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 429
    monkeypatch.setenv("ARIA_AUTH_ALLOW_SIGNUP", "0")
    assert accounts.post("/api/auth/register", json={"email": "disabled@example.test", "password": PASSWORD}).status_code == 403


def test_statement_multipart_owner_is_checked(accounts):
    user = register(accounts)
    data = b"Date,Narration,Amount\n2026-10-01,SWIGGY,100\n"
    assert accounts.post("/api/transactions/parse", data={"session_id": "victim"}, files={"file": ("statement.csv", data)}).status_code == 403
    result = accounts.post("/api/transactions/parse", data={"session_id": user["id"]}, files={"file": ("statement.csv", data)})
    assert result.status_code == 200, result.text
    assert accounts.post("/api/transactions/import", json={"session_id": user["id"], "import_id": result.json()["import_id"]}).status_code == 200


def test_legacy_learning_state_cannot_be_claimed_by_selecting_its_id(accounts):
    user = register(accounts)
    legacy = uuid.uuid4().hex
    with store._SessionLocal() as db:
        db.add(store.LearningState(user_id=legacy, mastery_json='{"legacy-private-concept": 0.9}', history_json='[]'))
        db.commit()
    assert accounts.get("/api/progress", params={"session_id": legacy}).json()["engaged"] == []
    assert accounts.post("/api/quiz/answer", json={"session_id": legacy, "concept_id": "sip", "is_correct": True}).status_code == 200
    with store._SessionLocal() as db:
        assert json.loads(db.get(store.LearningState, legacy).mastery_json) == {"legacy-private-concept": .9}
        assert "sip" in json.loads(db.get(store.LearningState, f"account:{user['id']}:{legacy}").mastery_json)


def test_chat_progress_and_audio_are_account_scoped(accounts, mock_llm, monkeypatch, tmp_path):
    user = register(accounts)
    monkeypatch.setattr("api.routes.chat.register_later", lambda fn: None)
    session = uuid.uuid4().hex
    payload = {"session_id": session, "owner_id": user["id"], "query": "hello"}
    assert accounts.post("/api/chat", json=payload).status_code == 200
    assert accounts.get("/api/chat/history", params={"session_id": session}).status_code == 403
    second = TestClient(app, headers={"Origin": "http://testserver"})
    other = register(second)
    assert second.get("/api/chat/history", params={"session_id": session, "owner_id": other["id"]}).status_code == 403
    assert second.get("/api/progress", params={"session_id": session}).status_code == 403
    source = tmp_path / "account.wav"
    source.write_bytes(b"RIFFsynthetic")
    token = store.current_owner.set(user["id"])
    try:
        clip = audio_store.register(str(source))
    finally:
        store.current_owner.reset(token)
    assert accounts.get("/api/audio/" + clip).status_code == 200
    assert second.get("/api/audio/" + clip).status_code == 404
    assert second.get("/avatar/render", params={"audio_token": clip}).status_code == 404


def test_shared_mutable_integrations_fail_closed_before_work(accounts, monkeypatch):
    register(accounts)
    assert accounts.post("/api/research/validation", json={"symbol": "TCS.NS"}).status_code == 403
    assert accounts.post("/api/tavus/start", json={"session_id": "new"}).status_code == 403
    from modules.equity_research.intelligence import pipeline
    monkeypatch.setenv("ARIA_FORECAST", "1")
    monkeypatch.setenv("ARIA_SCENARIO_BACKTEST", "1")
    def forbidden(*a, **k):
        pytest.fail("Account-mode report queued a globally shared job")
    monkeypatch.setattr("modules.equity_research.forecast.jobs.submit", forbidden)
    monkeypatch.setattr("modules.equity_research.scenario_backtest.jobs.submit", forbidden)
    pipeline._queue_forecast("TEST.NS", "private-report")
    pipeline._queue_scenario_backtest(SimpleNamespace(tables={"income": "synthetic"}))


def test_websocket_authentication_owner_and_revocation(accounts, monkeypatch):
    with pytest.raises(WebSocketDisconnect) as denied:
        with accounts.websocket_connect("/api/live/ws"):
            pass
    assert denied.value.code == 1008
    user = register(accounts)
    with accounts.websocket_connect("/api/live/ws") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        assert accounts.post("/api/auth/logout", json={}).status_code == 200
        ws.send_json({"type": "ping"})
        with pytest.raises(WebSocketDisconnect) as revoked:
            ws.receive_json()
        assert revoked.value.code == 1008
    assert accounts.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 200
    async def forbidden(*a, **k):
        pytest.fail("Cross-account live message reached provider task")
    monkeypatch.setattr("api.routes.live._reply", forbidden)
    with accounts.websocket_connect("/api/live/ws") as ws:
        ws.send_json({"type": "user", "owner_id": "another-account", "session_id": uuid.uuid4().hex, "text": "hello"})
        with pytest.raises(WebSocketDisconnect) as mismatch:
            ws.receive_json()
        assert mismatch.value.code == 1008


@pytest.fixture
def google(accounts, monkeypatch):
    """Real RSA JWT verification with a test-only Google certificate transport."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt, jwt
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    signer = crypt.RSASigner.from_string(pem, key_id="synthetic")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "synthetic-client.apps.googleusercontent.com")
    calls = []
    def transport(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=200, data=json.dumps({"synthetic": public}).encode())
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda: transport)
    def credential(**overrides):
        config = accounts.get("/api/auth/session").json()
        claims = {"iss": "https://accounts.google.com", "aud": config["google_client_id"], "sub": uuid.uuid4().hex,
                  "email": uuid.uuid4().hex + "@gmail.com", "email_verified": True, "iat": int(time.time()),
                  "exp": int(time.time()) + 300, "nonce": config["google_nonce"], **overrides}
        return jwt.encode(signer, claims).decode()
    return credential, calls


@pytest.mark.parametrize("override", [{"aud": "wrong-client"}, {"iss": "https://attacker.test"}, {"exp": 1}, {"nonce": "wrong"}, {"email_verified": False}])
def test_google_real_signature_verifier_rejects_invalid_claims(accounts, google, override):
    credential, _ = google
    response = accounts.post("/api/auth/google", json={"credential": credential(**override)})
    assert response.status_code == 401


def test_google_registration_and_explicit_password_account_link(accounts, google):
    credential, calls = google
    user = register(accounts)
    sub = uuid.uuid4().hex
    token = credential(email=user["email"], sub=sub)
    assert accounts.post("/api/auth/google", json={"credential": token}).status_code == 409
    assert accounts.post("/api/auth/google/link", json={"credential": token}).status_code == 200
    assert accounts.post("/api/auth/logout", json={}).status_code == 200
    signed_in = accounts.post("/api/auth/google", json={"credential": credential(email=user["email"], sub=sub)})
    assert signed_in.status_code == 200 and signed_in.json()["user"] == user
    assert calls and all(call["timeout"] == 10 for call in calls)


def test_google_new_account_and_invalid_signature(accounts, google):
    credential, _ = google
    token = credential()
    header, payload, signature = token.split(".")
    corrupted = header + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    assert accounts.post("/api/auth/google", json={"credential": corrupted}).status_code == 401
    assert accounts.post("/api/auth/google", json={"credential": token}).status_code == 200


def test_google_nonce_survives_status_reads_and_rejects_stale_challenge(accounts, google):
    credential, _ = google
    token = credential()
    first = accounts.get("/api/auth/session").json()["google_nonce"]
    assert accounts.get("/api/auth/session").json()["google_nonce"] == first
    assert accounts.post("/api/auth/google", json={"credential": token}).status_code == 200
    token = credential()
    nonce = accounts.get("/api/auth/session").json()["google_nonce"]
    accounts.cookies.set(auth.NONCE_COOKIE, f"1.{nonce}", domain="testserver.local", path="/")
    assert accounts.post("/api/auth/google", json={"credential": token}).status_code == 401
