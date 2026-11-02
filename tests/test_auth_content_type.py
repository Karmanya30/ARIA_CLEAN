"""QA-AUTH-001: the owner check must read the request body whatever the Content-Type header says."""
import json

import pytest

from tests.test_accounts import accounts, register  # noqa: F401
from fastapi.testclient import TestClient
from api.main import app

TYPES = ["Application/JSON", "application/JSON; charset=utf-8", "application/vnd.api+json", None]


def _other(accounts):
    victim = register(accounts)
    attacker_client = TestClient(app, headers={"Origin": "http://testserver"})
    attacker = register(attacker_client)
    return victim, attacker, attacker_client


@pytest.mark.parametrize("ctype", TYPES)
def test_another_accounts_id_in_the_body_is_refused_for_any_content_type(accounts, ctype):
    victim, _attacker, client = _other(accounts)
    headers = {"Content-Type": ctype} if ctype else {"Content-Type": ""}
    r = client.post("/api/profile", content=json.dumps({"session_id": victim["id"], "monthly_income": 1}), headers=headers)
    assert r.status_code in (403, 415), (ctype, r.status_code, r.text)
    r = client.post("/api/chat", content=json.dumps({"query": "hi", "session_id": "x", "owner_id": victim["id"], "request_id": "r1"}), headers=headers)
    assert r.status_code in (403, 415), (ctype, r.status_code, r.text)
    with __import__("shared.user_store", fromlist=["x"])._SessionLocal() as db:
        from shared import user_store as store
        assert store.get_financial_profile(victim["id"]) in (None, {}) or "monthly_income" not in (store.get_financial_profile(victim["id"]) or {})


def test_own_id_still_works_with_a_normal_json_header(accounts):
    me = register(accounts)
    r = accounts.post("/api/profile", json={"session_id": me["id"], "monthly_income": 50000})
    assert r.status_code == 200, r.text
