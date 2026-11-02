"""Optional cookie accounts. Private mode preserves existing local workflows.

Account mode fails closed for integrations that still have global mutable
state (paid video and compute jobs), rather than treating a UUID as a login.
"""
import hashlib
import hmac
import os
import re
import secrets
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, WebSocketException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.requests import HTTPConnection

router = APIRouter(prefix="/api/auth", tags=["accounts"])
COOKIE = "aria_auth"
NONCE_COOKIE = "aria_google_nonce"
SESSION_SECONDS = 7 * 24 * 3600
ITERATIONS = 600_000


def mode():
    value = os.getenv("ARIA_AUTH_MODE", "private")
    if value not in ("private", "accounts"):
        raise ValueError("ARIA_AUTH_MODE must be private or accounts")
    return value


def origin():
    value = os.getenv("ARIA_APP_ORIGIN", "http://localhost:5173").rstrip("/")
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname or url.path or url.query or url.fragment or url.username:
        raise ValueError("ARIA_APP_ORIGIN must be one exact HTTP(S) origin")
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1", "testserver"):
        raise ValueError("Non-local accounts require an HTTPS ARIA_APP_ORIGIN")
    return value


def _store():
    from shared import user_store
    return user_store


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, *, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"{ITERATIONS}${salt}${digest}"


def password_matches(password, encoded):
    try:
        iterations, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def principal(connection: HTTPConnection):
    token = connection.cookies.get(COOKIE, "")
    if len(token) < 32 or len(token) > 128:
        return None
    store = _store()
    with store._SessionLocal() as db:
        row = db.get(store.AuthSessionRecord, fingerprint(token))
        if row is None or row.expires_at <= time.time():
            return None
        account = db.get(store.AccountRecord, row.account_id)
        return {"id": account.id, "email": account.email} if account else None


def same_origin(request):
    if request.headers.get("origin") != origin():
        raise HTTPException(403, "This request must come from the ARIA application.")


def _accounts(request):
    if mode() != "accounts":
        raise HTTPException(404, "Account sign-in is disabled in private mode.")
    same_origin(request)


def _cookie(response, name, value, seconds):
    response.set_cookie(name, value, max_age=seconds, httponly=True, secure=origin().startswith("https://"),
                        samesite="strict", path="/")


def _session(account, response):
    store = _store()
    token = secrets.token_urlsafe(32)
    with store._SessionLocal() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        db.query(store.AuthSessionRecord).filter(store.AuthSessionRecord.expires_at <= time.time()).delete()
        # Bound persistent sessions per account (oldest sessions are revoked).
        rows = db.query(store.AuthSessionRecord).filter_by(account_id=account["id"]).order_by(store.AuthSessionRecord.expires_at).all()
        for row in rows[:-9]:
            db.delete(row)
        db.add(store.AuthSessionRecord(token_hash=fingerprint(token), account_id=account["id"], expires_at=time.time() + SESSION_SECONDS))
        db.query(store.AuthThrottleRecord).filter_by(key=fingerprint(account["email"])).delete()
        db.commit()
    _cookie(response, COOKIE, token, SESSION_SECONDS)
    response.headers["Cache-Control"] = "no-store"
    return {"user": account}


_THROTTLE_WINDOW = 900
_THROTTLE_ROWS = 4096


def _throttle(email, ip="unknown"):
    """Sign-in attempt budget, per (email, address) pair so a stranger cannot lock the real owner out from another address (10 tries),
    plus looser ceilings per email (100) and per address (60) against spraying. A full table evicts its oldest rows instead of
    refusing everyone (QA-AUTH-002). Returns the pair's key so a successful sign-in can clear it."""
    store = _store()
    keys = [(fingerprint(f"{email}|{ip}"), 10), (fingerprint(f"email|{email}"), 100), (fingerprint(f"ip|{ip}"), 60)]
    with store._SessionLocal() as db:
        db.execute(text("BEGIN IMMEDIATE"))
        now = time.time()
        db.query(store.AuthThrottleRecord).filter(store.AuthThrottleRecord.expires_at <= now).delete()
        if db.query(store.AuthThrottleRecord).count() >= _THROTTLE_ROWS - len(keys):
            oldest = [r.key for r in db.query(store.AuthThrottleRecord).order_by(store.AuthThrottleRecord.expires_at).limit(_THROTTLE_ROWS // 16)]
            db.query(store.AuthThrottleRecord).filter(store.AuthThrottleRecord.key.in_(oldest)).delete(synchronize_session=False)
        for key, limit in keys:
            row = db.get(store.AuthThrottleRecord, key)
            if row is None:
                row = store.AuthThrottleRecord(key=key, attempts=0, expires_at=now + _THROTTLE_WINDOW)
                db.add(row)
            if row.attempts >= limit:
                raise HTTPException(429, "Too many sign-in attempts. Please try again in 15 minutes.")
            row.attempts += 1
        db.commit()
    return keys[0][0]


def _throttle_clear(key):
    store = _store()
    with store._SessionLocal() as db:
        db.query(store.AuthThrottleRecord).filter(store.AuthThrottleRecord.key == key).delete()
        db.commit()


def _peer(request):
    return request.client.host if request.client else "unknown"


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


def _email(value):
    value = value.strip().casefold()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise HTTPException(422, "Enter a valid email address.")
    return value


@router.get("/session")
def session_info(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    config = {"mode": mode(), "user": None, "google_client_id": "", "allow_signup": False}
    if mode() == "accounts":
        origin()  # validate configuration even for unauthenticated requests
        config.update(user=principal(request), google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
                      allow_signup=os.getenv("ARIA_AUTH_ALLOW_SIGNUP", "0") == "1")
        if config["google_client_id"]:
            try:
                issued, nonce = request.cookies.get(NONCE_COOKIE, "").split(".", 1)
                if not 0 <= time.time() - int(issued) < 600 or len(nonce) < 32:
                    raise ValueError
            except ValueError:
                nonce = secrets.token_urlsafe(32)
                # Reuse a valid challenge across tabs/status checks, not arbitrary GET rows.
                _cookie(response, NONCE_COOKIE, f"{int(time.time())}.{nonce}", 600)
            config["google_nonce"] = nonce
    return config


_VERIFY_SECONDS = 24 * 3600


def verification_required():
    """Sign-up needs a click on a link sent to the address (SEC-05). ARIA_AUTH_REQUIRE_EMAIL_VERIFICATION=0 keeps instant sign-up,
    for invite-only testing where nobody can register uninvited."""
    return os.getenv("ARIA_AUTH_REQUIRE_EMAIL_VERIFICATION", "1") != "0"


def send_mail(to, subject, body):
    """Mail through the operator's SMTP settings (the feedback form's). Without them: ARIA_AUTH_DEV_MAIL=1 writes the mail to the
    log for local development; otherwise sign-up is unavailable rather than silently unverified."""
    from email.message import EmailMessage
    import smtplib
    import ssl
    from api.routes.feedback import _config
    config = _config()
    if config is None:
        if os.getenv("ARIA_AUTH_DEV_MAIL", "0") == "1":
            from loguru import logger
            logger.warning(f"[dev mail] to={to} subject={subject}\n{body}")
            return
        raise HTTPException(503, "Sign-up email is not configured yet. Please try again later.")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config["sender"], to, subject
    msg.set_content(body)
    try:
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context) if config["security"] == "ssl" else smtplib.SMTP(config["host"], config["port"], timeout=15)
        with server:
            if config["security"] == "starttls":
                server.ehlo(); server.starttls(context=context); server.ehlo()
            if config["username"]:
                server.login(config["username"], config["password"])
            server.send_message(msg)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(502, "The sign-up email could not be sent. Please try again later.") from None


_PENDING_MESSAGE = "If that address can be registered, we have sent a link to confirm it. Open it within 24 hours."


@router.post("/register")
def register(req: Credentials, request: Request, response: Response):
    _accounts(request)
    if os.getenv("ARIA_AUTH_ALLOW_SIGNUP", "0") != "1":
        raise HTTPException(403, "Account registration is disabled.")
    email = _email(req.email)
    _throttle("register|" + email, _peer(request))  # its own budget: signing up does not use up the sign-in attempts
    store = _store()
    encoded = password_hash(req.password)  # always computed, so a taken address costs the same time
    if not verification_required():
        account = {"id": uuid4().hex, "email": email}
        try:
            with store._SessionLocal() as db:
                db.add(store.AccountRecord(**account, password_hash=encoded))
                db.commit()
        except IntegrityError:
            raise HTTPException(409, "This account cannot be created. Try signing in.") from None
        return _session(account, response)
    # Same answer whether or not the address already has an account (SEC-08); only the mail differs.
    with store._SessionLocal() as db:
        exists = db.query(store.AccountRecord).filter_by(email=email).one_or_none() is not None
        token = secrets.token_urlsafe(32)
        if not exists:
            now = time.time()
            db.query(store.PendingAccountRecord).filter(store.PendingAccountRecord.expires_at <= now).delete()
            db.query(store.PendingAccountRecord).filter_by(email=email).delete()  # the newest link replaces older ones
            db.add(store.PendingAccountRecord(token_hash=fingerprint(token), email=email, password_hash=encoded, expires_at=now + _VERIFY_SECONDS))
            db.commit()
    if exists:
        send_mail(email, "ARIA sign-up", "Someone tried to create an ARIA account with this address, which already has one. If it was you, sign in instead. If not, ignore this email.")
    else:
        send_mail(email, "Confirm your ARIA account", f"Open this link within 24 hours to finish creating your ARIA account:\n\n{origin()}/?verify={token}\n\nIf you did not ask for this, ignore this email.")
    response.headers["Cache-Control"] = "no-store"
    return {"pending": True, "message": _PENDING_MESSAGE}


class VerifyRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)


@router.post("/verify")
def verify(req: VerifyRequest, request: Request, response: Response):
    _accounts(request)
    store = _store()
    _throttle("verify|" + fingerprint(req.token), _peer(request))
    with store._SessionLocal() as db:
        row = db.get(store.PendingAccountRecord, fingerprint(req.token))
        if row is None or row.expires_at <= time.time():
            raise HTTPException(400, "This confirmation link is invalid or has expired. Sign up again.")
        account = {"id": uuid4().hex, "email": row.email}
        try:
            db.add(store.AccountRecord(**account, password_hash=row.password_hash))
            db.delete(row)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "This account cannot be created. Try signing in.") from None
    return _session(account, response)


@router.post("/login")
def login(req: Credentials, request: Request, response: Response):
    _accounts(request)
    email = _email(req.email)
    attempt = _throttle(email, _peer(request))
    store = _store()
    with store._SessionLocal() as db:
        row = db.query(store.AccountRecord).filter_by(email=email).one_or_none()
        encoded = row.password_hash if row and row.password_hash else f"{ITERATIONS}${'0'*32}${'0'*64}"
        valid = password_matches(req.password, encoded)
        if not row or not row.password_hash or not valid:
            raise HTTPException(401, "Email or password is incorrect.")
        account = {"id": row.id, "email": row.email}
    _throttle_clear(attempt)  # a successful sign-in does not count against the budget
    return _session(account, response)


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=10, max_length=16384)


def verify_google(credential):
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token
    transport = GoogleRequest()
    def bounded_request(*args, **kwargs):
        kwargs["timeout"] = 10
        return transport(*args, **kwargs)
    return verify_oauth2_token(credential, bounded_request, os.environ["GOOGLE_CLIENT_ID"])


def _google_claims(req, request):
    _accounts(request)
    if not os.getenv("GOOGLE_CLIENT_ID"):
        raise HTTPException(503, "Google sign-in has not been configured.")
    try:
        issued, nonce = request.cookies.get(NONCE_COOKIE, "").split(".", 1)
        age = time.time() - int(issued)
        if age < 0 or age > 600 or len(nonce) < 32:
            raise ValueError
        claims = verify_google(req.credential)  # library validates signature, audience, issuer and expiry
        if claims.get("aud") != os.environ["GOOGLE_CLIENT_ID"] or claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError
        if not claims.get("sub") or claims.get("email_verified") is not True or not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError
        if float(claims.get("exp", 0)) <= time.time():
            raise ValueError
        return str(claims["sub"]), _email(claims["email"])
    except Exception:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.") from None


@router.post("/google")
def google_login(req: GoogleCredential, request: Request, response: Response):
    sub, email = _google_claims(req, request)
    store = _store()
    try:
        with store._SessionLocal() as db:
            row = db.query(store.AccountRecord).filter_by(google_sub=sub).one_or_none()
            if row is None:
                if os.getenv("ARIA_AUTH_ALLOW_SIGNUP", "0") != "1":
                    raise HTTPException(403, "Account registration is disabled.")
                # Never attach a Google identity to an email/password account merely by matching email.
                row = store.AccountRecord(id=uuid4().hex, email=email, google_sub=sub)
                db.add(row)
                db.commit()
            account = {"id": row.id, "email": row.email}
    except IntegrityError:
        raise HTTPException(409, "Sign in with your password first, then link Google from your account menu.") from None
    response.delete_cookie(NONCE_COOKIE, path="/")
    return _session(account, response)


@router.post("/google/link")
def google_link(req: GoogleCredential, request: Request, response: Response):
    account = principal(request)
    if account is None:
        raise HTTPException(401, "Please sign in first.")
    sub, email = _google_claims(req, request)
    if email != account["email"]:
        raise HTTPException(409, "Choose the Google account with the same email address.")
    store = _store()
    try:
        with store._SessionLocal() as db:
            row = db.get(store.AccountRecord, account["id"])
            if row.google_sub and row.google_sub != sub:
                raise HTTPException(409, "A different Google identity is already linked.")
            row.google_sub = sub
            db.commit()
    except IntegrityError:
        raise HTTPException(409, "This Google identity is already linked to another account.") from None
    response.delete_cookie(NONCE_COOKIE, path="/")
    return {"linked": True}


@router.post("/logout")
@router.post("/logout-all")
def logout(request: Request, response: Response):
    _accounts(request)
    store = _store()
    account = principal(request)
    with store._SessionLocal() as db:
        if request.url.path.endswith("logout-all") and account:
            db.query(store.AuthSessionRecord).filter_by(account_id=account["id"]).delete()
        else:
            db.query(store.AuthSessionRecord).filter_by(token_hash=fingerprint(request.cookies.get(COOKIE, ""))).delete()
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(NONCE_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"signed_out": True}


async def authorize(request: HTTPConnection):
    """Global route dependency; private identifiers cannot select another account."""
    if mode() == "private" or request.url.path == "/api/health" or request.url.path.startswith("/api/auth/"):
        yield
        return
    account = principal(request)
    if request.scope["type"] == "websocket":
        if account is None or request.headers.get("origin") != origin():
            raise WebSocketException(code=1008, reason="Please sign in from ARIA.")
        request.scope.setdefault("state", {})["auth_account"] = account
        store = _store()
        account_token = store.authenticated_account.set(account["id"])
        try:
            yield
        finally:
            store.authenticated_account.reset(account_token)
        return
    if account is None:
        raise HTTPException(401, "Please sign in to ARIA.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        same_origin(request)
    path = request.url.path
    if path.startswith(("/api/research/validation", "/api/research/scenario-backtest")):
        raise HTTPException(403, "This shared integration is available only in private mode until account isolation is added.")
    fields = {key: request.query_params.getlist(key) for key in ("owner_id", "session_id")}
    # Whatever the Content-Type says (case, parameters, "+json" types, or none at all: FastAPI parses those as JSON too), a body that
    # parses is checked, so a differently spelled header cannot smuggle another account's id past the owner check.
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media == "multipart/form-data" or media == "application/x-www-form-urlencoded":
        form = await request.form()
        for key in fields:
            fields[key].extend(form.getlist(key))
    elif request.method not in ("GET", "HEAD", "OPTIONS"):
        try:
            body = await request.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            for key in fields:
                if key in body:
                    fields[key].append(body[key])
    if any(value != account["id"] for value in fields["owner_id"]):
        raise HTTPException(403, "This data belongs to another account.")
    financial = path.startswith(("/api/profile", "/api/transactions"))
    if financial and any(value != account["id"] for value in fields["session_id"]):
        raise HTTPException(403, "This data belongs to another account.")
    needs_owner = path.startswith(("/api/chat", "/api/conversations", "/api/instruments/ask", "/api/research/intelligence", "/api/research/reports"))
    if needs_owner and not fields["owner_id"]:
        raise HTTPException(403, "An account owner is required.")
    store = _store()
    token = store.current_owner.set(account["id"])
    account_token = store.authenticated_account.set(account["id"])
    try:
        if path in ("/api/progress", "/api/quiz/answer"):
            from shared.conversation_memory import conversation
            for session_id in fields["session_id"]:
                try:
                    conversation(session_id)
                except PermissionError:
                    raise HTTPException(403, "This conversation belongs to another account.") from None
        audio_token = request.path_params.get("token") if path.startswith("/api/audio/") else request.query_params.get("audio_token") if path == "/avatar/render" else None
        if audio_token:
            with store._SessionLocal() as db:
                row = db.get(store.AudioArtifactRecord, audio_token)
                if row is None or row.owner_id != account["id"]:
                    raise HTTPException(404, "Audio not found or expired.")
        yield
    finally:
        store.authenticated_account.reset(account_token)
        store.current_owner.reset(token)
