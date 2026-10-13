"""Owner: scenario backtest WP5. Background runs + file-based results.

results/{symbol}.forecasts.parquet, .origins.parquet, .summary.json, keyed by sha1(input tables sha1 + ENGINE_VERSION).
One worker thread runs jobs one at a time (a company takes seconds from cache); no DB table.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from . import ENGINE_VERSION, data

_pool: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_running: set[str] = set()


def results_dir():
    return data.CACHE_DIR / "results"


def _p(symbol: str, ext: str):
    return results_dir() / f"{re.sub(r'[^A-Za-z0-9_.^-]', '_', symbol)}.{ext}"


def _key(symbol: str, version: str | None = None) -> str | None:
    """Input key: the cached statements' sha1 plus the engine version (None when nothing is cached yet)."""
    try:
        return hashlib.sha1(f"{data.load(symbol)[1]['sha1']}|{version or ENGINE_VERSION}".encode()).hexdigest()
    except Exception:
        return None


# sb1 results of status 'ok' stay valid under sb2: sb2 only ADDS short-history origins (separate slice) and only for
# companies with <= SHORT_MAX_COMPANY_YEARS fiscal years, so every sb1 number for a longer-history company is unchanged.
LEGACY_OK = "sb1"


def _legacy_ok(symbol: str, s: dict) -> bool:
    if s.get("status") != "ok" or s.get("engine") != LEGACY_OK or s.get("key") != _key(symbol, LEGACY_OK):
        return False
    from . import engine

    try:
        return not engine.short_ok(len(data.load(symbol)[1].get("fiscal_years") or []))
    except Exception:
        return False


def _read_summary(symbol: str) -> dict | None:
    try:
        return json.loads(_p(symbol, "summary.json").read_text())
    except Exception:
        return None


def is_current(symbol: str) -> bool:
    """A finished result computed from the inputs now on disk (a failed one is never current)."""
    s = _read_summary(symbol)
    if not s or s.get("status") in ("failed", "retry", "no_price"):
        return False
    if not s.get("key"):
        return s.get("status") == "no_screener_page"
    return s["key"] == _key(symbol) or _legacy_ok(symbol, s)


def _safe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.attrs = {}  # attrs hold dates; parquet metadata needs JSON
    for c in df.columns[df.dtypes == object]:
        df[c] = df[c].map(lambda v: json.dumps(v, default=str) if isinstance(v, (list, dict, tuple, set)) else v)
    return df


def _write(symbol: str, summary: dict, f: pd.DataFrame | None = None, o: pd.DataFrame | None = None) -> dict:
    results_dir().mkdir(parents=True, exist_ok=True)
    summary = {**summary, "symbol": symbol, "engine": ENGINE_VERSION, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if f is not None:
        _safe(f).to_parquet(_p(symbol, "forecasts.parquet"))
        _safe(o).to_parquet(_p(symbol, "origins.parquet"))
    _p(symbol, "summary.json").write_text(json.dumps(summary, default=str))
    return summary


def classify(e: BaseException) -> str:
    """'retry' for network trouble (timeout, connect error, 429): retried automatically on resume, never a final failure.
    'no_price' when Yahoo has no usable bars under any ticker tried. Everything else is 'failed'."""
    from modules.equity_research.forecast.data import DataUnavailable

    if data.is_transient(e):
        return "retry"
    if isinstance(e, DataUnavailable) and e.reason in ("no_data", "insufficient_history"):
        return "no_price"
    return "failed"


def compute(symbol: str, tables: dict | None = None, meta: dict | None = None, force: bool = False) -> dict:
    """Run (or reuse) the backtest for one company, write its result files and return the summary dict. Never raises."""
    t0 = time.perf_counter()
    try:
        if tables:
            data.save_tables(symbol, tables, meta or {})
        if not force and is_current(symbol):
            return _read_summary(symbol)
        from . import engine

        try:
            f, o = engine.run_company(symbol)
        except LookupError as e:  # neither screener.in nor the yfinance fallback has the company
            return _write(symbol, {"status": "no_screener_page", "reason": str(e), "key": None})
        summary = {"status": f.attrs.get("status", "ok"), "key": _key(symbol), "issues": f.attrs.get("issues", []),
                   "origin_skips": f.attrs.get("origin_skips", {}), "n_origins": len(o), "metrics": None,
                   "provider": f.attrs.get("provider"), "view": f.attrs.get("view"), "n_fiscal_years": f.attrs.get("n_years"),
                   "price_symbol": f.attrs.get("price_symbol"), "reason": f.attrs.get("reason") or None,
                   "n_origins_short": int(o["flags"].fillna("").str.contains("short_history").sum()) if len(o) else 0}
        if len(o):
            try:  # metrics.py is written separately; a missing or failing one must not lose the raw result
                from . import metrics

                summary["metrics"] = metrics.company_summary(f, o)
            except Exception as e:
                logger.warning(f"{symbol}: company_summary unavailable ({type(e).__name__}: {e})")
        return _write(symbol, {**summary, "seconds": round(time.perf_counter() - t0, 1)}, f, o)
    except Exception as e:
        status = classify(e)
        (logger.warning if status != "failed" else logger.exception)(f"scenario backtest {status} for {symbol}: {type(e).__name__}: {str(e)[:120]}")
        return _write(symbol, {"status": status, "reason": f"{type(e).__name__}: {str(e)[:200]}", "key": None})


def _job(symbol, tables, meta, force):
    try:
        compute(symbol, tables, meta, force)
    finally:
        with _lock:
            _running.discard(symbol)


def submit(symbol: str, tables: dict | None = None, meta: dict | None = None, force: bool = False) -> str:
    """Queue a run (a no-op when one is already queued for the symbol); returns the status."""
    global _pool
    with _lock:
        if symbol in _running:
            return "computing"
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scenario-backtest")
        _running.add(symbol)
    _pool.submit(_job, symbol, tables, meta, force)
    return "computing"


def status(symbol: str) -> str:
    """not_run | computing | ok | insufficient_history | model_refused | no_screener_page | retry | no_price | failed"""
    if symbol in _running:
        return "computing"
    s = _read_summary(symbol)
    return s["status"] if s else "not_run"


def get_result(symbol: str, include_forecasts: bool = False) -> dict:
    st = status(symbol)
    s = _read_summary(symbol)
    out = {"symbol": symbol, "status": st, "summary": s, "stale": bool(s and s.get("key") and s["key"] != _key(symbol)),
           "origins": [], "forecasts": []}
    for name, flag in (("origins", True), ("forecasts", include_forecasts)):
        p = _p(symbol, f"{name}.parquet")
        if flag and p.exists():
            out[name] = json.loads(pd.read_parquet(p).to_json(orient="records", date_format="iso"))
    return out


def wait_idle(timeout: float = 30.0) -> bool:
    """Block until the queue has drained (tests)."""
    end = time.time() + timeout
    while _running and time.time() < end:
        time.sleep(0.02)
    return not _running
