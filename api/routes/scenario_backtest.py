"""Historical scenario backtest: start a run, read one company's result, read the universe summary."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/research/scenario-backtest", tags=["scenario-backtest"])

_SYMBOL = re.compile(r"^[A-Z0-9.^=&_-]{1,20}$")


class StartRequest(BaseModel):
    symbol: str
    force: bool = False


def _symbol(s: str) -> str:
    s = s.strip().upper()
    if not _SYMBOL.match(s):
        raise HTTPException(status_code=422, detail="Invalid symbol.")
    return s if "." in s else s + ".NS"


@router.post("")
@router.post("/")
def start(req: StartRequest) -> dict[str, Any]:
    from modules.equity_research.scenario_backtest import jobs

    sym = _symbol(req.symbol)
    return {"symbol": sym, "status": jobs.submit(sym, force=req.force)}


@router.get("/universe/summary")
def universe_summary() -> dict[str, Any]:
    """Counts by status from the last sweep (data/scenario_backtest/summary.parquet)."""
    import datetime as dt

    import pandas as pd

    from modules.equity_research.scenario_backtest import data

    p = data.CACHE_DIR / "summary.parquet"
    if not p.exists():
        return {"symbols": 0, "by_status": {}, "last_updated": None}
    df = pd.read_parquet(p, columns=["status"])
    return {"symbols": len(df), "by_status": {k: int(v) for k, v in df["status"].value_counts().items()},
            "last_updated": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat()}


@router.get("/{symbol}")
def result(symbol: str, forecasts: bool = False) -> dict[str, Any]:
    from modules.equity_research.scenario_backtest import jobs

    r = jobs.get_result(_symbol(symbol), include_forecasts=forecasts)
    if r["status"] == "not_run":
        raise HTTPException(status_code=404, detail="No scenario backtest has been run for this symbol.")
    return r
