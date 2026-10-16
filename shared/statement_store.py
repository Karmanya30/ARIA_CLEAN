"""Durable SQLite statement previews and atomic, idempotent imports.

Only normalized rows are stored, never the original file. Preview access and
retry receipts expire together. Pruning occurs on parse/import, not a timer.
"""
from __future__ import annotations

import json
import time
import uuid

from shared import user_store as store

TTL_SECONDS = 600


class PreviewExpired(LookupError):
    pass


def create(owner: str, rows: list[dict], suggested: dict) -> str:
    preview_id, now = uuid.uuid4().hex, time.time()
    with store._SessionLocal() as db:
        db.query(store.StatementPreviewRecord).filter(store.StatementPreviewRecord.expires_at <= now).delete()
        db.add(store.StatementPreviewRecord(id=preview_id, owner_id=owner, expires_at=now + TTL_SECONDS,
            rows_json=json.dumps(rows), suggested_json=json.dumps(suggested), results_json="{}"))
        db.commit()
    return preview_id


def _key(date, amount, merchant, kind):
    return (date, round(float(amount), 2), (merchant or "").casefold(), kind or "expense")


def import_preview(owner: str, preview_id: str, apply_profile: bool = False) -> dict:
    from modules.finance.statement_import import EXPENSE_KEYS, to_store_category

    with store._SessionLocal() as db:
        # Claim the SQLite writer before any read/deduplication. This serializes
        # workers/processes and overlapping preview IDs, not only local threads.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        now = time.time()
        db.query(store.StatementPreviewRecord).filter(store.StatementPreviewRecord.expires_at <= now).delete()
        preview = db.get(store.StatementPreviewRecord, preview_id)
        if preview is None or preview.owner_id != owner:
            db.commit()  # Persist expiry pruning even when the requested preview is missing.
            raise PreviewExpired("That import has expired. Please upload the file again.")
        results = json.loads(preview.results_json)
        operation = "profile" if apply_profile else "transactions"
        if operation in results:
            db.commit()
            return results[operation]
        rows, suggested = json.loads(preview.rows_json), json.loads(preview.suggested_json)
        existing = db.query(store.TransactionRecord).filter(store.TransactionRecord.user_id == owner).all()
        seen = {_key(t.date, t.amount, t.merchant, t.kind) for t in existing}
        batch, duplicates = [], 0
        for row in rows:
            income = row["direction"] == "credit" and row["category"] == "income"
            if not income and (row["direction"] != "debit" or row["category"] == "investment" or row["category"] not in (*EXPENSE_KEYS, "emi")):
                continue
            kind = "income" if income else "expense"
            key = _key(row["date"], row["amount"], row["merchant"], kind)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            batch.append({"user_id": owner, "date": row["date"], "category": "income" if income else to_store_category(row["category"]),
                          "amount": row["amount"], "merchant": row["merchant"], "channel": "statement", "kind": kind})
        if batch:
            db.execute(store.TransactionRecord.__table__.insert(), batch)
        fields = {k: v for k, v in suggested.items() if v}
        if apply_profile and fields:
            profile = db.get(store.FinancialProfile, owner)
            details = json.loads(profile.details_json or "{}") if profile else {}
            loans = details.get("loans")
            if fields.get("expenses"):
                fields["expenses"] = {**{k: None for k in details.get("expenses", {}) if k not in fields["expenses"]}, **fields["expenses"]}
            emis = [r for r in rows if r["direction"] == "debit" and r["category"] == "emi"]
            if emis and not loans:
                first, last = min(r["date"] for r in rows), max(r["date"] for r in rows)
                months = (int(last[:4]) - int(first[:4])) * 12 + int(last[5:7]) - int(first[5:7]) + 1
                fields["loans"] = [{"kind": "other", "emi": round(sum(r["amount"] for r in emis) / months)}]
            store.save_financial_profile(owner, source="form", _session=db, **fields)
        result = {"imported": len(batch), "duplicates": duplicates, "profile_updated": bool(apply_profile and fields)}
        results[operation] = result
        preview.results_json = json.dumps(results)
        db.commit()  # Transactions, profile changes and receipt commit together.
        return result
