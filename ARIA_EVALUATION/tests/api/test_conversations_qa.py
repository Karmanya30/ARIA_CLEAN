"""QA probes for /api/conversations beyond tests/test_conversation_history.py: validation edges, non-ASCII export,
accounts-mode authorisation (PATCH/DELETE/PUT/export across accounts, CSRF, no cookie). Synthetic owner ids only."""
import uuid
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from tests.test_accounts import PASSWORD, accounts, register  # noqa: F401
from tests.test_conversation_history import seed

C = TestClient(app, raise_server_exceptions=False)  # a 500 is returned as a status, as in production


@pytest.fixture
def own():
    o = uuid.uuid4().hex
    return o, seed(o, "synthetic question about index funds")


def url(sid, tail=""):
    return f"/api/conversations/{sid}{tail}"


# ---- validation -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -5}, {"limit": 10**9}, {"offset": -1}, {"q": "%" * 500}, {"q": "_" * 50},
                                    {"q": "\\"}, {"q": "' OR 1=1 --"}, {"q": "हिंदी"}, {"q": "a" * 5000}])
def test_list_never_5xx_on_odd_params(own, params):
    o, _ = own
    assert C.get("/api/conversations", params={"owner_id": o, **params}).status_code == 200


@pytest.mark.parametrize("params", [{"limit": "x"}, {"offset": "x"}, {"archived": "maybe"}])
def test_list_bad_types_are_422(own, params):
    o, _ = own
    assert C.get("/api/conversations", params={"owner_id": o, **params}).status_code == 422


def test_list_limit_is_capped_at_100(own):
    o, _ = own
    for i in range(3):
        seed(o, f"q{i}")
    assert len(C.get("/api/conversations", params={"owner_id": o, "limit": 10**9}).json()["items"]) == 4


@pytest.mark.parametrize("body,code", [({}, 422), ({"title": None}, 422), ({"title": "   "}, 422), ({"title": 5}, 422),
                                       ({"pinned": "maybe"}, 422), ({"archived": []}, 422), ({"title": "x" * 10_000}, 200),
                                       ({"title": "<script>alert(1)</script>"}, 200)])
def test_patch_validation(own, body, code):
    o, sid = own
    r = C.patch(url(sid), params={"owner_id": o}, json=body)
    assert r.status_code == code, r.text
    if code == 200 and "title" in body:
        assert len(r.json()["title"]) <= 120  # stored truncated; the UI must escape it (React does)


def test_patch_not_json_and_list_body(own):
    o, sid = own
    assert C.patch(url(sid), params={"owner_id": o}, content=b"{x", headers={"content-type": "application/json"}).status_code == 422
    assert C.patch(url(sid), params={"owner_id": o}, json=["a"]).status_code == 422


def test_patch_invalid_title_with_valid_flag_has_no_partial_effect(own):
    o, sid = own
    assert C.patch(url(sid), params={"owner_id": o}, json={"title": "  ", "pinned": True}).status_code == 422
    assert C.get("/api/conversations", params={"owner_id": o}).json()["items"][0]["pinned"] is False


def test_archive_clears_pin(own):
    o, sid = own
    C.patch(url(sid), params={"owner_id": o}, json={"pinned": True})
    r = C.patch(url(sid), params={"owner_id": o}, json={"archived": True})
    assert r.json()["pinned"] is False and r.json()["archived"] is True


@pytest.mark.parametrize("rating", [True, 1.0, "1", 2, 0, "up"])
def test_rating_edges(own, rating):
    o, sid = own
    mid = C.get(url(sid, "/messages"), params={"owner_id": o}).json()["turns"][0]["message_id"]
    r = C.put(url(sid, f"/messages/{mid}/rating"), params={"owner_id": o}, json={"rating": rating})
    assert r.status_code in (200, 422), r.text  # never 500


def test_rating_null_clears_and_message_id_must_be_int(own):
    o, sid = own
    mid = C.get(url(sid, "/messages"), params={"owner_id": o}).json()["turns"][0]["message_id"]
    assert C.put(url(sid, f"/messages/{mid}/rating"), params={"owner_id": o}, json={"rating": 1}).status_code == 200
    assert C.put(url(sid, f"/messages/{mid}/rating"), params={"owner_id": o}, json={"rating": None}).status_code == 200
    assert C.get(url(sid, "/messages"), params={"owner_id": o}).json()["turns"][0]["rating"] is None
    assert C.put(url(sid, "/messages/abc/rating"), params={"owner_id": o}, json={"rating": 1}).status_code == 422


def test_rating_a_message_of_another_conversation_is_404(own):
    o, sid = own
    other = seed(o, "second chat")
    mid = C.get(url(other, "/messages"), params={"owner_id": o}).json()["turns"][0]["message_id"]
    assert C.put(url(sid, f"/messages/{mid}/rating"), params={"owner_id": o}, json={"rating": 1}).status_code == 404


def test_messages_paging_params(own):
    o, sid = own
    for p in ({"limit": 0}, {"limit": -1}, {"limit": 10**9}, {"before": 0}, {"before": -3}, {"before": 10**15}):
        assert C.get(url(sid, "/messages"), params={"owner_id": o, **p}).status_code == 200, p


def test_unknown_and_odd_ids_are_404_not_500(own):
    o, _ = own
    for cid in ("nope", "0" * 300, "%00", "a b", "..%2f..%2fetc"):
        assert C.get(f"/api/conversations/{cid}/messages", params={"owner_id": o}).status_code in (404, 422), cid


def test_export_formats(own):
    o, sid = own
    assert C.get(url(sid, "/export"), params={"owner_id": o, "format": "bogus"}).headers["content-type"].startswith("application/json")
    md = C.get(url(sid, "/export"), params={"owner_id": o, "format": "md"})
    assert md.headers["content-type"].startswith("text/markdown") and md.text.startswith("# ")


def test_export_with_non_ascii_title_does_not_500(own):
    """QA-CONV-001: Content-Disposition filename is built with str.isalnum(), which keeps non-Latin-1 letters; headers are latin-1."""
    o, sid = own
    assert C.patch(url(sid), params={"owner_id": o}, json={"title": "निवेश योजना"}).status_code == 200
    r = C.get(url(sid, "/export"), params={"owner_id": o})
    assert r.status_code == 200, f"export of a Devanagari-titled chat returned {r.status_code}"


def test_like_escape_has_no_invalid_escape_warning():
    """QA-CONV-002: shared/conversation_history._like uses "\\%" in a plain string literal (SyntaxWarning on 3.12+)."""
    src = Path("shared/conversation_history.py").read_text(encoding="utf-8")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        compile(src, "conversation_history.py", "exec")
    assert not [x for x in w if "invalid escape" in str(x.message)]


def test_delete_twice_and_after_delete_everything_404(own):
    o, sid = own
    assert C.delete(url(sid), params={"owner_id": o}).status_code == 200
    for r in (C.delete(url(sid), params={"owner_id": o}), C.patch(url(sid), params={"owner_id": o}, json={"title": "x"}),
              C.get(url(sid, "/export"), params={"owner_id": o})):
        assert r.status_code == 404


def test_owner_required(own):
    _, sid = own
    for r in (C.get("/api/conversations"), C.get("/api/conversations", params={"owner_id": ""}), C.delete(url(sid))):
        assert r.status_code == 403


# ---- accounts mode: authorisation -------------------------------------------------------------------------------------------
def test_accounts_cross_account_mutations_and_csrf(accounts):
    victim = register(accounts)
    sid = seed(victim["id"], "victim private question")
    attacker_client = TestClient(app, headers={"Origin": "http://testserver"}, raise_server_exceptions=False)
    attacker = register(attacker_client)
    for owner in (victim["id"], attacker["id"]):  # naming the victim = 403 (authorize); naming itself = 404 (not the owner)
        want = 403 if owner == victim["id"] else 404
        assert attacker_client.patch(url(sid), params={"owner_id": owner}, json={"title": "pwn"}).status_code == want
        assert attacker_client.delete(url(sid), params={"owner_id": owner}).status_code == want
        assert attacker_client.get(url(sid, "/export"), params={"owner_id": owner}).status_code == want
        assert attacker_client.put(url(sid, "/messages/1/rating"), params={"owner_id": owner}, json={"rating": 1}).status_code == want
    # owner_id smuggled in the body is checked too
    assert attacker_client.patch(url(sid), params={"owner_id": attacker["id"]}, json={"title": "x", "owner_id": victim["id"]}).status_code == 403
    assert accounts.get(url(sid, "/messages"), params={"owner_id": victim["id"]}).status_code == 200
    # CSRF: state-changing calls with a valid cookie but no / foreign Origin are refused
    no_origin = TestClient(app, raise_server_exceptions=False)
    no_origin.cookies.update(accounts.cookies)
    assert no_origin.delete(url(sid), params={"owner_id": victim["id"]}).status_code == 403
    evil = TestClient(app, headers={"Origin": "https://evil.example"}, raise_server_exceptions=False)
    evil.cookies.update(accounts.cookies)
    assert evil.patch(url(sid), params={"owner_id": victim["id"]}, json={"title": "x"}).status_code == 403
    assert accounts.get(url(sid, "/messages"), params={"owner_id": victim["id"]}).status_code == 200


def test_accounts_anonymous_gets_401_everywhere(accounts):
    anon = TestClient(app, headers={"Origin": "http://testserver"}, raise_server_exceptions=False)
    for m, p in (("get", "/api/conversations"), ("patch", "/api/conversations/x"), ("delete", "/api/conversations/x"),
                 ("get", "/api/conversations/x/export"), ("get", "/api/profile"), ("post", "/api/chat"), ("get", "/api/markets/overview"),
                 ("post", "/api/voice/transcribe"), ("get", "/avatar/live"), ("get", "/api/instruments/search")):
        assert getattr(anon, m)(p).status_code == 401, p
    assert anon.get("/api/health").status_code == 200
