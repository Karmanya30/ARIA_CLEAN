"""Vitara Markets dashboard API: delayed (~15 min) Yahoo Finance data. overview/movers/sectors/news only read the
background snapshots in modules.market.live; chart/quote fetch on demand with a cache and a last-good fallback."""
from __future__ import annotations

import re
import threading
import time

import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from modules.equity_research.intelligence.data import _yf_info
from modules.market import live
from shared.company_resolver import resolve_company

router = APIRouter(prefix="/api/markets", tags=["markets"])

# endpoint -> required top-level keys (tests and the frontend types mirror this)
SCHEMA: dict[str, set[str]] = {
    "overview": {"status", "meta", "items"},
    "movers": {"meta", "gainers", "losers", "active"},
    "sectors": {"meta", "sectors"},
    "news": {"meta", "engine", "items"},
    "chart": {"symbol", "range", "interval", "currency", "meta", "bars"},
    "quote": {"symbol", "name", "price", "change_pct", "prev_close", "day_low", "day_high", "year_low", "year_high",
              "market_cap", "pe", "sector", "volume", "meta"},
}
META_KEYS = {"as_of", "fetched_at", "stale", "source", "delay_min"}

_SYMBOL = re.compile(r"^[A-Z0-9^=.&_-]{1,20}$")
_RANGES = {"1D": ("1d", "5m"), "5D": ("5d", "15m"), "1M": ("1mo", "1h"), "6M": ("6mo", "1d"), "1Y": ("1y", "1d"), "5Y": ("5y", "1wk")}
_store: dict[tuple, tuple[float, dict]] = {}
_store_lock = threading.Lock()


def _symbol(s: str) -> str:
    s = s.strip().upper()
    if not _SYMBOL.match(s):
        raise HTTPException(422, "invalid symbol")
    return s


def _cached(key: tuple, ttl: int, fetch) -> dict:
    """Fresh cache hit, else fetch; on failure the last good copy flagged stale, else 503."""
    with _store_lock:
        hit = _store.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        data = fetch()
    except Exception as exc:
        if hit:
            return {**hit[1], "meta": {**hit[1]["meta"], "stale": True, "error": str(exc)[:200]}}
        raise HTTPException(503, detail={"meta": {**live._meta(stale=True), "error": str(exc)[:200]}})
    with _store_lock:
        if len(_store) > 500:
            _store.clear()  # ponytail: wipe-all keeps it bounded; an LRU only matters if the key space gets large
        _store[key] = (time.monotonic(), data)
    return data


@router.get("/overview")
def overview() -> dict:
    s = live.snapshot("overview")
    last = s.pop("last_bar", None)
    return {**s, "status": live.market_status(last_bar=last)}


@router.get("/movers")
def movers() -> dict:
    return live.snapshot("movers")


@router.get("/sectors")
def sectors() -> dict:
    return live.snapshot("sectors")


@router.get("/news")
def news() -> dict:
    return live.snapshot("news")


def _chart(symbol: str, rng: str) -> dict:
    period, interval = _RANGES[rng]
    with live.YF_LOCK:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("no price history")
    try:
        cur = t.fast_info.get("currency") or ""
    except Exception:
        cur = ""
    bars = [{"t": int(ts.timestamp()), "o": round(float(r.Open), 2), "h": round(float(r.High), 2), "l": round(float(r.Low), 2),
             "c": round(float(r.Close), 2), "v": int(r.Volume)} for ts, r in df.dropna(subset=["Close"]).iterrows()]
    return {"symbol": symbol, "range": rng, "interval": interval, "currency": cur, "bars": bars,
            "meta": live._meta(df.index[-1].to_pydatetime())}


@router.get("/chart")
def chart(symbol: str, range: str = "1D") -> dict:  # noqa: A002  (the query parameter is named "range")
    symbol, rng = _symbol(symbol), range.upper()
    if rng not in _RANGES:
        raise HTTPException(422, "range must be one of " + "|".join(_RANGES))
    return _cached(("chart", symbol, rng), 60 if rng in ("1D", "5D") else 900, lambda: _chart(symbol, rng))


def _quote(symbol: str) -> dict:
    info = _yf_info(symbol)
    fi = yf.Ticker(symbol).fast_info
    price = fi.get("lastPrice") or info.get("currentPrice") or info.get("regularMarketPrice")
    prev = fi.get("previousClose") or info.get("previousClose")
    return {"symbol": symbol, "name": info.get("shortName") or info.get("longName") or symbol,
            "price": price, "change_pct": round((price - prev) / prev * 100, 2) if price and prev else None, "prev_close": prev,
            "day_low": fi.get("dayLow"), "day_high": fi.get("dayHigh"), "year_low": fi.get("yearLow"), "year_high": fi.get("yearHigh"),
            "market_cap": fi.get("marketCap") or info.get("marketCap"), "pe": info.get("trailingPE"), "sector": info.get("sector"),
            "volume": fi.get("lastVolume") or info.get("volume"), "meta": live._meta()}


@router.get("/quote")
def quote(symbol: str) -> dict:
    symbol = _symbol(symbol)
    return _cached(("quote", symbol), 300, lambda: _quote(symbol))


@router.get("/search")
def search(q: str = Query(..., max_length=60)) -> list[dict]:
    q = q.strip()
    out: dict[str, dict] = {}

    def add(sym: str, name: str, sector: str = "") -> None:
        if len(out) < 8:
            out.setdefault(sym, {"symbol": sym, "name": name, "sector": sector})

    slug = resolve_company(q) if q else None
    if slug and f"{slug}.NS" in live.NIFTY50:
        name, sector = live.NIFTY50[f"{slug}.NS"]
        add(f"{slug}.NS", name, sector)
    elif slug:
        add(f"{slug}.NS", slug)
    low = q.lower()
    for sym, (name, sector) in live.NIFTY50.items():
        if low and (low in name.lower() or low in sym.lower()):
            add(sym, name, sector)
    cand = q.upper()
    if _SYMBOL.match(cand) and "." not in cand and not cand.startswith("^"):
        add(cand + ".NS", cand)  # ticker-shaped input: offer it as an NSE symbol
    return list(out.values())
