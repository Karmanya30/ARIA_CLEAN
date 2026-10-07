"""Module 1's transaction entry -- feeds the LSTM spend forecaster and
Isolation Forest anomaly detector, which otherwise only ever see an empty
list (see modules/finance/pipeline.py's _load_transactions)."""
from __future__ import annotations

import random
import time
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from modules.finance.statement_import import EXPENSE_KEYS as _EXPENSE

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionRequest(BaseModel):
    session_id: str
    date: str
    category: str
    amount: float
    merchant: str | None = None
    channel: str | None = None


@router.get("")
def list_transactions(session_id: str) -> list[dict[str, Any]]:
    from shared.user_store import get_transactions

    return get_transactions(session_id)


@router.post("")
def add_transaction(req: TransactionRequest) -> dict[str, str]:
    from shared.user_store import add_transaction

    add_transaction(
        req.session_id, date=req.date, category=req.category, amount=req.amount,
        merchant=req.merchant, channel=req.channel,
    )
    return {"status": "added"}


_MAX_BYTES = 5 * 1024 * 1024
_TTL = 600
_imports: dict[str, tuple[float, str, list[dict], dict]] = {}  # import_id -> (expires, session_id, rows, suggested)


@router.post("/parse")
def parse_statement_file(file: UploadFile = File(...), session_id: str = Form(...)) -> dict[str, Any]:
    """Parse an uploaded statement/transaction file in memory. The file itself is never stored; only the
    normalized transactions are kept server-side for 10 minutes (so /import can use them), then dropped."""
    from modules.finance import statement_import as si

    data = file.file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, "That file is larger than 5 MB. Please upload a shorter period.")
    try:
        parsed = si.parse_statement(file.filename or "", data)
        info = si.summarize(parsed["rows"])
    except si.StatementError as exc:
        raise HTTPException(exc.status, exc.message)
    except Exception:  # never leak internals or file contents
        raise HTTPException(422, "Sorry, I couldn't read that file. Try CSV or Excel.")
    now = time.time()
    for k in [k for k, v in _imports.items() if v[0] < now]:
        del _imports[k]
    import_id = uuid.uuid4().hex
    _imports[import_id] = (now + _TTL, session_id, parsed["rows"], info["suggested_profile"])
    return {
        "filename": file.filename, "format": parsed["format"], "rows_total": len(parsed["rows"]),
        "importable": sum(1 for r in parsed["rows"] if r["direction"] == "debit" and r["category"] != "investment" and r["category"] in (*_EXPENSE, "emi")),
        "rows": parsed["rows"][:200], "skipped": parsed["skipped"], "warnings": parsed["warnings"],
        **info, "import_id": import_id,
    }


class ImportRequest(BaseModel):
    session_id: str
    import_id: str
    apply_to_profile: bool = False


@router.post("/import")
def import_statement(req: ImportRequest) -> dict[str, Any]:
    """Save a parsed statement's expense/EMI debits as transactions (skipping ones already stored) and, only
    when apply_to_profile is true, its suggested expenses/income into the profile."""
    from modules.finance.statement_import import to_store_category
    from shared.user_store import add_transaction, get_transactions, save_financial_profile

    entry = _imports.get(req.import_id)
    if not entry or entry[0] < time.time() or entry[1] != req.session_id:
        raise HTTPException(404, "That import has expired. Please upload the file again.")
    _, _, rows, suggested = entry
    seen = {(t["date"], round(t["amount"], 2), (t["merchant"] or "").lower()) for t in get_transactions(req.session_id)}
    imported = duplicates = 0
    for r in rows:
        if r["direction"] != "debit" or r["category"] == "investment" or r["category"] not in (*_EXPENSE, "emi"):
            continue
        key = (r["date"], r["amount"], r["merchant"].lower())
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        add_transaction(req.session_id, date=r["date"], category=to_store_category(r["category"]),
                        amount=r["amount"], merchant=r["merchant"], channel="statement")
        imported += 1
    fields = {k: v for k, v in suggested.items() if v}
    if req.apply_to_profile and fields:
        save_financial_profile(req.session_id, source="form", **fields)
    return {"imported": imported, "duplicates": duplicates, "profile_updated": bool(req.apply_to_profile and fields)}


@router.delete("")
def clear_all_transactions(session_id: str) -> dict[str, str]:
    from shared.user_store import clear_transactions

    clear_transactions(session_id)
    return {"status": "cleared"}


@router.post("/sample")
def load_sample_transactions(req: dict[str, str]) -> dict[str, str]:
    """Deterministic synthetic transactions spanning two months, including
    one deliberate outlier -- enough to clear anomaly.py's MIN_TRANSACTIONS
    (10) and give the forecaster a real multi-month sequence, so trying the
    forecast/anomaly models doesn't require manually adding 15+ rows."""
    from shared.user_store import add_transaction

    session_id = req["session_id"]
    rng = random.Random(f"sample_txns_{session_id}")
    today = date.today()
    rows = [
        (5, "housing", 18000, "Rent", "netbanking"),
        (7, "food", 3200, "BigBasket", "upi"),
        (12, "food", 850, "Zomato", "upi"),
        (14, "transport", 1200, "Ola", "upi"),
        (18, "utilities", 2400, "Electricity Board", "netbanking"),
        (20, "entertainment", 600, "Netflix", "card"),
        (25, "food", 4100, "Local Market", "cash"),
        (35, "housing", 18000, "Rent", "netbanking"),
        (38, "food", 2900, "BigBasket", "upi"),
        (42, "transport", 950, "Uber", "upi"),
        (45, "medical", 1500, "Apollo Pharmacy", "card"),
        (48, "utilities", 2600, "Electricity Board", "netbanking"),
        (52, "other", 55000, "Electronics Store", "card"),  # deliberate outlier
        (55, "entertainment", 700, "Netflix", "card"),
        (58, "food", 3400, "BigBasket", "upi"),
    ]
    for days_ago, category, amount, merchant, channel in rows:
        jitter = rng.randint(-50, 50)
        add_transaction(
            session_id,
            date=(today - timedelta(days=days_ago)).isoformat(),
            category=category,
            amount=max(1.0, amount + jitter),
            merchant=merchant,
            channel=channel,
        )
    return {"status": "loaded", "count": str(len(rows))}
