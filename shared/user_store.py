"""
shared/user_store.py

SQLite-backed per-user state, keyed by the same session id the UI already
generates (see web/src -- a UUID minted client-side per browser tab).
Tables:

- FinancialProfile — Module 1's risk label + financial inputs.
- LearningState    — Module 2's per-concept mastery vector + interaction history.

Both modules import this module directly; there is no ORM session object
exposed to callers, only plain dict-in/dict-out functions so callers never
need to know SQLAlchemy exists.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from config.paths import USER_PROFILES_DIR

Base = declarative_base()

# DB_URL env override is respected only if it points somewhere other than the
# documented default — otherwise we build an absolute path from config.paths
# so the DB location doesn't depend on the process's working directory.
_DEFAULT_DB_URL = "sqlite:///data/user_profiles/aria.db"
_env_db_url = os.getenv("DB_URL", _DEFAULT_DB_URL)
if _env_db_url == _DEFAULT_DB_URL:
    DB_URL = f"sqlite:///{(USER_PROFILES_DIR / 'aria.db').as_posix()}"
else:
    DB_URL = _env_db_url


class FinancialProfile(Base):
    """Module 1 — user's financial snapshot + latest risk classification."""

    __tablename__ = "financial_profiles"

    user_id = Column(String, primary_key=True)
    monthly_income = Column(Float, default=0.0)
    age = Column(Integer, default=30)
    dependents = Column(Integer, default=0)
    existing_emi = Column(Float, default=0.0)
    emergency_fund_months = Column(Float, default=0.0)
    city_tier = Column(Integer, default=1)
    tax_regime = Column(String, default="new")
    # Stage 12 -- modules/finance/instrument_recommender.py's horizon-fit
    # scoring. horizon_years nullable: "not stated" must stay distinct
    # from "stated as 0", so the scorer can skip horizon adjustments
    # rather than assuming a value.
    goal = Column(String, default="general")
    horizon_years = Column(Float, nullable=True)
    risk_label = Column(String, nullable=True)
    risk_confidence = Column(Float, nullable=True)
    # JSON-encoded list[tuple[str, float]] -- the XGBoost risk model's own
    # SHAP top-3 feature explanation (modules/finance/risk_model.py). Stored
    # so the Profile tab can show *why* a classification was made, not just
    # the label -- otherwise this real, already-computed signal only ever
    # reaches the user filtered through one word in the LLM's narration.
    risk_top_features = Column(Text, default="[]")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TransactionRecord(Base):
    """A user-entered transaction (Profile tab). Feeds Module 1's LSTM spend
    forecast and Isolation Forest anomaly detector, both of which otherwise
    only ever see an empty transaction list in the live chat pipeline."""

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True, nullable=False)
    date = Column(String, nullable=False)  # ISO "YYYY-MM-DD"
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    merchant = Column(String, nullable=True)
    channel = Column(String, nullable=True)  # upi | card | cash | netbanking


class LearningState(Base):
    """Module 2 — per-user concept mastery vector + interaction history."""

    __tablename__ = "learning_state"

    user_id = Column(String, primary_key=True)
    mastery_json = Column(Text, default="{}")  # {concept_id: probability}
    history_json = Column(Text, default="[]")  # [{concept_id, is_correct, ts}]
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


_engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
_SessionLocal = sessionmaker(bind=_engine)
Base.metadata.create_all(_engine)  # creates missing tables only, never columns


def _migrate_add_missing_columns() -> None:
    """Lightweight, dependency-free migration for columns added to an
    existing table after its first deploy (no Alembic at this project's
    scale) -- `create_all` above only creates missing *tables*. Safe to
    call every startup: each ALTER is wrapped so an already-present column
    (the common case) is silently ignored rather than raising."""
    with _engine.begin() as conn:
        for statement in (
            "ALTER TABLE financial_profiles ADD COLUMN risk_top_features TEXT DEFAULT '[]'",
            "ALTER TABLE financial_profiles ADD COLUMN goal TEXT DEFAULT 'general'",
            "ALTER TABLE financial_profiles ADD COLUMN horizon_years REAL",
        ):
            try:
                conn.exec_driver_sql(statement)
            except OperationalError:
                pass  # column already exists


_migrate_add_missing_columns()


# ── Module 1: financial profile ─────────────────────────────────────────
def get_financial_profile(user_id: str) -> dict[str, Any] | None:
    with _SessionLocal() as session:
        row = session.get(FinancialProfile, user_id)
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "monthly_income": row.monthly_income,
            "age": row.age,
            "dependents": row.dependents,
            "existing_emi": row.existing_emi,
            "emergency_fund_months": row.emergency_fund_months,
            "city_tier": row.city_tier,
            "tax_regime": row.tax_regime,
            "goal": row.goal,
            "horizon_years": row.horizon_years,
            "risk_label": row.risk_label,
            "risk_confidence": row.risk_confidence,
            "risk_top_features": json.loads(row.risk_top_features or "[]"),
        }


def save_financial_profile(user_id: str, **fields: Any) -> None:
    if "risk_top_features" in fields and not isinstance(fields["risk_top_features"], str):
        fields["risk_top_features"] = json.dumps(fields["risk_top_features"])
    with _SessionLocal() as session:
        row = session.get(FinancialProfile, user_id)
        if row is None:
            row = FinancialProfile(user_id=user_id)
            session.add(row)
        for key, value in fields.items():
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        session.commit()


# ── Module 1: transactions (Profile tab entry -> feeds forecast + anomaly) ─
def add_transaction(
    user_id: str,
    date: str,
    category: str,
    amount: float,
    merchant: str | None = None,
    channel: str | None = None,
) -> None:
    with _SessionLocal() as session:
        session.add(
            TransactionRecord(
                user_id=user_id,
                date=date,
                category=category,
                amount=amount,
                merchant=merchant,
                channel=channel,
            )
        )
        session.commit()


def get_transactions(user_id: str) -> list[dict[str, Any]]:
    with _SessionLocal() as session:
        rows = (
            session.query(TransactionRecord)
            .filter(TransactionRecord.user_id == user_id)
            .order_by(TransactionRecord.date)
            .all()
        )
        return [
            {
                "id": row.id,
                "date": row.date,
                "category": row.category,
                "amount": row.amount,
                "merchant": row.merchant,
                "channel": row.channel,
            }
            for row in rows
        ]


def clear_transactions(user_id: str) -> None:
    with _SessionLocal() as session:
        session.query(TransactionRecord).filter(TransactionRecord.user_id == user_id).delete()
        session.commit()


def delete_financial_profile(user_id: str) -> None:
    with _SessionLocal() as session:
        row = session.get(FinancialProfile, user_id)
        if row is not None:
            session.delete(row)
            session.commit()


# ── Module 2: learning / mastery state ──────────────────────────────────
def get_learning_state(user_id: str) -> dict[str, Any]:
    with _SessionLocal() as session:
        row = session.get(LearningState, user_id)
        if row is None:
            return {"mastery": {}, "history": []}
        return {
            "mastery": json.loads(row.mastery_json or "{}"),
            "history": json.loads(row.history_json or "[]"),
        }


def save_learning_state(
    user_id: str, mastery: dict[str, float], history: list[dict[str, Any]]
) -> None:
    with _SessionLocal() as session:
        row = session.get(LearningState, user_id)
        if row is None:
            row = LearningState(user_id=user_id)
            session.add(row)
        row.mastery_json = json.dumps(mastery)
        row.history_json = json.dumps(history)
        row.updated_at = datetime.now(timezone.utc)
        session.commit()


def append_learning_interaction(
    user_id: str, concept_id: str, is_correct: bool, mastery: dict[str, float]
) -> None:
    """Convenience wrapper: append one interaction and persist updated mastery."""
    state = get_learning_state(user_id)
    state["history"].append(
        {
            "concept_id": concept_id,
            "is_correct": bool(is_correct),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_learning_state(user_id, mastery, state["history"])
