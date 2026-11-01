"""Send user feedback through the operator's explicitly configured SMTP server."""
from __future__ import annotations

from collections import OrderedDict
from email.headerregistry import Address
from email.message import EmailMessage
import os
import re
import smtplib
import ssl
from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api import auth

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
_lock = Lock()
_attempts: OrderedDict[str, list[float]] = OrderedDict()
_WINDOW = 600
_MAX_ATTEMPTS = 5
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")


def _address(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not _EMAIL.fullmatch(value) or '..' in value or '\r' in value or '\n' in value:
        raise ValueError("Enter a valid email address.")
    return value


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    discovery: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=50)
    message: str = Field(min_length=10, max_length=5000)

    @field_validator("name", "discovery", "category")
    @classmethod
    def single_line(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Please use a single line of text.")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _address(value)


def _config() -> dict | None:
    host = os.getenv("ARIA_SMTP_HOST", "").strip()
    sender = os.getenv("ARIA_SMTP_FROM", "").strip()
    recipient = os.getenv("ARIA_FEEDBACK_TO", "").strip()
    username = os.getenv("ARIA_SMTP_USERNAME", "").strip()
    password = os.getenv("ARIA_SMTP_PASSWORD", "")
    security = os.getenv("ARIA_SMTP_SECURITY", "starttls").strip().lower()
    try:
        port = int(os.getenv("ARIA_SMTP_PORT", "465" if security == "ssl" else "587"))
        if (not host or not sender or not recipient or security not in ("ssl", "starttls")
                or not 1 <= port <= 65535 or bool(username) != bool(password)):
            return None
        recipients = [_address(value) for value in recipient.split(',')]
        if len(recipients) > 10 or len(set(address.casefold() for address in recipients)) != len(recipients):
            return None
        return {"host": host, "port": port, "sender": _address(sender), "recipients": recipients,
                "username": username, "password": password, "security": security}
    except (ValueError, TypeError):
        return None


def _rate_limit(request: Request) -> None:
    peer = request.client.host if request.client else "unknown"
    now = monotonic()
    with _lock:
        attempts = [t for t in _attempts.pop(peer, []) if now - t < _WINDOW]
        if len(attempts) >= _MAX_ATTEMPTS:
            _attempts[peer] = attempts
            raise HTTPException(429, "Too many feedback attempts. Please try again later.", headers={"Retry-After": "600"})
        _attempts[peer] = [*attempts, now]
        while len(_attempts) > 4096:
            _attempts.popitem(last=False)


@router.get("/status")
def status(response: Response) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    return {"configured": _config() is not None}


@router.post("")
def send_feedback(body: Feedback, request: Request, response: Response) -> dict[str, bool]:
    # Protect even private mode from a third-party page using the local app as a mail relay.
    auth.same_origin(request)
    config = _config()
    if config is None:
        raise HTTPException(503, "Feedback email is not configured yet. Please try again later.")
    _rate_limit(request)
    msg = EmailMessage()
    msg["From"] = config["sender"]
    msg["To"] = ', '.join(config["recipients"])
    msg["Reply-To"] = Address(display_name=body.name, addr_spec=body.email)
    msg["Subject"] = "ARIA feedback"
    msg.set_content(f"Name: {body.name}\nEmail: {body.email}\nHow they heard about ARIA: {body.discovery}\nCategory: {body.category}\n\nFeedback:\n{body.message}\n")
    try:
        context = ssl.create_default_context()
        if config["security"] == "ssl":
            server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context)
        else:
            server = smtplib.SMTP(config["host"], config["port"], timeout=15)
        with server:
            if config["security"] == "starttls":
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if config["username"]:
                server.login(config["username"], config["password"])
            refused = server.send_message(msg)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
    except (OSError, smtplib.SMTPException, ValueError):
        # Do not expose credentials, message contents or provider diagnostics.
        raise HTTPException(502, "Feedback could not be sent. Please try again later.") from None
    response.headers["Cache-Control"] = "no-store"
    return {"sent": True}
