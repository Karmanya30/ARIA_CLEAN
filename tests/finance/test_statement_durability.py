"""SQLite atomicity, retries, worker isolation and deletion for statement imports."""
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from shared import statement_store, user_store
from api.main import app

client = TestClient(app)
ROWS = [
    {"date": "2026-10-01", "amount": 250.5, "merchant": "Synthetic Grocer", "category": "food", "direction": "debit"},
    {"date": "2026-10-02", "amount": 50000.0, "merchant": "Synthetic Salary", "category": "income", "direction": "credit"},
]


@pytest.fixture
def owner():
    identity = uuid.uuid4().hex
    yield identity
    user_store.clear_transactions(identity)
    user_store.delete_financial_profile(identity)


def preview(owner, suggested=None):
    return statement_store.create(owner, ROWS, suggested or {"monthly_income": 50000, "expenses": {"food": 250.5}})


def submit(owner, identifier, apply=False):
    return client.post("/api/transactions/import", json={"session_id": owner, "import_id": identifier, "apply_to_profile": apply})


def test_same_request_replays_result_without_overwriting_later_profile_edits(owner):
    identifier = preview(owner)
    first = submit(owner, identifier, True)
    assert first.status_code == 200 and first.json()["imported"] == 2
    user_store.save_financial_profile(owner, monthly_income=90000)
    assert submit(owner, identifier, True).json() == first.json()
    assert len(user_store.get_transactions(owner, kind=None)) == 2
    assert user_store.get_financial_profile(owner)["monthly_income"] == 90000


def test_apply_profile_is_a_separate_explicit_operation(owner):
    identifier = preview(owner)
    first = submit(owner, identifier)
    assert first.json() == {"imported": 2, "duplicates": 0, "profile_updated": False}
    assert user_store.get_financial_profile(owner) is None
    assert submit(owner, identifier, True).json() == {"imported": 0, "duplicates": 2, "profile_updated": True}
    assert submit(owner, identifier).json() == first.json()


def test_profile_failure_rolls_back_rows_profile_and_receipt(owner, monkeypatch):
    identifier = preview(owner)
    user_store.save_financial_profile(owner, monthly_income=90000)
    original = user_store.save_financial_profile
    def fail_after_profile_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic storage failure")
    with monkeypatch.context() as patch:
        patch.setattr(user_store, "save_financial_profile", fail_after_profile_write)
        with pytest.raises(RuntimeError, match="synthetic storage failure"):
            submit(owner, identifier, True)
    assert user_store.get_transactions(owner, kind=None) == []
    assert user_store.get_financial_profile(owner)["monthly_income"] == 90000
    with user_store._SessionLocal() as db:
        assert json.loads(db.get(user_store.StatementPreviewRecord, identifier).results_json) == {}
    assert submit(owner, identifier, True).json()["imported"] == 2


def test_invalid_profile_does_not_partially_import_transactions(owner):
    identifier = preview(owner, {"monthly_income": 1e12})
    assert submit(owner, identifier, True).status_code == 422
    assert user_store.get_transactions(owner, kind=None) == []
    assert user_store.get_financial_profile(owner) is None
    assert submit(owner, identifier).json()["imported"] == 2


@pytest.mark.parametrize("same_preview", [True, False])
def test_parallel_requests_do_not_duplicate_transactions(owner, same_preview):
    identifiers = [preview(owner)]
    identifiers = identifiers * 6 if same_preview else identifiers + [preview(owner) for _ in range(5)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda identity: submit(owner, identity, True), identifiers))
    assert all(r.status_code == 200 for r in responses)
    assert len(user_store.get_transactions(owner, kind=None)) == 2
    if same_preview:
        assert all(r.json() == responses[0].json() for r in responses)
    else:
        assert sum(r.json()["imported"] for r in responses) == 2
        assert sum(r.json()["duplicates"] for r in responses) == 10


def test_separate_processes_share_preview_claim_and_deduplication(owner):
    identifiers = [preview(owner), preview(owner)]
    command = "import json,sys; from shared.statement_store import import_preview; print(json.dumps(import_preview(sys.argv[1],sys.argv[2],True)))"
    env = {**os.environ, "DB_URL": str(user_store._engine.url), "ARIA_WARMUP": "0"}
    processes = [subprocess.Popen([sys.executable, "-c", command, owner, identity], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) for identity in identifiers]
    try:
        outputs = [p.communicate(timeout=60) for p in processes]
        assert all(p.returncode == 0 for p in processes), outputs
        results = [json.loads(out) for out, _ in outputs]
        assert sum(r["imported"] for r in results) == 2
        assert len(user_store.get_transactions(owner, kind=None)) == 2
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)


def test_expiry_and_owner_checks_do_not_expose_or_reuse_preview(owner):
    identifier = preview(owner)
    assert submit("stranger", identifier).status_code == 404
    with user_store._SessionLocal() as db:
        row = db.get(user_store.StatementPreviewRecord, identifier)
        assert row is not None and json.loads(row.results_json) == {}
        row.expires_at = 0
        db.commit()
    assert submit(owner, identifier).status_code == 404
    with user_store._SessionLocal() as db:
        assert db.get(user_store.StatementPreviewRecord, identifier) is None


@pytest.mark.parametrize("action", ["/api/profile", "/api/transactions"])
def test_delete_finance_data_invalidates_pending_preview_and_receipts(owner, action):
    identifier = preview(owner)
    assert submit(owner, identifier).status_code == 200
    assert client.delete(action, params={"session_id": owner}).status_code == 200
    assert submit(owner, identifier).status_code == 404
    assert user_store.get_transactions(owner, kind=None) == []


def test_statement_expense_averages_replace_old_breakdown(owner):
    user_store.save_financial_profile(owner, expenses={"food": 900, "rent": 25000})
    assert submit(owner, preview(owner), True).status_code == 200
    assert user_store.get_financial_profile(owner)["expenses"] == {"food": 250.5}


@pytest.mark.parametrize("amount", ["1e400", "-1e400", "1e12", "0.0001"])
def test_uploaded_invalid_amount_is_rejected_before_preview_storage(owner, amount):
    data = ('[{"date":"2026-10-01","description":"Synthetic Grocer","amount":' + amount + '}]').encode()
    result = client.post("/api/transactions/parse", data={"session_id": owner}, files={"file": ("amount.json", data, "application/json")})
    assert result.status_code == 422
    with user_store._SessionLocal() as db:
        assert db.query(user_store.StatementPreviewRecord).filter_by(owner_id=owner).count() == 0
