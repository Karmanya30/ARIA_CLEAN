"""Forecast validation runs: start one, poll its progress, read the latest result."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/research/validation", tags=["forecast"])

_SYMBOL = re.compile(r"^[A-Z0-9.^=&_-]{1,20}$")


class StartRequest(BaseModel):
    symbol: str
    report_id: str | None = None
    force: bool = False


def _symbol(s: str) -> str:
    s = s.strip().upper()
    if not _SYMBOL.match(s):
        raise HTTPException(status_code=422, detail="Invalid symbol.")
    return s


def _get(run_id: str):
    from modules.equity_research.forecast import jobs

    try:
        return jobs.status(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown run.") from None


@router.post("")
@router.post("/")
def start(req: StartRequest) -> dict[str, Any]:
    from modules.equity_research.forecast import jobs

    run_id = jobs.submit(_symbol(req.symbol), req.report_id, req.force)
    return {"run_id": run_id, "status": jobs.status(run_id).status}


@router.get("/latest")
def latest(symbol: str) -> dict[str, Any]:
    from modules.equity_research.forecast import store

    run = store.latest_run(_symbol(symbol))
    return run.model_dump() if run else {"status": "not_run"}


@router.get("/universe/summary")
def universe_summary() -> dict[str, Any]:
    """Counts by outcome from the last universe sweep (data/forecast_universe/summary.parquet)."""
    import datetime as dt

    import pandas as pd

    from modules.equity_research.forecast import universe

    p = universe.UNIVERSE_DIR / "summary.parquet"
    if not p.exists():
        return {"symbols": 0, "by_outcome": {}, "last_updated": None}
    df = pd.read_parquet(p, columns=["outcome", "status"])
    return {"symbols": len(df), "by_outcome": {k: int(v) for k, v in df["outcome"].value_counts().items()},
            "last_updated": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat()}


@router.get("/universe/{symbol}")
def universe_symbol(symbol: str) -> dict[str, Any]:
    """Latest run summary of one swept symbol (Yahoo code, e.g. RELIANCE.NS or 500325.BO)."""
    import pandas as pd

    from modules.equity_research.forecast import universe

    sym = _symbol(symbol)
    p = universe.UNIVERSE_DIR / "summary.parquet"
    if not p.exists():
        raise HTTPException(status_code=404, detail="No universe sweep has been run.")
    df = pd.read_parquet(p)
    hit = df[df["yahoo_symbol"].str.upper() == sym]
    if hit.empty:
        raise HTTPException(status_code=404, detail="Symbol not in the universe sweep.")
    row = hit.iloc[0].to_dict()
    return {k: (None if (not isinstance(v, (list, dict)) and pd.isna(v)) else (v.item() if hasattr(v, "item") else v))
            for k, v in row.items()}


@router.get("/{run_id}")
def run_status(run_id: str) -> dict[str, Any]:
    return _get(run_id).model_dump()


@router.post("/{run_id}/cancel")
def cancel(run_id: str) -> dict[str, Any]:
    from modules.equity_research.forecast import jobs

    _get(run_id)
    jobs.cancel(run_id)
    return jobs.status(run_id).model_dump()
