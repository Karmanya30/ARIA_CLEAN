"""One searchable catalogue of every tradable instrument ARIA can show: NSE/BSE stocks, Indian mutual funds, ETFs, crypto,
bond yields and bond ETFs, indices, commodities and currencies; plus quote / chart / profile / SIP for each.

Free sources only: the NSE/BSE universe file, AMFI + mfapi.in (modules.market.amfi), Yahoo Finance (via yfinance),
CoinGecko (free tier) and FRED (India 10Y yield). Every source has a timeout and a cache; a failing source degrades
that one field to "unavailable" and never fails the call. Ids look like "stock:RELIANCE.NS", "mf:119551", "crypto:BTC-USD".
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yfinance as yf
from loguru import logger

from modules.market import amfi
from modules.market import instrument_lists as L
from modules.market.live import YF_LOCK
from shared.company_resolver import company_aliases

DIR = amfi.DIR
UNIVERSE = Path(__file__).resolve().parents[2] / "data" / "forecast_universe" / "universe.parquet"
TYPES = ("stock", "etf", "mutual_fund", "crypto", "bond", "index", "commodity", "currency")
PREFIX = {"stock": "stock", "etf": "etf", "mutual_fund": "mf", "crypto": "crypto", "bond": "bond", "index": "index",
          "commodity": "commodity", "currency": "currency"}
BY_PREFIX = {v: k for k, v in PREFIX.items()}
DISCLAIMER = "This is general information, not investment advice. Past performance does not predict future results."
CAVEAT = "Past performance does not predict future returns."
COVERAGE = {
    "stock": "All NSE and BSE listed companies (~4,600, from the exchange universe file); other countries only through the online lookup.",
    "mutual_fund": "India only: every AMFI scheme with its daily NAV. NAV is end-of-day, not live; expense ratio is not in the free data.",
    "etf": "Indian ETFs: a curated NSE list plus BSE-listed ETFs; global: a curated list of major ETFs. Not every ETF in the world.",
    "crypto": "Top ~250 coins by market cap (CoinGecko, cached) or the curated top 100 when CoinGecko is unreachable; USD prices.",
    "bond": "LIMITED free coverage: individual G-secs, state bonds and corporate bonds have no free quote feed. Available: US Treasury "
            "yields, India 10-year yield (monthly, OECD via FRED), and bond/gilt/liquid ETFs.",
    "index": "Major Indian and global indices (Yahoo Finance, delayed).",
    "commodity": "Global commodity futures priced in USD (Yahoo). Indian MCX prices are not available free; see gold/silver ETFs for INR exposure.",
    "currency": "Major currency pairs including INR crosses (Yahoo, delayed).",
}
LIMITED = ("bond",)
_SYM = re.compile(r"^[A-Za-z0-9^=.&_-]{1,24}$")
_INDEX_CCY = {"^GSPC": "USD", "^DJI": "USD", "^IXIC": "USD", "^NDX": "USD", "^RUT": "USD", "^FTSE": "GBP", "^GDAXI": "EUR",
              "^FCHI": "EUR", "^N225": "JPY", "^HSI": "HKD", "^STI": "SGD", "^AXJO": "AUD", "^KS11": "KRW", "000001.SS": "CNY",
              "^BVSP": "BRL", "^VIX": "", "^INDIAVIX": "", "DX-Y.NYB": ""}


class NotFound(LookupError):
    pass


class Unsupported(ValueError):
    pass


class NoData(RuntimeError):
    pass


# ── caching ─────────────────────────────────────────────────────────────────────────────────────────────────────
_mem: dict[Any, tuple[float, Any]] = {}
_mem_lock = threading.Lock()


def _cached(key: Any, ttl: float, fn: Callable[[], Any]) -> tuple[Any, bool]:
    """(value, stale): a fresh hit, else fn(); if fn fails the last good value comes back stale, else the error is raised."""
    with _mem_lock:
        hit = _mem.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1], False
    try:
        val = fn()
    except Exception:
        if hit:
            return hit[1], True
        raise
    with _mem_lock:
        if len(_mem) > 3000:
            _mem.clear()  # ponytail: wipe-all keeps it bounded; an LRU only matters if the key space grows
        _mem[key] = (time.monotonic(), val)
    return val, False


def _r(x: Any) -> float | None:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    x = float(x)
    return round(x, 4) if abs(x) >= 1 else float(f"{x:.6g}")


def _pct(x: Any) -> float | None:
    return None if x is None or not math.isfinite(float(x)) else round(float(x), 2)


# ── Yahoo ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _fetch_hist(sym: str, period: str, interval: str) -> pd.DataFrame:
    with YF_LOCK:  # yfinance shares state between threads
        df = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=False, timeout=10)
    if df is None or df.empty or "Close" not in df:
        raise NoData(f"Yahoo has no price history for {sym}")
    return df.dropna(subset=["Close"])


def _hist(sym: str, period: str, interval: str) -> tuple[pd.DataFrame, bool]:
    ttl = 60 if interval.endswith(("m", "h")) else 1800 if period == "max" else 900 if interval in ("1wk", "1mo") else 120
    return _cached(("hist", sym, period, interval), ttl, lambda: _fetch_hist(sym, period, interval))


def _info(sym: str) -> dict:
    def go() -> dict:
        with YF_LOCK:
            return yf.Ticker(sym).info or {}
    try:
        return _cached(("info", sym), 6 * 3600, go)[0]
    except Exception:
        return {}


_yf_down_until = 0.0
_px: dict[str, tuple[float, dict]] = {}


def _prices(symbols: list[str]) -> dict[str, dict]:
    """sym -> {price, change_pct, as_of} for a page of symbols from ONE batched download, cached 5 min per symbol.
    After a failure Yahoo is left alone for 90 s and only cached prices are returned."""
    global _yf_down_until
    now = time.monotonic()
    out = {s: _px[s][1] for s in symbols if s in _px and now - _px[s][0] < 300}
    need = [s for s in symbols if s not in out]
    if need and now >= _yf_down_until:
        try:
            with YF_LOCK:
                df = yf.download(need, period="5d", interval="1d", progress=False, auto_adjust=False, threads=True, timeout=15)
            close = df["Close"]
            if isinstance(close, pd.Series):
                close = close.to_frame(need[0])
            for s in need:
                c = close[s].dropna() if s in close else pd.Series(dtype=float)
                if len(c):
                    prev = float(c.iloc[-2]) if len(c) > 1 else None
                    price = float(c.iloc[-1])
                    out[s] = {"price": _r(price), "change_pct": _pct((price - prev) / prev * 100) if prev else None, "as_of": c.index[-1].date().isoformat()}
                    _px[s] = (now, out[s])
        except Exception as exc:
            _yf_down_until = now + 90
            logger.warning(f"batched Yahoo prices failed ({type(exc).__name__}); skipping live prices for 90 s")
    return out


# ── CoinGecko / FRED ───────────────────────────────────────────────────────────────────────────────────────────
CG_URL = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1"
          "&sparkline=false&price_change_percentage=24h")
_cg: tuple[float, list[dict]] = (0.0, [])
_cg_fail_until = 0.0
_cg_lock = threading.Lock()


def _coingecko(network: bool = True) -> list[dict]:
    """Top coins by market cap, cached 15 min on disk. Stale copy if CoinGecko fails, [] if there never was one."""
    global _cg, _cg_fail_until
    path = DIR / "coingecko.json"
    with _cg_lock:
        _cg_refresh(path, network)
    if not path.exists():
        return []
    mt = path.stat().st_mtime
    if _cg[0] != mt:
        try:
            _cg = (mt, json.loads(path.read_text("utf-8")))
        except ValueError:
            return _cg[1]
    return _cg[1]


def _cg_refresh(path: Path, network: bool) -> None:
    global _cg_fail_until
    age = time.time() - path.stat().st_mtime if path.exists() else 1e9
    if age >= 900 and network and time.time() >= _cg_fail_until:
        try:
            data = amfi.http_get(CG_URL, timeout=10).json()
            if not isinstance(data, list) or not data:
                raise ValueError("unexpected CoinGecko reply")
            DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), "utf-8")
            tmp.replace(path)  # atomic: a concurrent reader never sees half a file
            age = 0
        except Exception as exc:
            _cg_fail_until = time.time() + 120
            logger.warning(f"CoinGecko unavailable ({type(exc).__name__}); using the cached/curated list")


def _fred_in10y() -> list[tuple[str, float]]:
    """India 10-year government bond yield, monthly (OECD series on FRED, free CSV)."""
    def go() -> list[tuple[str, float]]:
        txt = amfi.http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDIRLTLT01STM", timeout=15).text
        rows = [l.split(",") for l in txt.splitlines()[1:]]
        out = [(d, float(v)) for d, v in rows if len(rows[0]) == 2 and v not in (".", "")]
        if not out:
            raise NoData("no FRED rows")
        return out
    return _cached(("fred", "in10y"), 12 * 3600, go)[0]


# ── catalogue ──────────────────────────────────────────────────────────────────────────────────────────────────
def _lines(txt: str) -> list[list[str]]:
    return [l.split("|") for l in txt.strip().splitlines()]


def _item(type_: str, symbol: str, name: str, exchange: str, currency: str, source: str, subtitle: str, pop: float = 5,
          extra: str = "", **priv: Any) -> dict:
    aliases = company_aliases(symbol) if type_ == "stock" else ()
    hay = f"{name} {symbol} {extra} {' '.join(aliases)}".lower()
    return {"id": f"{PREFIX[type_]}:{symbol}", "symbol": symbol, "name": name, "type": type_, "exchange": exchange, "currency": currency,
            "source": source, "subtitle": subtitle, "_hay": hay, "_hay2": re.sub(r"[^a-z0-9]", "", hay), "_pop": pop,
            "_name": name.lower(), "_sym": symbol.lower(), "_base": re.sub(r"\.(ns|bo)$", "", symbol.lower()), "_aliases": aliases,
            "_words": set(re.findall(r"[a-z0-9&]+", hay)), **priv}


_cat: dict[str, Any] | None = None
_cat_lock = threading.Lock()
_ETF_RE = re.compile(r"\bETF\b|BEES|EXCH\w* TRADED|MUTUAL FUND", re.I)
_BOND_RE = re.compile(r"LIQUID|GILT|G-?SEC|BOND|BBETF|\bSDL|TREASURY|CASH", re.I)


def _build() -> dict[str, Any]:
    items: list[dict] = []
    seen_etf: set[str] = set()

    def curated(txt, type_, suffix, exchange, ccy, source, sub, pop):
        for sym, name in ((a[0], a[1]) for a in _lines(txt)):
            items.append(_item(type_, sym, name, exchange(sym) if callable(exchange) else exchange,
                               ccy(sym) if callable(ccy) else ccy, source, sub(sym) if callable(sub) else sub, pop))
            if type_ in ("etf", "bond"):
                seen_etf.add(re.sub(r"\.(NS|BO)$", "", sym).lower())

    curated(L.INDICES, "index", "", "Index", lambda s: "INR" if s.startswith(("^NS", "^CNX", "^BSE", "^CRSL")) else _INDEX_CCY.get(s, "USD"),
            "Yahoo Finance", lambda s: "India index" if s.startswith(("^NS", "^CNX", "^BSE", "^CRSL", "^INDIA")) else "Global index", 9)
    curated(L.COMMODITIES, "commodity", "", "Futures", "USD", "Yahoo Finance", "Commodity futures (USD)", 8)
    curated(L.CURRENCIES, "currency", "", "Forex", lambda s: s[3:6], "Yahoo Finance", "Currency pair", 8)
    curated(L.BOND_YIELDS, "bond", "", "Treasury yield", "", "Yahoo Finance", "Government bond yield (%)", 8)
    curated(L.BOND_ETFS_GLOBAL, "bond", "", "US", "USD", "Yahoo Finance", "Bond ETF (US)", 6)
    curated(L.ETFS_INDIA, "etf", "", "NSE", "INR", "Yahoo Finance", "ETF (NSE)", 7)
    curated(L.BOND_ETFS_INDIA, "bond", "", "NSE", "INR", "Yahoo Finance", "Bond / liquid / gilt ETF (NSE)", 7)
    curated(L.ETFS_GLOBAL, "etf", "", "US", "USD", "Yahoo Finance", "ETF (US)", 7)
    items.append(_item("bond", "IN10Y", "India 10-Year Government Bond Yield", "G-sec yield", "", "FRED (OECD)",
                       "Government bond yield (%), monthly", 8.5))

    if UNIVERSE.exists():
        df = pd.read_parquet(UNIVERSE, columns=["symbol", "yahoo_symbol", "exchange", "name", "isin", "series", "also_on", "traded_value", "nifty500"])
        for r in df.itertuples(index=False):
            ysym, ex, name, series = r.yahoo_symbol, r.exchange, str(r.name), str(r.series)
            tv = float(r.traded_value) if r.traded_value == r.traded_value else 0.0
            pop = math.log10(tv + 1) + (3 if r.nifty500 else 0)
            etfish = bool(_ETF_RE.search(name) or re.search("BEES|ETF", r.symbol)) or (ex == "BSE" and series in ("E", "F"))
            if etfish:
                if r.symbol.lower() in seen_etf:
                    continue
                kind = "bond" if series == "F" or _BOND_RE.search(f"{name} {r.symbol}") else "etf"
                disp = f"{r.symbol} - {name}" if "etf" not in name.lower() and "bees" not in name.lower() else name
                items.append(_item(kind, ysym, disp, ex, "INR", "NSE/BSE universe", f"{r.symbol} · {ex} · ETF", 5, extra=f"{r.isin} {r.symbol}"))
            else:
                bse_only = ysym.endswith(".BO")
                sub = f"{r.symbol} · {ex}" + (f" ({ysym[:-3]})" if bse_only else " · also BSE" if r.also_on == "BSE" else "") + (f" · series {series}" if series not in ("EQ", "nan") else "")
                items.append(_item("stock", ysym, name, ex, "INR", "NSE/BSE universe", sub, pop, extra=f"{r.isin} {r.symbol}", _series=series, _tv=tv))
    else:
        logger.warning("universe.parquet missing: stock search covers the curated lists only")
    return {"items": items, "by_id": {i["id"]: i for i in items}}


def catalog() -> dict[str, Any]:
    global _cat
    with _cat_lock:
        if _cat is None:
            _cat = _build()
        return _cat


_crypto_key: tuple | None = None
_crypto_items: list[dict] = []


def _crypto_pool(network: bool = False) -> list[dict]:
    """Coins ranked by market cap: CoinGecko's list when cached, else the curated top 100. Rebuilt when CoinGecko refreshes."""
    global _crypto_key, _crypto_items
    cg = _coingecko(network)
    key = (_cg[0] if cg else 0.0,)
    if key == _crypto_key and _crypto_items:
        return _crypto_items
    curated = {a[0].upper(): (a[1], a[2] if len(a) > 2 else f"{a[0].upper()}-USD") for a in _lines(L.CRYPTO)}
    out, seen = [], set()
    for rank, c in enumerate(cg, 1):
        base = str(c.get("symbol", "")).upper()
        if not base or base in seen:
            continue
        seen.add(base)
        ysym = curated.get(base, (None, f"{base}-USD"))[1]
        out.append(_item("crypto", ysym, c.get("name") or base, "Crypto", "USD", "CoinGecko / Yahoo Finance", f"{base} · rank #{rank} by market cap",
                         12 - rank * 0.04, _base=base, _cgid=c.get("id"), _rank=rank))
    for i, (base, (name, ysym)) in enumerate(curated.items(), 1):
        if base not in seen:
            out.append(_item("crypto", ysym, name, "Crypto", "USD", "Yahoo Finance", f"{base} · top-100 coin", 11 - i * 0.07, _base=base, _rank=len(out) + 1))
    _crypto_key, _crypto_items = key, out
    return out


_mf_key: int | None = None
_mf_items: list[dict] = []
_PLAN_RANK = {("Direct", "Growth"): 0, ("Regular", "Growth"): 1, ("Direct", "IDCW"): 2, ("Regular", "IDCW"): 3}


def _mf_pool() -> list[dict]:
    global _mf_key, _mf_items
    funds = amfi.funds()
    if id(funds) == _mf_key:
        return _mf_items
    items = []
    for f in funds:
        amc = re.sub(r" Mutual Fund$", "", f["amc"], flags=re.I)
        cat = " ".join(f["category"].split(" - ", 1)[-1].split())
        it = _item("mutual_fund", f["code"], f"{f['name']} - {f['plan']} - {f['option']}", "AMFI", "INR", "AMFI",
                   f"{amc} · {cat} · {f['plan']} {f['option']}", 2, extra=f"{f['code']} {f['isin']} {f['amc']} {f['category']}", _mf=f)
        it["_rank"] = _PLAN_RANK.get((f["plan"], f["option"]), 4)
        items.append(it)
    _mf_key, _mf_items = id(funds), items
    return items


def _public(it: dict) -> dict:
    return {k: v for k, v in it.items() if not k.startswith("_")}


# ── resolve ────────────────────────────────────────────────────────────────────────────────────────────────────
def resolve(iid: str) -> dict:
    """Instrument for an id such as "stock:RELIANCE.NS". Known ids come from the catalogue; any other well-formed symbol is
    taken as a Yahoo symbol, so anything Yahoo lists can still be opened. NotFound for malformed ids or unknown MF codes."""
    prefix, _, rest = (iid or "").strip().partition(":")
    rest = rest.strip()
    if prefix not in BY_PREFIX or not rest or not _SYM.match(rest):
        raise NotFound(f"unknown instrument id {iid!r}")
    type_ = BY_PREFIX[prefix]
    if type_ == "mutual_fund" and rest.isdigit():
        for it in _mf_pool():
            if it["symbol"] == rest:
                return it
        meta, hist, _ = amfi.history(rest)  # AMFI file down, or a scheme it no longer lists
        if not meta or str(meta.get("scheme_code", "")) != rest:
            raise NotFound(f"no mutual fund with scheme code {rest}")
        return _item("mutual_fund", rest, meta.get("scheme_name", rest), "AMFI", "INR", "mfapi.in", meta.get("fund_house", ""),
                     _mf={"code": rest, "name": meta.get("scheme_name", rest), "amc": meta.get("fund_house", ""), "category": meta.get("scheme_category", ""),
                          "isin": meta.get("isin_growth") or "", "plan": _plan_of(meta), "option": "Growth", "nav": None, "date": None, "kind": meta.get("scheme_type", "")})
    sym = rest.upper()
    cat = catalog()["by_id"]
    for cand in (f"{prefix}:{sym}", f"{prefix}:{sym}.NS"):
        if cand in cat:
            return cat[cand]
    if type_ == "crypto":
        for it in _crypto_pool():
            if it["id"] == f"crypto:{sym}":
                return it
    for other in ("etf", "stock", "bond"):  # an ETF opened as "stock:" and so on
        if f"{PREFIX[other]}:{sym}" in cat:
            return cat[f"{PREFIX[other]}:{sym}"]
    ex = "NSE" if sym.endswith(".NS") else "BSE" if sym.endswith(".BO") else ""
    ccy = "INR" if ex else "USD" if sym.endswith("-USD") else ""
    return _item(type_, sym, sym, ex, ccy, "Yahoo Finance", ex or "Yahoo Finance symbol", 1, generic=True)


def _plan_of(meta: dict) -> str:
    return "Direct" if "direct" in str(meta.get("scheme_name", "")).lower() else "Regular"


# ── search ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _score(it: dict, q: str, toks: list[str]) -> float:
    if not toks:
        return 1 + it["_pop"] * 0.4
    hay, hay2 = it["_hay"], it["_hay2"]
    fuzzy = False
    for t in toks:
        t2 = re.sub(r"[^a-z0-9]", "", t)
        if t in hay or (t2 and (t2 != t or len(t2) >= 4) and t2 in hay2):
            continue
        # Conservative spelling tolerance: short symbols and numeric identifiers must stay precise.
        if len(t2) >= 4 and t2.isalpha() and any(
            w.isalpha() and abs(len(w) - len(t2)) <= 2
            and SequenceMatcher(None, t2, w).ratio() >= 0.8 for w in it["_words"]
        ):
            fuzzy = True
        else:
            return 0
    if fuzzy:
        return 30 + it["_pop"] * 0.4
    s = 50
    if q in (it["_sym"], it["_base"], it["_name"], *it.get("_aliases", ())):
        s = 100
    elif it["_sym"].startswith(q) or it["_base"].startswith(q):
        s = 90
    elif it["_name"].startswith(q):
        s = 80
    elif all(any(w.startswith(t) for w in it["_words"]) for t in toks):
        s = 70
    return s + it["_pop"] * 0.4


def _pool(type_: str, network: bool = False) -> list[dict]:
    if type_ == "mutual_fund":
        return _mf_pool()
    if type_ == "crypto":
        return _crypto_pool(network)
    return [i for i in catalog()["items"] if i["type"] == type_]


def _yahoo_lookup(q: str) -> list[dict]:
    """Yahoo's own symbol search for things outside our lists (US stocks, other countries). Cached an hour."""
    kinds = {"EQUITY": "stock", "ETF": "etf", "CRYPTOCURRENCY": "crypto", "INDEX": "index", "CURRENCY": "currency"}  # Indian funds come from AMFI

    def go() -> list[dict]:
        res = yf.Search(q, max_results=8, news_count=0, timeout=6).quotes
        out = []
        for r in res:
            t = kinds.get(str(r.get("quoteType")))
            sym = str(r.get("symbol", "")).upper()
            if t and _SYM.match(sym):
                name = r.get("longname") or r.get("shortname") or sym
                out.append(_item(t, sym, name, r.get("exchDisp") or "", "INR" if sym.endswith((".NS", ".BO")) else "USD" if t == "crypto" else "",
                                 "Yahoo Finance", f"{sym} · {r.get('exchDisp') or 'Yahoo Finance'}", 3))
        return out
    try:
        return _cached(("ysearch", q.lower()), 3600, go)[0]
    except Exception as exc:
        logger.debug(f"Yahoo symbol lookup failed: {type(exc).__name__}")
        return []


def search(q: str, type_: str = "all", limit: int = 20, market: str = "all") -> dict:
    raw = (q or "").strip()
    q = raw.lower()
    toks = q.split()
    if type_ not in ("all", *TYPES):
        raise ValueError(f"type must be one of all|{'|'.join(TYPES)}")
    if market not in ("all", "india"):
        raise ValueError("market must be all|india")
    def eligible(it: dict) -> bool:
        return market == "all" or it["symbol"].endswith((".NS", ".BO"))
    types = TYPES if type_ == "all" else (type_,)
    ranked: list[tuple[float, int, dict]] = []
    counts: dict[str, int] = {}
    for t in types:
        pool = [it for it in _pool(t) if eligible(it)]
        scored = [(s, it.get("_rank", 0) if t == "mutual_fund" else 0, it) for it in pool if (s := _score(it, q, toks)) > 0]
        counts[t] = len(scored)
        scored.sort(key=lambda x: (-x[0], x[1], len(x[2]["name"])))
        ranked.extend(scored[: max(limit, 10)])
    ranked.sort(key=lambda x: (-x[0], x[1], len(x[2]["name"])))
    picked, rest, mf = [], [], 0
    cap = max(3, limit // 2) if type_ == "all" else limit  # funds are 14k of 19k rows: keep them from burying everything else
    for _, _, it in ranked:
        if it["type"] == "mutual_fund" and mf >= cap:
            rest.append(it)
            continue
        mf += it["type"] == "mutual_fund"
        picked.append(it)
    picked = (picked + rest)[:limit]
    yahoo = False
    ticker_like = raw.isupper() and " " not in raw and not any(q in (i["_sym"], i["_base"], *i.get("_aliases", ())) for i in picked)  # "AAPL" typed, no such symbol here
    if len(q) >= 2 and (not picked or ticker_like) and type_ in ("all", "stock", "etf", "crypto", "index", "currency"):
        have = {i["id"] for i in picked}
        extra = [i for i in _yahoo_lookup(q) if i["id"] not in have and eligible(i) and (type_ == "all" or i["type"] == type_)]
        picked = sorted(picked + extra, key=lambda i: -_score(i, q, toks) if toks else 0)[:limit]  # stable: exact ticker rises to the top
        yahoo = bool(extra)
    if type_ in ("all", "crypto") and not _cg[1]:
        threading.Thread(target=_coingecko, name="cg-warm", daemon=True).start()  # next search gets the full coin list
    meta = {"query": q, "type": type_, "count": len(picked), "matches_by_type": {t: n for t, n in counts.items() if n},
            "online_lookup_used": yahoo, "coverage": {t: COVERAGE[t] for t in types},
            "limited_coverage": [t for t in types if t in LIMITED],
            "sources": {"mutual_funds": "AMFI NAV file" + ("" if amfi.funds() else " (unavailable right now)"),
                        "stocks": "NSE/BSE universe file" + ("" if UNIVERSE.exists() else " (missing)")}}
    return {"items": [_public(i) for i in picked], "meta": meta}


# ── browse ─────────────────────────────────────────────────────────────────────────────────────────────────────
_facet_key: int | None = None
_facets: dict = {}


def _mf_facets() -> dict:
    global _facet_key, _facets
    funds = amfi.funds()
    if id(funds) != _facet_key:
        def top(key):
            c: dict[str, int] = {}
            for f in funds:
                c[f[key]] = c.get(f[key], 0) + 1
            return [{"name": k, "count": v} for k, v in sorted(c.items()) if k]
        _facets, _facet_key = {"amcs": top("amc"), "categories": top("category"), "plans": top("plan"), "options": top("option")}, id(funds)
    return _facets


def browse(type_: str, q: str = "", sort: str = "", page: int = 1, page_size: int = 50, amc: str = "", category: str = "",
           plan: str = "", option: str = "", prices: bool = True) -> dict:
    type_ = {"mf": "mutual_fund"}.get(type_, type_)
    if type_ not in TYPES:
        raise ValueError(f"type must be one of {'|'.join(TYPES)}")
    page, page_size = max(1, page), max(1, min(200, page_size))
    toks = q.strip().lower().split()
    pool = _pool(type_, network=type_ == "crypto")
    if type_ == "mutual_fund":
        al, cl = amc.lower(), category.lower()
        pool = [i for i in pool if (not al or al in i["_mf"]["amc"].lower()) and (not cl or cl in i["_mf"]["category"].lower())
                and (not plan or i["_mf"]["plan"].lower() == plan.lower()) and (not option or i["_mf"]["option"].lower() == option.lower())]
    if toks:
        scored = [(s, it) for it in pool if (s := _score(it, q.strip().lower(), toks)) > 0]
        scored.sort(key=lambda x: (-x[0], x[1].get("_rank", 0), len(x[1]["name"])))
        pool = [it for _, it in scored]
    elif type_ == "mutual_fund":
        pool = sorted(pool, key=lambda i: (i["name"].lower(), i["_rank"]))
    else:
        pool = sorted(pool, key=lambda i: -i["_pop"])
    cg = {str(c.get("symbol", "")).upper(): c for c in _coingecko(False)} if type_ == "crypto" else {}

    def key_for(name: str):
        if name in ("name", "-name"):
            return lambda i: i["name"].lower()
        if name in ("nav", "-nav") and type_ == "mutual_fund":
            return lambda i: i["_mf"]["nav"] or 0
        if type_ == "crypto" and name.lstrip("-") in ("change", "price", "mcap"):
            field = {"change": "price_change_percentage_24h", "price": "current_price", "mcap": "market_cap"}[name.lstrip("-")]
            return lambda i: (cg.get(i.get("_base", ""), {}).get(field) or -1e18)
        return None
    kf = key_for(sort)
    used_sort = sort if kf else ("search relevance" if toks else "name" if type_ == "mutual_fund" else "popularity")
    if kf:
        pool = sorted(pool, key=kf, reverse=sort.startswith("-"))
    total = len(pool)
    chunk = pool[(page - 1) * page_size: page * page_size]
    price_src = "none"
    px: dict[str, dict] = {}
    if type_ == "crypto" and cg:
        price_src = "CoinGecko (cached)"
    elif type_ != "mutual_fund" and prices and chunk:
        yahoo_syms = [i["symbol"] for i in chunk if i["symbol"] != "IN10Y"]
        px = _prices(yahoo_syms)
        price_src = "Yahoo Finance (one batched download, cached 5 min)" if px else "unavailable (Yahoo busy; names only)"
    elif type_ == "mutual_fund":
        price_src = "AMFI NAV (latest declared; 1-day change not included in lists)"
    out = []
    for it in chunk:
        row = _public(it)
        if type_ == "mutual_fund":
            f = it["_mf"]
            row.update(price=f["nav"], change_pct=None, as_of=f["date"], amc=f["amc"], category=f["category"], plan=f["plan"], option=f["option"], isin=f["isin"])
        elif type_ == "crypto" and (c := cg.get(it.get("_base", ""))):
            row.update(price=_r(c.get("current_price")), change_pct=_pct(c.get("price_change_percentage_24h")), as_of=None,
                       market_cap=c.get("market_cap"), volume_24h=c.get("total_volume"), rank=c.get("market_cap_rank"))
        else:
            p = px.get(it["symbol"], {})
            if it["symbol"] == "IN10Y":  # not on Yahoo: FRED (cached 12 h); the change is month on month
                try:
                    (d, v), prev = _fred_in10y()[-1], _fred_in10y()[-2][1]
                    p = {"price": v, "change_pct": _pct((v - prev) / prev * 100), "as_of": d}
                except Exception:
                    p = {}
            row.update(price=p.get("price"), change_pct=p.get("change_pct"), as_of=p.get("as_of"))
        out.append(row)
    meta = {"type": type_, "page": page, "page_size": page_size, "total": total, "pages": max(1, math.ceil(total / page_size)), "sort": used_sort,
            "prices": price_src, "coverage": COVERAGE[type_], "limited_coverage": type_ in LIMITED}
    if type_ == "mutual_fund":
        meta["facets"] = _mf_facets()
        meta["sorts"] = ["name", "-name", "nav", "-nav"]
    elif type_ == "crypto":
        meta["sorts"] = ["name", "-name", "price", "-price", "mcap", "-mcap", "change", "-change"]
    return {"items": out, "meta": meta}


# ── quote ──────────────────────────────────────────────────────────────────────────────────────────────────────
DELAY = {
    "yahoo": "Prices are delayed about 15 minutes (Yahoo Finance); when the market is closed this is the last close.",
    "crypto": "Crypto trades 24x7; price is near real-time (Yahoo Finance, refreshed about every minute).",
    "fx": "Forex and futures quotes can lag 10-15 minutes (Yahoo Finance).",
    "yield": "Yield in percent, delayed about 15 minutes (Yahoo Finance). It is a yield, not a price.",
    "mf": "NAV is declared once a day by the fund house (published by AMFI, usually by late evening IST); it is not a live price.",
    "in10y": "Monthly average yield (OECD data on FRED), not live. Free daily Indian G-sec yields are not available.",
}


def _age_days(d: str) -> int:
    return (datetime.now(timezone.utc).date() - date.fromisoformat(str(d)[:10])).days


def _base_quote(it: dict, note: str) -> dict:
    return {"id": it["id"], "name": it["name"], "type": it["type"], "price": None, "change": None, "change_pct": None,
            "currency": it["currency"], "as_of": None, "delay_note": note, "stale": True, "source": it["source"]}


def _quote_mf(it: dict) -> dict:
    f = it["_mf"]
    live = amfi.fund(f["code"]) or f
    meta, hist, hstale = amfi.history(f["code"])
    q = _base_quote(it, DELAY["mf"])
    nav, nd = live.get("nav"), live.get("date")
    if nav is None and hist:
        nd, nav = hist[-1]
    if nav is None:
        raise NoData("NAV unavailable from AMFI and mfapi")
    prev = next((p for d, p in reversed(hist) if d < nd), None)
    q.update(price=_r(nav), change=_r(nav - prev) if prev else None, change_pct=_pct((nav - prev) / prev * 100) if prev else None, as_of=nd,
             stale=amfi.stale_nav(nd), nav=_r(nav), nav_date=nd, scheme_category=f["category"] or meta.get("scheme_category"),
             amc=f["amc"] or meta.get("fund_house"), isin=f["isin"] or meta.get("isin_growth"), plan=f["plan"], option=f["option"],
             scheme_type=f["kind"] or meta.get("scheme_type"), expense_ratio=None,
             expense_ratio_note="Not in the free AMFI/mfapi data; see the scheme's factsheet.")
    q["source"] = "AMFI" + (" + mfapi.in" if hist else "")
    return q


def _quote_in10y(it: dict) -> dict:
    rows = _fred_in10y()
    d, v = rows[-1]
    prev = rows[-2][1] if len(rows) > 1 else None
    q = _base_quote(it, DELAY["in10y"])
    q.update(price=_r(v), change=_r(v - prev) if prev else None, change_pct=_pct((v - prev) / prev * 100) if prev else None, as_of=d,
             stale=_age_days(d) > 75, **{"yield": _r(v), "yield_unit": "% per year"})
    return q


def _cg_coin(it: dict) -> dict:
    base = it.get("_base") or re.sub(r"(\d*)-USD$", "", it["symbol"])
    for c in _coingecko(True):
        if str(c.get("symbol", "")).upper() == base:
            return c
    return {}


def _quote_yahoo(it: dict) -> dict:
    sym, t = it["symbol"], it["type"]
    note = DELAY["crypto" if t == "crypto" else "yield" if sym.startswith("^") and sym in [a[0] for a in _lines(L.BOND_YIELDS)] else
                 "fx" if t in ("currency", "commodity") else "yahoo"]
    q = _base_quote(it, note)
    q["source"] = "Yahoo Finance"
    cg = _cg_coin(it) if t == "crypto" else {}
    try:
        df, hstale = _hist(sym, "1y", "1d")
    except Exception:
        if not cg:
            raise
        q.update(price=_r(cg.get("current_price")), change=_r(cg.get("price_change_24h")), change_pct=_pct(cg.get("price_change_percentage_24h")),
                 as_of=cg.get("last_updated"), stale=False, source="CoinGecko")
        df = None
    if df is not None:
        close = df["Close"]
        price = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else None
        asof = df.index[-1]
        last = df.iloc[-1]
        q.update(price=_r(price), change=_r(price - prev) if prev else None, change_pct=_pct((price - prev) / prev * 100) if prev else None,
                 as_of=asof.isoformat(), stale=hstale or _age_days(asof.date().isoformat()) > (2 if t == "crypto" else 6),
                 day_high=_r(last.get("High")), day_low=_r(last.get("Low")), year_high=_r(df["High"].max()), year_low=_r(df["Low"].min()))
        if t in ("stock", "etf", "index") and float(last.get("Volume") or 0) > 0:
            q["volume"] = int(last["Volume"])
        if "yield" in note:
            q.update(**{"yield": _r(price), "yield_unit": "% per year"})
    if t in ("stock", "etf", "bond") and "yield" not in note:
        info = _info(sym)
        if not q["currency"]:
            q["currency"] = info.get("currency") or ""
        if it.get("generic") and (n := info.get("longName") or info.get("shortName")):
            q["name"] = n
        for k, src in (("market_cap", "marketCap"), ("pe_ratio", "trailingPE"), ("sector", "sector"), ("industry", "industry"), ("beta", "beta"),
                       ("dividend_per_share", "dividendRate"), ("dividend_yield_pct", "dividendYield"), ("eps_ttm", "trailingEps"), ("book_value_per_share", "bookValue"),
                       ("expense_ratio_pct", "netExpenseRatio"), ("net_assets", "netAssets"), ("fund_family", "fundFamily"), ("fund_category", "category")):
            if info.get(src) is not None:
                q[k] = info[src]
    if t == "crypto" and cg:
        if "CoinGecko" not in q["source"]:
            q["source"] += " + CoinGecko"
        q.update(market_cap=cg.get("market_cap"), volume_24h=cg.get("total_volume"), market_cap_rank=cg.get("market_cap_rank"),
                 high_24h=_r(cg.get("high_24h")), low_24h=_r(cg.get("low_24h")), circulating_supply=cg.get("circulating_supply"))
    elif t == "crypto":
        q["market_cap_note"] = "Market cap / volume unavailable right now (CoinGecko unreachable)."
    return q


def quote(it: dict) -> dict:
    """Latest price facts. Never raises for a known instrument: a dead source gives price=None, stale=True and an "error"."""
    try:
        if it["type"] == "mutual_fund":
            return _quote_mf(it)
        if it["symbol"] == "IN10Y":
            return _quote_in10y(it)
        return _quote_yahoo(it)
    except Exception as exc:
        logger.warning(f"quote {it['id']} failed: {type(exc).__name__}: {str(exc)[:120]}")
        q = _base_quote(it, "Live data is unavailable right now.")
        q["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return q


# ── history, chart ─────────────────────────────────────────────────────────────────────────────────────────────
RANGES = {"1d": ("1d", "5m"), "5d": ("5d", "15m"), "1m": ("1mo", "1h"), "6m": ("6mo", "1d"), "1y": ("1y", "1d"), "5y": ("5y", "1wk"), "max": ("max", "1mo")}
_RANGE_DAYS = {"1d": 1, "5d": 5, "1m": 31, "6m": 183, "1y": 366, "5y": 1830, "max": 40000}
_MAX_POINTS = 600


def _thin(pts: list[dict]) -> list[dict]:
    if len(pts) <= _MAX_POINTS:
        return pts
    step = math.ceil(len(pts) / _MAX_POINTS)
    return pts[::step][:-1] + [pts[-1]] if (len(pts) - 1) % step else pts[::step]


def _ts(d: str) -> int:
    return int(datetime.fromisoformat(d[:10]).replace(tzinfo=timezone.utc).timestamp())


def _chart_meta(rng: str, interval: str, it: dict, pts: list[dict], source: str, stale: bool, **extra: Any) -> dict:
    ch = (pts[-1]["v"] - pts[0]["v"]) / pts[0]["v"] * 100 if len(pts) > 1 and pts[0]["v"] else None
    return {"range": rng, "interval": interval, "currency": it["currency"], "source": source, "stale": stale, "count": len(pts),
            "start": pts[0]["t"] if pts else None, "end": pts[-1]["t"] if pts else None, "change_pct": _pct(ch) if ch is not None else None,
            "as_of": datetime.fromtimestamp(pts[-1]["t"], timezone.utc).isoformat() if pts else None, **extra}


def _cg_chart(it: dict, rng: str) -> list[dict]:
    cid = it.get("_cgid") or _cg_coin(it).get("id")
    if not cid:
        raise NoData("no CoinGecko id")
    days = {"1d": 1, "5d": 7, "1m": 30, "6m": 180}.get(rng, 365)
    js, _ = _cached(("cgchart", cid, days), 600, lambda: amfi.http_get(
        f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart?vs_currency=usd&days={days}", timeout=10).json())
    return [{"t": int(t // 1000), "v": _r(v)} for t, v in js["prices"]]


def chart(it: dict, rng: str = "1y") -> dict:
    rng = rng.lower()
    if rng not in RANGES:
        raise ValueError("range must be one of " + "|".join(RANGES))
    try:
        if it["type"] == "mutual_fund":
            meta, hist, stale = amfi.history(it["symbol"])
            if not hist:
                raise NoData("no NAV history")
            cutoff = (date.fromisoformat(hist[-1][0]) - timedelta(days=_RANGE_DAYS[rng])).isoformat()
            rows = [(d, v) for d, v in hist if d >= cutoff] if rng not in ("1d", "5d") else hist[-(2 if rng == "1d" else 6):]
            pts = _thin([{"t": _ts(d), "v": v} for d, v in rows])
            return {"points": pts, "meta": _chart_meta(rng, "1d (NAV)", it, pts, "mfapi.in", stale, note="One NAV per day; no intraday data for mutual funds.")}
        if it["symbol"] == "IN10Y":
            rows = _fred_in10y()
            cutoff = (date.fromisoformat(rows[-1][0]) - timedelta(days=_RANGE_DAYS[rng])).isoformat()
            pts = [{"t": _ts(d), "v": v} for d, v in rows if d >= cutoff]
            return {"points": pts, "meta": _chart_meta(rng, "1mo", it, pts, "FRED (OECD)", False, note="Monthly yield; short ranges show few points.")}
        period, interval = RANGES[rng]
        try:
            df, stale = _hist(it["symbol"], period, interval)
            if rng == "1d" and len(df) < 2:
                df, stale = _hist(it["symbol"], "5d", "15m")
                df = df[df.index.date == df.index[-1].date()]
            pts = _thin([{"t": int(ts.timestamp()), "v": _r(c)} for ts, c in df["Close"].items()])
            return {"points": pts, "meta": _chart_meta(rng, interval, it, pts, "Yahoo Finance", stale)}
        except Exception:
            if it["type"] != "crypto":
                raise
            pts = _thin(_cg_chart(it, rng))
            return {"points": pts, "meta": _chart_meta(rng, "auto", it, pts, "CoinGecko", False, note="CoinGecko free history covers at most 1 year.")}
    except Exception as exc:
        logger.warning(f"chart {it['id']} {rng} failed: {type(exc).__name__}")
        return {"points": [], "meta": {"range": rng, "currency": it["currency"], "stale": True, "count": 0, "source": it["source"],
                                      "error": f"{type(exc).__name__}: {str(exc)[:160]}"}}


def price_series(it: dict) -> tuple[list[tuple[str, float]], str, bool]:
    """Full daily history as [(iso date, price)] for returns and SIP: MF NAV, or dividend/split-adjusted Yahoo close."""
    if it["type"] == "mutual_fund":
        _, hist, stale = amfi.history(it["symbol"])
        if not hist:
            raise NoData("no NAV history")
        return hist, "mfapi.in NAV", stale
    if it["type"] in ("currency", "bond") or it["symbol"] == "IN10Y":
        raise Unsupported("a SIP simulation is not meaningful for this instrument type")
    df, stale = _hist(it["symbol"], "max", "1d")
    col = df["Adj Close"] if "Adj Close" in df and df["Adj Close"].notna().any() else df["Close"]
    return [(ts.date().isoformat(), float(v)) for ts, v in col.dropna().items()], "Yahoo Finance (dividend/split-adjusted close)", stale


# ── statistics from a price history ────────────────────────────────────────────────────────────────────────────
def return_stats(series: list[tuple[str, float]], crypto: bool = False) -> dict:
    if len(series) < 2:
        return {}
    s = pd.Series([p for _, p in series], index=pd.to_datetime([d for d, _ in series]))
    s = s[~s.index.duplicated()].sort_index()
    last_d, last = s.index[-1], float(s.iloc[-1])
    first_d, first = s.index[0], float(s.iloc[0])
    out: dict[str, Any] = {"first_date": first_d.date().isoformat(), "last_date": last_d.date().isoformat()}
    all_days = max((last_d - first_d).days, 0)
    if first > 0 and all_days >= 30:
        out["return_since_start_pct"] = _pct((last / first - 1) * 100)
        out["cagr_since_start_pct"] = _pct(((last / first) ** (365.25 / all_days) - 1) * 100)
    for name, days in (("1m", 30), ("3m", 91), ("6m", 182), ("1y", 365), ("3y", 1095), ("5y", 1825)):
        target = last_d - pd.Timedelta(days=days)
        if s.index[0] <= target + pd.Timedelta(days=5):
            base = float(s[:target].iloc[-1]) if (s.index <= target).any() else float(s.iloc[0])
            out[f"return_{name}_pct"] = _pct((last / base - 1) * 100)
            if days >= 1095:
                out[f"cagr_{name}_pct"] = _pct(((last / base) ** (365 / days) - 1) * 100)
    yr = s[s.index >= last_d - pd.Timedelta(days=365)]
    if len(yr) > 20:
        out["volatility_1y_pct"] = _pct(yr.pct_change().dropna().std() * math.sqrt(365 if crypto else 252) * 100)
        out["max_drawdown_1y_pct"] = _pct((yr / yr.cummax() - 1).min() * 100)
    out["max_drawdown_all_pct"] = _pct((s / s.cummax() - 1).min() * 100)
    return out


# ── SIP ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _xirr(flows: list[tuple[date, float]]) -> float | None:
    d0 = flows[0][0]
    f = lambda r: sum(c / (1 + r) ** ((d - d0).days / 365.0) for d, c in flows)  # noqa: E731
    lo, hi = -0.99, 50.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(120):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def simulate_sip(series: list[tuple[str, float]], monthly: float, years: float) -> dict:
    """Invest `monthly` on the first trading day of each month over the last `years` of the series (or all of it if shorter)."""
    s = pd.Series([p for _, p in series], index=pd.to_datetime([d for d, _ in series]))
    s = s[~s.index.duplicated()].sort_index()
    s = s[s > 0]
    if s.empty:
        raise NoData("no usable prices")
    end = s.index[-1]
    monthly_first = s.groupby([s.index.year, s.index.month]).head(1)
    requested_installments = max(1, int(round(years * 12)))
    first = monthly_first.tail(requested_installments)
    n = len(first)
    if n < 3:
        raise NoData("not enough price history for a SIP simulation (need at least 3 months)")
    w = s[s.index >= first.index[0]]
    units = pd.Series(0.0, index=w.index)
    units[first.index] = monthly / first.values
    cum = units.cumsum()
    value = cum * w
    invested, final = n * monthly, float(value.iloc[-1])
    days = (end - w.index[0]).days
    flows = [(d.date(), -monthly) for d in first.index] + [(end.date(), final)]
    x = _xirr(flows)
    run = value[cum > 0]
    inv_path = pd.Series(monthly, index=first.index).cumsum()
    return {"monthly": monthly, "installments": n, "start": w.index[0].date().isoformat(), "end": end.date().isoformat(),
            "years_used": round(n / 12, 2), "invested": round(invested, 2), "value": round(final, 2),
            "gain": round(final - invested, 2), "gain_pct": _pct((final / invested - 1) * 100),
            "xirr_pct": _pct(x * 100) if x is not None else None,
            "cagr_pct": _pct(((float(w.iloc[-1]) / float(w.iloc[0])) ** (365.25 / days) - 1) * 100) if days >= 30 else None,
            "worst_drawdown_pct": _pct((run / run.cummax() - 1).min() * 100),
            "series": [{"t": int(d.timestamp()), "invested": round(float(inv_path[d]), 2), "value": round(float(value[d]), 2)} for d in first.index]}


def sip(it: dict, monthly: float = 5000, years: float = 5) -> dict:
    series, basis, stale = price_series(it)
    res = simulate_sip(series, monthly, years)
    note = []
    if res["years_used"] < years - 0.2:
        note.append(f"Only {res['years_used']} years of history exist, so that is the period simulated.")
    if it["type"] == "mutual_fund" and it["_mf"].get("option") == "IDCW":
        note.append("This is an IDCW plan: payouts lower the NAV, so growth plans give a truer picture of returns.")
    return {"id": it["id"], "name": it["name"], "years_requested": years, **res, "currency": it["currency"], "caveat": CAVEAT,
            "method": "Fixed amount invested on the first trading day of each month at that day's close; XIRR from the dated cash flows; "
                      "CAGR is the asset's own price growth over the period; worst drawdown is the largest peak-to-trough fall of the SIP's value.",
            "meta": {"basis": basis, "stale": stale, "notes": note}}


# ── profile ────────────────────────────────────────────────────────────────────────────────────────────────────
_MF_KIND = {
    "equity": ("Invests mainly in company shares. Values can swing a lot year to year; it is built for long holding periods.", "high"),
    "debt": ("Lends to governments and companies through bonds. Usually steadier than shares, but moves with interest rates and can lose value if a borrower defaults.", "medium"),
    "hybrid": ("Mixes shares and bonds in one fund, so it is usually less jumpy than a pure equity fund.", "medium"),
    "solution": ("A goal-linked fund (retirement or children's) that is often subject to a lock-in.", "medium"),
    "other": ("An index fund, exchange-traded fund-of-funds or similar fund; risk follows what it tracks.", "medium"),
}
_TYPE_WHAT = {
    "stock": "A share of a company listed on the {ex} exchange. Owning it means owning a small part of the business; the price moves with the company's results and the market's mood.",
    "etf": "An exchange-traded fund: a basket of assets (shares, gold, bonds) that trades on an exchange like a share. It tracks an index or asset, so you get diversification in one purchase.",
    "crypto": "A digital currency or token that trades 24 hours a day on crypto exchanges. It is not issued by any government or bank and its price can move sharply.",
    "bond": "A bond-related instrument. Bonds are loans to a government or company that pay interest; their prices usually fall when interest rates rise.",
    "index": "A statistical measure of a group of securities (it is not something you can buy directly). Index funds and ETFs let you invest in its movements.",
    "commodity": "A futures price for a physical commodity such as gold, oil or wheat. Futures contracts expire and are rolled, so the quoted price can differ from the spot (cash) price.",
    "currency": "An exchange rate: how much of the second currency one unit of the first buys. Rates move with interest rates, trade flows and central-bank action.",
}


def _vol_tag(v: float | None) -> list[dict]:
    if v is None:
        return []
    lvl = "very high" if v > 50 else "high" if v > 30 else "medium" if v > 15 else "low"
    return [{"tag": f"{lvl.capitalize()} volatility", "level": "high" if lvl in ("very high", "high") else lvl,
             "why": f"The price swung about {v:.0f}% a year (annualised) over the last year."}]


def profile(it: dict) -> dict:
    t = it["type"]
    q = quote(it)
    stats: dict[str, Any] = {}
    try:
        series, basis, _ = price_series(it)
        stats = return_stats(series, crypto=t == "crypto")
    except Unsupported:
        pass
    except Exception as exc:
        logger.debug(f"profile stats {it['id']}: {type(exc).__name__}")
    rows: list[dict] = []
    tags: list[dict] = []
    desc = ""

    def add(label: str, value: Any, unit: str = "") -> None:
        if value is not None and value != "":
            if isinstance(value, (int, float)):
                num = f"{value:,}" if isinstance(value, int) else f"{value:,.2f}" if abs(value) >= 1 else f"{value:.6g}"
                rows.append({"label": label, "value": f"{num}{unit}"})
            else:
                rows.append({"label": label, "value": str(value)})

    what = _TYPE_WHAT.get(t, "").format(ex=it["exchange"] or "stock")
    if t == "mutual_fund":
        f = it["_mf"]
        cat = f["category"]
        c = cat.lower()
        head = ("equity" if "equity" in c else "hybrid" if re.search("hybrid|balanced|arbitrage", c) else
                "debt" if re.search("debt|income|liquid|money market|gilt|overnight|bond", c) else
                "solution" if re.search("solution|retirement|children", c) else "other")
        blurb, lvl = _MF_KIND[head]
        what = (f"A mutual fund run by {f['amc'] or 'an Indian fund house'} (category: {cat or 'not stated'}). You buy units at the day's NAV "
                f"(net asset value per unit). {blurb} {f['plan']} plan, {f['option']} option.")
        if f["option"] == "Growth":
            what += " Growth option: gains stay invested and are reflected in the NAV."
        elif f["option"] == "IDCW":
            what += " IDCW option: the fund may pay out part of its gains, which lowers the NAV."
        add("Latest NAV", q.get("nav"), " INR"); add("NAV date", q.get("nav_date")); add("1-day NAV change", q.get("change_pct"), "%")
        add("Category", cat); add("AMC", f["amc"]); add("Plan / option", f"{f['plan']} / {f['option']}"); add("ISIN", q.get("isin")); add("Scheme code", f["code"])
        add("Expense ratio", "Not in free data (see factsheet)")
        tags.append({"tag": f"{head.capitalize()} fund", "level": lvl, "why": blurb})
        if "liquid" in cat.lower() or "overnight" in cat.lower():
            tags[-1].update(level="low", why="Very short-term debt; the least volatile type of mutual fund.")
        if "elss" in cat.lower():
            tags.append({"tag": "3-year lock-in", "level": "medium", "why": "ELSS funds cannot be redeemed for 3 years."})
        if "sectoral" in cat.lower() or "thematic" in cat.lower():
            tags.append({"tag": "Concentrated", "level": "high", "why": "Sector and theme funds depend on a narrow slice of the market."})
    else:
        if q.get("yield") is None:
            add("Price", q.get("price"), f" {q['currency']}" if q.get("currency") else "")
        add("1-day change", q.get("change_pct"), "%")
        add("52-week high", q.get("year_high")); add("52-week low", q.get("year_low")); add("Market cap", q.get("market_cap"))
        add("P/E ratio", q.get("pe_ratio")); add("Sector", q.get("sector")); add("Industry", q.get("industry")); add("24h volume", q.get("volume_24h"))
        add("Market cap rank", q.get("market_cap_rank")); add("Expense ratio %", q.get("expense_ratio_pct")); add("Net assets", q.get("net_assets"))
        add("Yield", q.get("yield"), "%"); add("Exchange", it["exchange"])
        info = _info(it["symbol"]) if t in ("stock", "etf") else {}
        desc = (info.get("longBusinessSummary") or "")[:600]
    for k, label in (("return_1y_pct", "1-year return"), ("cagr_3y_pct", "3-year CAGR"), ("cagr_5y_pct", "5-year CAGR"),
                     ("cagr_since_start_pct", "CAGR since start"),
                     ("volatility_1y_pct", "1-year volatility"), ("max_drawdown_1y_pct", "Worst fall, last year")):
        add(label, stats.get(k), "%")
    tags += _vol_tag(stats.get("volatility_1y_pct"))
    dd = stats.get("max_drawdown_1y_pct")
    if dd is not None and dd < -30:
        tags.append({"tag": "Deep recent fall", "level": "high", "why": f"The price dropped about {abs(dd):.0f}% from a peak at some point in the last year."})
    if t == "stock":
        series_code = it.get("_series")
        if series_code and series_code != "EQ":
            tags.append({"tag": "Restricted / low-liquidity segment", "level": "high", "why": f"Listed in exchange series {series_code}, which can mean trade-for-trade settlement, surveillance or thin trading."})
        elif it.get("_tv", 1e9) < 5e6:
            tags.append({"tag": "Thinly traded", "level": "medium", "why": "Low daily traded value; it can be hard to buy or sell without moving the price."})
        tags.append({"tag": "Company-specific risk", "level": "medium", "why": "A single business can disappoint even when the market does well."})
    elif t == "crypto":
        tags += [{"tag": "Not legal tender, lightly regulated", "level": "high", "why": "No guarantee, deposit insurance or regulator backstop; Indian tax rules for crypto gains are strict."},
                 {"tag": "Trades 24x7", "level": "medium", "why": "Prices can move sharply at any hour, including weekends."}]
    elif t in ("bond",):
        tags.append({"tag": "Interest-rate risk", "level": "medium", "why": "Bond prices usually fall when interest rates rise."})
        if it["symbol"] == "IN10Y" or q.get("yield") is not None:
            tags.append({"tag": "Yield, not a price", "level": "low", "why": "The number shown is an annual percentage yield; you cannot buy it directly."})
        else:
            tags.append({"tag": "Credit and liquidity risk", "level": "medium", "why": "Corporate-bond ETFs carry borrower-default risk; some trade thinly."})
    elif t == "etf":
        tags.append({"tag": "Tracks an underlying", "level": "medium", "why": "It moves with its index or asset, plus a small tracking difference and expense ratio."})
    elif t == "index":
        tags.append({"tag": "Not directly investable", "level": "low", "why": "Invest through an index fund or ETF that tracks it."})
    elif t == "commodity":
        tags.append({"tag": "Futures contract", "level": "high", "why": "Futures expire and roll, and the price is in US dollars; it can differ from Indian spot prices."})
    elif t == "currency":
        tags.append({"tag": "Macro-driven", "level": "medium", "why": "Moves with interest rates, inflation, trade flows and central-bank decisions."})
    if q.get("price") is None:
        tags.append({"tag": "Live data unavailable", "level": "info", "why": q.get("error") or "A data source did not answer; figures may be missing."})
    return {"id": it["id"], "name": q.get("name") or it["name"], "type": t, "exchange": it["exchange"], "currency": it["currency"],
            "what_is": what, "description": desc, "key_stats": rows, "risk_tags": tags, "stats": stats, "disclaimer": DISCLAIMER,
            "meta": {"source": it["source"], "stale": q.get("stale", True), "as_of": q.get("as_of"), "coverage": COVERAGE.get(t, "")}}


def warm() -> None:
    """Background warm-up at API start: load the catalogue, the AMFI file and the coin list so the first search is instant."""
    for fn in (catalog, amfi.funds, lambda: _coingecko(True), _mf_pool):
        try:
            fn()
        except Exception as exc:
            logger.warning(f"instruments warm-up step skipped: {type(exc).__name__}")
