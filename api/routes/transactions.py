"""Module 1's transaction entry -- feeds the LSTM spend forecaster and
Isolation Forest anomaly detector, which otherwise only ever see an empty
list (see modules/finance/pipeline.py's _load_transactions)."""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Literal
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from modules.finance.statement_import import EXPENSE_KEYS as _EXPENSE

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    date: date
    category: Literal["housing", "food", "transport", "utilities", "emi", "entertainment", "medical", "other"]
    amount: float = Field(gt=0, le=1e11, allow_inf_nan=False)
    merchant: str | None = Field(None, max_length=300)
    channel: Literal["upi", "card", "cash", "netbanking"] | None = None


@router.get("")
def list_transactions(session_id: str) -> list[dict[str, Any]]:
    from shared.user_store import get_transactions

    return get_transactions(session_id)


@router.get("/insights")
def transaction_insights(session_id: str) -> dict[str, Any]:
    from modules.finance.spending import insights
    from shared.user_store import get_financial_profile, get_transactions

    return insights(get_transactions(session_id), get_financial_profile(session_id), get_transactions(session_id, kind="income"))


@router.post("")
def add_transaction(req: TransactionRequest) -> dict[str, str]:
    from shared.user_store import add_transaction

    add_transaction(
        req.session_id, date=req.date.isoformat(), category=req.category, amount=req.amount,
        merchant=req.merchant, channel=req.channel,
    )
    return {"status": "added"}


_MAX_BYTES = 5 * 1024 * 1024


@router.post("/parse")
def parse_statement_file(file: UploadFile = File(...), session_id: str = Form(...)) -> dict[str, Any]:
    """Parse in memory; keep an owner-scoped normalized preview with a 10-minute expiry.
    The original file is never stored. The preview survives worker/API restarts."""
    from modules.finance import statement_import as si
    from shared import statement_store

    if not session_id.strip() or len(session_id) > 200:
        raise HTTPException(422, "session_id must be nonblank and at most 200 characters")

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
    import_id = statement_store.create(session_id, parsed["rows"], info["suggested_profile"])
    return {
        "filename": file.filename, "format": parsed["format"], "rows_total": len(parsed["rows"]),
        "importable": sum(1 for r in parsed["rows"] if r["direction"] == "debit" and r["category"] != "investment" and r["category"] in (*_EXPENSE, "emi")),
        "rows": parsed["rows"][:200], "skipped": parsed["skipped"], "warnings": parsed["warnings"],
        **info, "import_id": import_id,
    }


class ImportRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    import_id: str = Field(min_length=1, max_length=200)
    apply_to_profile: bool = False


@router.post("/import")
def import_statement(req: ImportRequest) -> dict[str, Any]:
    """Save a parsed statement's expense/EMI debits (and salary-like credits, as kind=income) as transactions,
    skipping ones already stored, in one bulk insert; only when apply_to_profile is true, also its suggested
    expenses/income into the profile."""
    from shared import statement_store

    if not req.session_id.strip():
        raise HTTPException(422, "session_id must not be blank")
    try:
        return statement_store.import_preview(req.session_id, req.import_id, req.apply_to_profile)
    except statement_store.PreviewExpired as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(422, "The statement averages exceed supported profile limits. Import without updating the profile, or use a shorter statement.") from exc
    except OperationalError as exc:
        raise HTTPException(503, "Import is temporarily unavailable. Please retry the same preview.") from exc


@router.delete("")
def clear_all_transactions(session_id: str) -> dict[str, str]:
    from shared.user_store import clear_transactions

    clear_transactions(session_id)
    return {"status": "cleared"}


class SampleRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)


@router.post("/sample")
def load_sample_transactions(req: SampleRequest) -> dict[str, str]:
    """Deterministic synthetic transactions spanning two months, including
    one deliberate outlier -- enough to clear anomaly.py's MIN_TRANSACTIONS
    (10) and give the forecaster a real multi-month sequence, so trying the
    forecast/anomaly models doesn't require manually adding 15+ rows."""
    from shared.user_store import add_transaction

    session_id = req.session_id
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
