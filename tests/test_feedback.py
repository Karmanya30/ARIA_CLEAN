"""Feedback validation and SMTP delivery using an in-process SMTP double."""
from __future__ import annotations

import smtplib

from fastapi.testclient import TestClient
import pytest

from api.main import app
from api.routes import feedback

PAYLOAD = {"name": "Ada User", "email": "ada@example.test", "discovery": "University", "category": "Bug", "message": "The chart does not load after opening it."}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for key, value in {"ARIA_AUTH_MODE": "private", "ARIA_APP_ORIGIN": "http://testserver",
                       "ARIA_SMTP_HOST": "smtp.example.test", "ARIA_SMTP_PORT": "587", "ARIA_SMTP_SECURITY": "starttls",
                       "ARIA_SMTP_USERNAME": "sender@example.test", "ARIA_SMTP_PASSWORD": "secret-for-test",
                       "ARIA_SMTP_FROM": "sender@example.test", "ARIA_FEEDBACK_TO": "team@example.test"}.items():
        monkeypatch.setenv(key, value)
    feedback._attempts.clear()
    yield
    feedback._attempts.clear()


@pytest.fixture
def client():
    return TestClient(app, headers={"Origin": "http://testserver"})


class FakeSMTP:
    calls = []
    refusal = {}
    fail = False

    def __init__(self, host, port, timeout, **kwargs):
        self.calls.append(("connect", host, port, timeout, bool(kwargs.get("context"))))
        if self.fail:
            raise OSError("secret provider detail")

    def __enter__(self): return self
    def __exit__(self, *_): return None
    def ehlo(self): self.calls.append(("ehlo",))
    def starttls(self, *, context): self.calls.append(("tls", bool(context)))
    def login(self, username, password): self.calls.append(("login", username, password))
    def send_message(self, msg):
        self.calls.append(("message", msg))
        return self.refusal


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.calls = []
    FakeSMTP.refusal = {}
    FakeSMTP.fail = False
    monkeypatch.setattr(feedback.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(feedback.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_delivery_uses_tls_and_sender_reply_to(client, smtp):
    assert client.get('/api/feedback/status').json() == {"configured": True}
    result = client.post('/api/feedback', json=PAYLOAD)
    assert result.status_code == 200 and result.json() == {"sent": True}
    assert ("tls", True) in smtp.calls
    msg = next(c[1] for c in smtp.calls if c[0] == "message")
    assert str(msg["From"]) == "sender@example.test"
    assert str(msg["To"]) == "team@example.test"
    assert "ada@example.test" in str(msg["Reply-To"])
    assert all(value in msg.get_content() for value in PAYLOAD.values())


def test_multiple_recipients_receive_the_same_message(client, smtp, monkeypatch):
    monkeypatch.setenv('ARIA_FEEDBACK_TO', 'first@example.test, second@example.test')
    assert client.post('/api/feedback', json=PAYLOAD).json() == {'sent': True}
    msg = next(c[1] for c in smtp.calls if c[0] == 'message')
    assert [address.addr_spec for address in msg['To'].addresses] == ['first@example.test', 'second@example.test']


@pytest.mark.parametrize('recipients', ['first@example.test,invalid', 'first@example.test,', 'first@example.test,FIRST@example.test'])
def test_invalid_recipient_lists_are_unavailable(client, monkeypatch, recipients):
    monkeypatch.setenv('ARIA_FEEDBACK_TO', recipients)
    assert client.get('/api/feedback/status').json() == {'configured': False}
    assert client.post('/api/feedback', json=PAYLOAD).status_code == 503


def test_ssl_and_unauthenticated_relay_configuration(client, smtp, monkeypatch):
    monkeypatch.setenv("ARIA_SMTP_SECURITY", "ssl")
    monkeypatch.setenv("ARIA_SMTP_PORT", "465")
    monkeypatch.delenv("ARIA_SMTP_USERNAME")
    monkeypatch.delenv("ARIA_SMTP_PASSWORD")
    assert client.post('/api/feedback', json=PAYLOAD).status_code == 200
    assert smtp.calls[0] == ("connect", "smtp.example.test", 465, 15, True)
    assert not any(c[0] in ("tls", "login") for c in smtp.calls)


def test_missing_or_invalid_config_fails_closed(client, monkeypatch):
    monkeypatch.delenv("ARIA_FEEDBACK_TO")
    assert client.get('/api/feedback/status').json() == {"configured": False}
    assert client.post('/api/feedback', json=PAYLOAD).status_code == 503
    monkeypatch.setenv("ARIA_FEEDBACK_TO", "team@example.test")
    monkeypatch.setenv("ARIA_SMTP_SECURITY", "none")
    assert client.get('/api/feedback/status').json() == {"configured": False}


@pytest.mark.parametrize("field,value", [("name", "X\r\nCc: evil@example.test"), ("email", "x@example.test\r\nBcc:evil@example.test"),
                                        ("email", "not-an-email"), ("discovery", "web\nExtra"), ("message", "short"), ("message", "x" * 5001)])
def test_bad_inputs_never_reach_smtp(client, smtp, field, value):
    result = client.post('/api/feedback', json={**PAYLOAD, field: value})
    assert result.status_code == 422
    assert smtp.calls == []


def test_foreign_origin_and_unauthenticated_account_rejected(client, smtp, monkeypatch):
    assert client.post('/api/feedback', headers={"Origin": "https://evil.example"}, json=PAYLOAD).status_code == 403
    monkeypatch.setenv("ARIA_AUTH_MODE", "accounts")
    assert client.post('/api/feedback', json=PAYLOAD).status_code == 401
    assert smtp.calls == []


def test_signed_in_account_can_send(client, smtp, monkeypatch):
    from uuid import uuid4
    monkeypatch.setenv("ARIA_AUTH_MODE", "accounts")
    monkeypatch.setenv("ARIA_AUTH_ALLOW_SIGNUP", "1")
    monkeypatch.setenv("ARIA_AUTH_REQUIRE_EMAIL_VERIFICATION", "0")
    registered = client.post('/api/auth/register', json={"email": uuid4().hex + "@example.test", "password": "long-test-password-123"})
    assert registered.status_code == 200
    assert client.post('/api/feedback', json=PAYLOAD).json() == {"sent": True}


def test_failure_is_not_reported_as_success_or_leaked(client, smtp):
    smtp.fail = True
    result = client.post('/api/feedback', json=PAYLOAD)
    assert result.status_code == 502 and "secret" not in result.text and "sent" not in result.json()
    smtp.fail = False
    smtp.refusal = {"team@example.test": (550, b"refused")}
    assert client.post('/api/feedback', json=PAYLOAD).status_code == 502


def test_rate_limit_is_bounded(client, smtp):
    for _ in range(5):
        assert client.post('/api/feedback', json=PAYLOAD).status_code == 200
    assert client.post('/api/feedback', json=PAYLOAD).status_code == 429
    assert sum(c[0] == "message" for c in smtp.calls) == 5
