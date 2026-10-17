import sqlite3
import uuid

import pytest

from api import auth
from scripts.provision_local_account import provision
from shared import user_store as store


def test_provision_preserves_private_records_and_other_owners(tmp_path):
    owner, other = uuid.uuid4().hex, uuid.uuid4().hex
    store.save_financial_profile(owner, monthly_income=80000)
    store.save_financial_profile(other, monthly_income=60000)
    store.add_transactions(owner, [{"date": "2026-10-17", "category": "food", "amount": 400}])
    before_profile = store.get_financial_profile(owner)
    before_transactions = store.get_transactions(owner)
    password = "synthetic-dummy-password-123"
    email = owner + "@example.test"
    result = provision(owner, email, password, tmp_path)
    assert result["existing_records"]["financial_profiles"] == 1
    assert result["original_records_rewritten"] is False
    assert store.get_financial_profile(owner) == before_profile
    assert store.get_transactions(owner) == before_transactions
    assert store.get_financial_profile(other)["monthly_income"] == 60000
    with store._SessionLocal() as db:
        account = db.get(store.AccountRecord, owner)
        assert account.email == email and account.password_hash != password
        assert auth.password_matches(password, account.password_hash)
    with sqlite3.connect(result["backup"]) as db:
        assert db.execute("select count(*) from auth_accounts where id=?", (owner,)).fetchone()[0] == 0
        assert db.execute("select monthly_income from financial_profiles where user_id=?", (owner,)).fetchone()[0] == 80000


def test_nonexistent_private_owner_is_not_claimed(tmp_path):
    owner = uuid.uuid4().hex
    with pytest.raises(ValueError, match="No existing records"):
        provision(owner, owner + "@example.test", "synthetic-password-123", tmp_path)
    with store._SessionLocal() as db:
        assert db.get(store.AccountRecord, owner) is None


def test_existing_account_cannot_be_overwritten_or_merged(tmp_path):
    owner, other = uuid.uuid4().hex, uuid.uuid4().hex
    store.save_financial_profile(owner, monthly_income=80000)
    store.save_financial_profile(other, monthly_income=60000)
    email = owner + "@example.test"
    provision(owner, email, "synthetic-password-123", tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        provision(other, email, "different-password-123", tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        provision(owner, "different-" + email, "different-password-123", tmp_path)
    with store._SessionLocal() as db:
        assert db.get(store.AccountRecord, other) is None
        assert auth.password_matches("synthetic-password-123", db.get(store.AccountRecord, owner).password_hash)
