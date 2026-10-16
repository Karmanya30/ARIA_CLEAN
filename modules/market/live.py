"""Live (delayed ~15 min) Indian-market data for the Vitara Markets dashboard, from Yahoo Finance.

A background thread refreshes in-memory snapshots; request handlers only ever read them (snapshot()), so a slow
or failing Yahoo never blocks an API call. Each section keeps its last good copy and flags stale on failure.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from loguru import logger

from modules.equity_research.intelligence import sentiment
from shared.company_resolver import resolve_company
from shared.news import fetch_news

IST = timezone(timedelta(hours=5, minutes=30))
YF_LOCK = threading.Lock()  # yfinance's download() is not thread-safe
SOURCE, DELAY_MIN = "Yahoo Finance", 15

# symbol -> (name, sector); the 50 current Nifty constituents
NIFTY50: dict[str, tuple[str, str]] = {
    "RELIANCE.NS": ("Reliance Industries", "Energy"), "ONGC.NS": ("ONGC", "Energy"),
    "NTPC.NS": ("NTPC", "Energy"), "POWERGRID.NS": ("Power Grid", "Energy"), "COALINDIA.NS": ("Coal India", "Energy"),
    "TCS.NS": ("TCS", "IT"), "INFY.NS": ("Infosys", "IT"), "HCLTECH.NS": ("HCL Technologies", "IT"),
    "WIPRO.NS": ("Wipro", "IT"), "TECHM.NS": ("Tech Mahindra", "IT"),
    "HDFCBANK.NS": ("HDFC Bank", "Banks"), "ICICIBANK.NS": ("ICICI Bank", "Banks"), "SBIN.NS": ("State Bank of India", "Banks"),
    "KOTAKBANK.NS": ("Kotak Mahindra Bank", "Banks"), "AXISBANK.NS": ("Axis Bank", "Banks"),
    "BAJFINANCE.NS": ("Bajaj Finance", "Financial Services"), "BAJAJFINSV.NS": ("Bajaj Finserv", "Financial Services"),
    "JIOFIN.NS": ("Jio Financial", "Financial Services"), "SHRIRAMFIN.NS": ("Shriram Finance", "Financial Services"),
    "SBILIFE.NS": ("SBI Life Insurance", "Financial Services"), "HDFCLIFE.NS": ("HDFC Life", "Financial Services"),
    "MARUTI.NS": ("Maruti Suzuki", "Auto"), "M&M.NS": ("Mahindra & Mahindra", "Auto"), "TMPV.NS": ("Tata Motors PV", "Auto"),
    "EICHERMOT.NS": ("Eicher Motors", "Auto"), "BAJAJ-AUTO.NS": ("Bajaj Auto", "Auto"),
    "SUNPHARMA.NS": ("Sun Pharma", "Pharma"), "DRREDDY.NS": ("Dr Reddy's", "Pharma"), "CIPLA.NS": ("Cipla", "Pharma"),
    "APOLLOHOSP.NS": ("Apollo Hospitals", "Pharma"), "MAXHEALTH.NS": ("Max Healthcare", "Pharma"),
    "HINDUNILVR.NS": ("Hindustan Unilever", "FMCG"), "ITC.NS": ("ITC", "FMCG"), "NESTLEIND.NS": ("Nestle India", "FMCG"),
    "TATACONSUM.NS": ("Tata Consumer", "FMCG"),
    "TATASTEEL.NS": ("Tata Steel", "Metals"), "JSWSTEEL.NS": ("JSW Steel", "Metals"), "HINDALCO.NS": ("Hindalco", "Metals"),
    "BHARTIARTL.NS": ("Bharti Airtel", "Telecom"),
    "LT.NS": ("Larsen & Toubro", "Infra & Industrials"), "ADANIENT.NS": ("Adani Enterprises", "Infra & Industrials"),
    "ADANIPORTS.NS": ("Adani Ports", "Infra & Industrials"), "BEL.NS": ("Bharat Electronics", "Infra & Industrials"),
    "INDIGO.NS": ("IndiGo", "Infra & Industrials"),
    "ULTRACEMCO.NS": ("UltraTech Cement", "Materials"), "GRASIM.NS": ("Grasim", "Materials"), "ASIANPAINT.NS": ("Asian Paints", "Materials"),
    "TITAN.NS": ("Titan", "Consumer"), "TRENT.NS": ("Trent", "Consumer"), "ETERNAL.NS": ("Eternal", "Consumer"),
}

# symbol -> (name, group)
OVERVIEW: dict[str, tuple[str, str]] = {
    "^NSEI": ("Nifty 50", "india"), "^BSESN": ("Sensex", "india"), "^NSEBANK": ("Bank Nifty", "india"),
    "^CNXIT": ("Nifty IT", "india"), "^INDIAVIX": ("India VIX", "india"),
    "^GSPC": ("S&P 500", "global"), "^IXIC": ("Nasdaq", "global"),
    "INR=X": ("USD/INR", "fx"), "GC=F": ("Gold", "commodity"), "CL=F": ("Crude Oil", "commodity"), "BTC-USD": ("Bitcoin", "crypto"),
}
# sector name -> index symbol (None: Yahoo has no index, so the change is the constituents' average)
SECTOR_INDEX: dict[str, str | None] = {
    "IT": "^CNXIT", "Banks": "^NSEBANK", "Financial Services": "NIFTY_FIN_SERVICE.NS", "Auto": "^CNXAUTO",
    "Pharma": "^CNXPHARMA", "FMCG": "^CNXFMCG", "Metals": "^CNXMETAL", "Energy": "^CNXENERGY",
    "Realty": "^CNXREALTY", "PSU Banks": "^CNXPSUBANK", "Media": "^CNXMEDIA",
}
_ALL_INDEX = list(dict.fromkeys([*OVERVIEW, *(s for s in SECTOR_INDEX.values() if s)]))

_snap: dict[str, dict] = {}
_snap_lock = threading.Lock()
_started = False
_start_lock = threading.Lock()


def market_status(now: datetime | None = None, last_bar: datetime | None = None) -> dict:
    now = (now or datetime.now(IST)).astimezone(IST)
    open_ = now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)
    label = "Market open" if open_ else "Market closed"
    if open_ and last_bar is not None and now - last_bar.astimezone(IST) > timedelta(minutes=30):
        label = "No recent trades (holiday?)"
    return {"open": open_, "label": label, "now_ist": now.isoformat(timespec="seconds"), "note": "Exchange holidays not tracked."}


def _meta(as_of: datetime | None = None, **extra: Any) -> dict:
    now = datetime.now(timezone.utc)
    return {"as_of": (as_of or now).isoformat(timespec="seconds"), "fetched_at": now.isoformat(timespec="seconds"),
            "stale": False, "source": SOURCE, "delay_min": DELAY_MIN, **extra}


def _download(symbols: list[str], interval: str) -> pd.DataFrame:
    with YF_LOCK:
        df = yf.download(symbols, period="5d", interval=interval, progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError("Yahoo returned no data")
    return df


def _series(df: pd.DataFrame, field: str, sym: str) -> pd.Series:
    try:
        return df[field][sym].dropna()
    except KeyError:
        return pd.Series(dtype=float)


def _session(s: pd.Series) -> tuple[pd.Series, float | None]:
    """The latest trading session's bars and the close before it. A new session starts after a >4 h gap
    (overnight/weekend) or at a new UTC date, so 24 h markets (Bitcoin, FX) split by day."""
    if s.empty:
        return s, None
    idx = s.index
    start = idx.searchsorted(pd.Timestamp(idx[-1].date(), tz=idx.tz))
    gaps = [i for i in range(1, len(idx)) if idx[i] - idx[i - 1] > timedelta(hours=4)]
    if gaps:
        start = max(start, gaps[-1])
    return s.iloc[start:], (float(s.iloc[start - 1]) if start > 0 else None)


def _fallback_prev(sym: str, price: float) -> float | None:
    """Prior close for a symbol whose 15m window holds only one session: fast_info, else the daily history."""
    try:
        with YF_LOCK:
            t = yf.Ticker(sym)
            prev = t.fast_info.get("previousClose")
            if not prev:
                d = t.history(period="1mo", interval="1d", auto_adjust=False)["Close"].dropna()
                prev = d.iloc[-2] if len(d) > 1 else None
        return float(prev) if prev else None
    except Exception:
        return None


def _pct(price: float, prev: float | None) -> tuple[float, float]:
    return (price - prev, (price - prev) / prev * 100) if prev else (0.0, 0.0)


def _currency(sym: str) -> str:
    return "USD" if sym in ("^GSPC", "^IXIC", "GC=F", "CL=F", "BTC-USD") else "INR" if sym != "^INDIAVIX" else ""


def _build_overview(df: pd.DataFrame) -> tuple[dict, dict[str, float]]:
    items, changes, newest = [], {}, None
    for sym in _ALL_INDEX:
        today, prev = _session(_series(df, "Close", sym))
        if today.empty:
            continue
        price = float(today.iloc[-1])
        if prev is None:
            prev = _fallback_prev(sym, price) or float(today.iloc[0])
        chg, pct = _pct(price, prev)
        changes[sym] = round(pct, 2)
        if sym in OVERVIEW:
            name, group = OVERVIEW[sym]
            items.append({"symbol": sym, "name": name, "group": group, "price": round(price, 2), "change": round(chg, 2),
                          "change_pct": round(pct, 2), "prev_close": round(prev, 2), "currency": _currency(sym),
                          "spark": [round(float(v), 2) for v in today.iloc[-40:]]})
        if sym == "^NSEI":
            newest = today.index[-1].to_pydatetime()
    if not items:
        raise RuntimeError("no overview rows")
    return {"items": items, "last_bar": newest, "meta": _meta(newest)}, changes


def _build_movers(df: pd.DataFrame, idx_changes: dict[str, float]) -> tuple[dict, dict]:
    rows = []
    for sym, (name, sector) in NIFTY50.items():
        close, vol = _series(df, "Close", sym), _series(df, "Volume", sym)
        if len(close) < 2:
            continue
        price, prev = float(close.iloc[-1]), float(close.iloc[-2])
        v = float(vol.iloc[-1]) if len(vol) else 0.0
        rows.append({"symbol": sym, "name": name, "sector": sector, "price": round(price, 2),
                     "change_pct": round(_pct(price, prev)[1], 2), "volume": int(v), "value_cr": round(price * v / 1e7, 2)})
    if not rows:
        raise RuntimeError("no constituent rows")
    top = lambda key: sorted(rows, key=lambda r: r[key], reverse=True)[:8]  # noqa: E731
    movers = {"gainers": top("change_pct"), "losers": sorted(rows, key=lambda r: r["change_pct"])[:8], "active": top("value_cr")}
    sectors = []
    for name in dict.fromkeys([*SECTOR_INDEX, *(r["sector"] for r in rows)]):
        stocks = [r for r in rows if r["sector"] == name]
        isym = SECTOR_INDEX.get(name)
        pct = idx_changes.get(isym) if isym else None
        basis = "index"
        if pct is None and stocks:
            pct, basis = round(sum(r["change_pct"] for r in stocks) / len(stocks), 2), "constituents"
        if pct is None:
            continue
        sectors.append({"name": name, "index_symbol": isym, "basis": basis, "change_pct": pct, "value_cr": round(sum(r["value_cr"] for r in stocks), 2),
                        "stocks": [{k: r[k] for k in ("symbol", "name", "change_pct", "value_cr")} for r in stocks]})
    return {**movers, "meta": _meta()}, {"sectors": sectors, "meta": _meta()}


def _build_news() -> dict:
    raw = fetch_news("", limit=None)
    if not raw:
        raise RuntimeError("no news")
    t = sentiment.tone([r["title"] for r in raw])
    items = []
    for r, it in zip(raw, t["items"]):
        slug = resolve_company(r["title"])
        sym = [f"{slug}.NS"] if slug else []
        items.append({"title": r["title"], "source": r.get("source", ""), "url": r.get("url", ""), "age_hours": r.get("age_hours"),
                      "sources": r.get("sources", 1), "tone": it["label"], "net": round(it["net"], 2), "symbols": sym})
    feeds = len({i["source"] for i in items})
    return {"items": items, "engine": t["engine"], "meta": _meta(source=f"RSS, {feeds} feeds")}


def _put(kind: str, data: dict | None, err: Exception | None = None) -> None:
    with _snap_lock:
        if data is not None:
            _snap[kind] = data
        elif kind in _snap:  # keep the last good copy, flag it stale
            _snap[kind] = {**_snap[kind], "meta": {**_snap[kind]["meta"], "stale": True, "error": str(err)[:200]}}


def refresh_once(news: bool = True) -> None:
    """Refresh every section; a failing section keeps its last good copy (stale=True). Raises if any failed."""
    errors: list[Exception] = []
    changes: dict[str, float] = {}
    try:
        data, changes = _build_overview(_download(_ALL_INDEX, "15m"))
        _put("overview", data)
    except Exception as exc:
        errors.append(exc)
        _put("overview", None, exc)
    try:
        movers, sectors = _build_movers(_download(list(NIFTY50), "1d"), changes)
        _put("movers", movers)
        _put("sectors", sectors)
    except Exception as exc:
        errors.append(exc)
        _put("movers", None, exc)
        _put("sectors", None, exc)
    if news:
        try:
            _put("news", _build_news())
        except Exception as exc:
            errors.append(exc)
            _put("news", None, exc)
    if errors:
        raise errors[0]


def _loop() -> None:
    backoff, last_news = 0.0, 0.0
    while True:
        try:
            due = time.monotonic() - last_news > 300
            refresh_once(news=due)
            last_news = time.monotonic() if due else last_news
            backoff = 0.0
            wait = 60 if market_status()["open"] else 900
        except Exception as exc:
            backoff = min(backoff * 2, 900) if backoff else 120  # 2 -> 4 -> ... -> 15 min
            wait = backoff
            logger.warning(f"markets refresh failed ({type(exc).__name__}); retry in {wait:.0f}s")
        time.sleep(wait)


def start() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="markets-live", daemon=True).start()


def snapshot(kind: str) -> dict:
    """Copy of the latest snapshot; {warming: True} with empty lists (and a start()) when nothing has loaded yet."""
    with _snap_lock:
        snap = _snap.get(kind)
    if snap is None:
        start()
        return {"warming": True, "items": [], "gainers": [], "losers": [], "active": [], "sectors": [], "meta": _meta(stale=True)}
    return {**snap, "meta": dict(snap["meta"])}
