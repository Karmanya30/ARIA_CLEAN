"""
Data gathering for the equity-research intelligence layer.

Reuses ARIA's existing sources rather than adding new providers:

- screener.in (``screener_adapter``) -- multi-year statements. Fetched on the
  *consolidated* basis, because market cap and EPS from Yahoo are consolidated
  (Reliance: standalone TTM EPS 28.98 vs consolidated 55.22 == Yahoo's 55.21).
- yfinance -- price, shares, debt/cash, minority interest, weekly prices (beta),
  peer multiples, analyst targets, business profile.
- Google News' public RSS search -- company headlines (yfinance returns none for
  NSE tickers). Optional, soft-failing, switch off with FI_NEWS_RSS=0.

``build_snapshot`` is a pure function of already-fetched data, so tests exercise
the same parsing code with recorded fixtures; ``gather`` only adds the network.
"""
from __future__ import annotations

import functools
import math
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import requests
import yfinance as yf
from loguru import logger

from config import settings
from modules.equity_research.data_normalizer import _parse_numeric
from modules.equity_research.investment import search_company
from modules.equity_research.screener_adapter import get_screener_data
from shared.company_resolver import resolve_company
from shared.news import fetch_news

INDEX_SYMBOL = "^NSEI"  # Nifty 50 -- beta is measured against it
_CR = 1e7  # rupees per crore

# Peer sets for comparable-company analysis, keyed by the group _peer_group() assigns.
# Curated, not an index: the report lists exactly which peers were used, and any peer
# whose data fails is dropped (and counted) rather than guessed. Deliberately separate
# from modules/market/analyzer.py's 4-name sector-trend baskets, which are too small to
# leave a usable peer median once the subject company is removed.
PEER_GROUPS: dict[str, list[str]] = {
    "banks": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN", "INDUSINDBK", "BANKBARODA", "PNB", "FEDERALBNK"],
    "nbfc": ["BAJFINANCE", "CHOLAFIN", "SHRIRAMFIN", "MUTHOOTFIN", "M&MFIN", "LICHSGFIN"],
    "insurance": ["SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI", "LICI"],
    "it": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "PERSISTENT", "COFORGE", "MPHASIS"],
    "fmcg": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO", "GODREJCP", "COLPAL", "TATACONSUM"],
    "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA", "TORNTPHARM", "ZYDUSLIFE", "ALKEM"],
    "auto": ["MARUTI", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY", "TMPV"],
    "energy": ["RELIANCE", "ONGC", "IOC", "BPCL", "GAIL", "OIL", "HINDPETRO", "PETRONET"],
    "metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "SAIL", "NMDC", "COALINDIA"],
    "cement": ["ULTRACEMCO", "AMBUJACEM", "SHREECEM", "ACC", "DALBHARAT", "JKCEMENT"],
    "power": ["NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "NHPC", "JSWENERGY", "TORNTPOWER"],
    "industrials": ["LT", "SIEMENS", "ABB", "BHEL", "HAL", "BEL", "CUMMINSIND"],
    "retail": ["TITAN", "TRENT", "DMART", "PAGEIND", "JUBLFOOD", "NYKAA"],
    "chemicals": ["ASIANPAINT", "BERGEPAINT", "PIDILITIND", "SRF", "UPL"],
    "realty": ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "LODHA"],
    "telecom": ["BHARTIARTL", "INDUSTOWER", "TATACOMM"],
}

# (substring of Yahoo's industry/sector, peer group) -- first match wins.
_GROUP_RULES: tuple[tuple[str, str], ...] = (
    ("banks", "banks"), ("credit services", "nbfc"), ("mortgage finance", "nbfc"),
    ("insurance", "insurance"), ("information technology", "it"), ("software", "it"),
    ("household", "fmcg"), ("packaged foods", "fmcg"), ("tobacco", "fmcg"), ("beverages", "fmcg"),
    ("confectioners", "fmcg"), ("drug manufacturers", "pharma"), ("auto", "auto"),
    ("oil & gas", "energy"), ("steel", "metals"), ("aluminum", "metals"), ("copper", "metals"),
    ("building materials", "cement"), ("utilities", "power"), ("telecom", "telecom"),
    ("engineering & construction", "industrials"), ("electrical equipment", "industrials"),
    ("specialty industrial", "industrials"), ("aerospace", "industrials"),
    ("luxury", "retail"), ("apparel retail", "retail"), ("internet retail", "retail"),
    ("specialty retail", "retail"), ("specialty chemicals", "chemicals"), ("real estate", "realty"),
)

# Yahoo fields kept on the snapshot (everything else in .info is ignored).
_INFO_KEYS = (
    "grossMargins", "currentRatio", "quickRatio", "netIncomeToCommon",
    "heldPercentInsiders", "heldPercentInstitutions", "recommendationKey", "recommendationMean",
    "shortName", "longName", "sector", "industry", "currency", "financialCurrency",
    "currentPrice", "regularMarketPrice", "marketCap", "sharesOutstanding", "impliedSharesOutstanding",
    "trailingPE", "forwardPE", "priceToBook", "bookValue", "trailingEps", "forwardEps",
    "enterpriseValue", "enterpriseToEbitda", "totalDebt", "totalCash", "dividendRate", "payoutRatio",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "numberOfAnalystOpinions", "recommendationKey", "longBusinessSummary", "fullTimeEmployees",
    "website", "companyOfficers", "revenueGrowth", "operatingMargins", "returnOnEquity", "totalRevenue", "ebitda",
    "enterpriseToRevenue", "dividendYield", "exchange", "fullExchangeName",
)


# ── small helpers ──────────────────────────────────────────────────────────
def _num(value: Any) -> float | None:
    """A finite float or None (Yahoo returns strings, NaN and None for missing data)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _ttl_cache(seconds: int) -> Callable:
    """Cache successful results for ``seconds``. Functions raise on failure, so a
    failed fetch is never cached (unlike lru_cache, which is what the older modules
    use and which never refreshes)."""

    def decorator(fn: Callable) -> Callable:
        store: dict[tuple, tuple[float, Any]] = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args: Any) -> Any:
            with lock:
                hit = store.get(args)
                if hit and time.monotonic() - hit[0] < seconds:
                    return hit[1]
            value = fn(*args)
            with lock:
                store[args] = (time.monotonic(), value)
            return value

        wrapper.cache_clear = store.clear  # type: ignore[attr-defined]
        return wrapper

    return decorator


# Yahoo reports some Indian IT companies' statements in USD while prices are in INR (Infosys: revenue
# "2,030 Cr", EV/EBITDA 905x, EV/Sales 202x). Every statement-derived Yahoo field is then in the wrong
# currency, so those fields are dropped at the source instead of being filtered out later.
_STATEMENT_FIELDS = ("enterpriseToEbitda", "enterpriseToRevenue", "ebitda", "totalRevenue", "netIncomeToCommon")


def _currency_mismatch(info: dict) -> bool:
    fc, c = info.get("financialCurrency"), info.get("currency")
    return bool(fc and c and fc != c)


def _cr(rupees: Any) -> float | None:
    """Yahoo reports absolute rupees; the report works in crore."""
    v = _num(rupees)
    return v / _CR if v else None


def row(table: dict, *names: str) -> dict[str, float | None]:
    """Year-keyed values of the first row (case-insensitive) matching any of ``names``."""
    rows = {k.lower(): v for k, v in table.get("rows", {}).items()}
    for name in names:
        if name.lower() in rows:
            return rows[name.lower()]
    return {}


def annual_cols(table: dict) -> list[str]:
    """Fiscal-year columns only: screener's P&L also carries a TTM column that
    overlaps the last fiscal year and must never be treated as another year."""
    return [c for c in table.get("cols", []) if c != "TTM"]


def numeric_table(raw: dict) -> dict:
    """screener's {"__columns__": [...], "Row": {"Mar 2025": "1,234"}} -> numeric rows."""
    cols = list(raw.get("__columns__", []))
    rows = {
        name: {c: _parse_numeric(vals.get(c)) for c in cols}
        for name, vals in raw.items()
        if name != "__columns__" and isinstance(vals, dict)
    }
    return {"cols": cols, "rows": rows}


# ── targets and snapshot ───────────────────────────────────────────────────
@dataclass(frozen=True)
class Target:
    slug: str  # screener.in slug (== NSE symbol for almost every listed company)
    symbol: str  # Yahoo symbol, e.g. "RELIANCE.NS"
    name: str


@dataclass(frozen=True)
class Peer:
    symbol: str
    name: str
    pe: float | None
    pb: float | None
    ev_ebitda: float | None
    mcap_cr: float | None = None
    fwd_pe: float | None = None
    ev_sales: float | None = None
    ev_cr: float | None = None
    revenue_cr: float | None = None
    ebitda_cr: float | None = None
    net_income_cr: float | None = None  # Yahoo's "net income to common": trailing EPS x shares would be equivalent
    rev_growth: float | None = None  # Yahoo's latest-quarter YoY revenue growth, fraction
    op_margin: float | None = None  # fraction
    roe: float | None = None  # fraction


@dataclass
class Snapshot:
    target: Target
    as_of: str
    view: str  # "consolidated" | "standalone" | "unavailable"
    tables: dict[str, dict]  # pl, bs, cf, ratios, quarterly -> {"cols": [...], "rows": {...}}
    info: dict[str, Any]
    is_financial: bool
    nci_cr: float | None = None
    stock_returns: list[float] = field(default_factory=list)  # weekly, aligned with index_returns
    index_returns: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)  # weekly closes, oldest first
    peers: list[Peer] = field(default_factory=list)
    peer_group: str | None = None
    news: list[dict] = field(default_factory=list)
    wiki: list[dict] = field(default_factory=list)  # encyclopedic background: {kind, title, text, url}
    warnings: list[str] = field(default_factory=list)
    pledged_pct: float | None = None  # % of promoter holding pledged, only when screener.in's remarks flag it
    yf_statements: dict | None = None  # latest annual balance-sheet rows + EBIT from Yahoo: {as_of, rows, ebit}, absolute units

    def as_peer(self) -> "Peer":
        """The subject in the same shape as its peers, for like-for-like benchmarking."""
        return _peer_from_info(self.target.slug, self.name, self.info)

    @property
    def name(self) -> str:
        return self.info.get("longName") or self.info.get("shortName") or self.target.name

    @property
    def price(self) -> float | None:
        return _num(self.info.get("currentPrice")) or _num(self.info.get("regularMarketPrice")) or (
            self.closes[-1] if self.closes else None
        )

    @property
    def shares(self) -> float | None:
        return _num(self.info.get("sharesOutstanding")) or _num(self.info.get("impliedSharesOutstanding"))

    @property
    def market_cap_cr(self) -> float | None:
        return _cr(self.info.get("marketCap"))

    @property
    def exchange(self) -> str:
        return "BSE" if self.target.symbol.endswith(".BO") else "NSE"

    @property
    def net_debt_cr(self) -> float | None:
        debt, cash = _num(self.info.get("totalDebt")), _num(self.info.get("totalCash"))
        return (debt - cash) / _CR if debt is not None and cash is not None else None


def _peer_group(sector: str | None, industry: str | None) -> str | None:
    text = f"{industry or ''} {sector or ''}".lower()
    return next((group for needle, group in _GROUP_RULES if needle in text), None)


def _aligned_weekly_returns(
    stock: list[tuple[str, float]], index: list[tuple[str, float]]
) -> tuple[list[float], list[float]]:
    by_date = dict(index)
    pairs = [(close, by_date[d]) for d, close in stock if d in by_date]
    if len(pairs) < 2:
        return [], []
    s = [pairs[i][0] / pairs[i - 1][0] - 1 for i in range(1, len(pairs)) if pairs[i - 1][0] and pairs[i - 1][1]]
    m = [pairs[i][1] / pairs[i - 1][1] - 1 for i in range(1, len(pairs)) if pairs[i - 1][0] and pairs[i - 1][1]]
    return s, m


def build_snapshot(
    target: Target,
    *,
    screener_raw: dict | None,
    info: dict | None,
    nci_cr: float | None = None,
    stock_weekly: list[tuple[str, float]] | None = None,
    index_weekly: list[tuple[str, float]] | None = None,
    peers: list[Peer] | None = None,
    news: list[dict] | None = None,
    wiki: list[dict] | None = None,
    warnings: list[str] | None = None,
    as_of: str | None = None,
    yf_statements: dict | None = None,
) -> Snapshot:
    """Assemble a Snapshot from fetched data. Pure -- no network, no LLM."""
    warnings = list(warnings or [])
    info = {k: v for k, v in (info or {}).items() if k in _INFO_KEYS}
    if _currency_mismatch(info):
        info = {k: v for k, v in info.items() if k not in _STATEMENT_FIELDS}
        nci_cr, yf_statements = None, None
        warnings.append(f"Yahoo Finance reports this company's statements in {info.get('financialCurrency')} but prices in "
                        f"{info.get('currency')}: its revenue, EBITDA, EV/EBITDA, EV/Sales and balance-sheet fields were ignored")
    tables: dict[str, dict] = {}
    view = "unavailable"
    if screener_raw and "error" not in screener_raw:
        view = screener_raw.get("view", "standalone")
        for key, raw_key in (
            ("pl", "profit_loss"), ("bs", "balance_sheet"), ("cf", "cash_flow"),
            ("ratios", "ratios"), ("quarterly", "quarterly_results"), ("shp", "shareholding"),
        ):
            tables[key] = numeric_table(screener_raw.get(raw_key, {}))
        if view != "consolidated":
            warnings.append(
                "screener.in has no consolidated statements for this company: figures are "
                "standalone, so per-share values may not match Yahoo's consolidated market data"
            )
    elif screener_raw:
        warnings.append(str(screener_raw["error"]))

    pl_rows = {k.lower() for k in tables.get("pl", {}).get("rows", {})}
    is_financial = info.get("sector") == "Financial Services" or "financing profit" in pl_rows
    s_ret, i_ret = _aligned_weekly_returns(stock_weekly or [], index_weekly or [])
    pledged = _num((screener_raw or {}).get("pledged_pct"))
    return Snapshot(
        target=target,
        as_of=as_of or date.today().isoformat(),
        view=view,
        tables=tables,
        info=info,
        is_financial=is_financial,
        nci_cr=nci_cr,
        stock_returns=s_ret,
        index_returns=i_ret,
        closes=[c for _, c in (stock_weekly or [])],
        peers=list(peers or []),
        peer_group=_peer_group(info.get("sector"), info.get("industry")),
        news=list(news or []),
        wiki=list(wiki or []),
        warnings=warnings,
        pledged_pct=pledged,
        yf_statements=yf_statements,
    )


# ── network fetchers (cached; raise on failure so failures are not cached) ──
@_ttl_cache(900)
def _screener(slug: str) -> dict:
    data = get_screener_data(slug, consolidated=True)
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


@_ttl_cache(300)
def _yf_info(symbol: str) -> dict:
    info = yf.Ticker(symbol).info or {}
    if not info:
        raise RuntimeError(f"Yahoo Finance returned no data for {symbol}")
    return info


@_ttl_cache(900)
def _yf_weekly(symbol: str) -> list[tuple[str, float]]:
    hist = yf.Ticker(symbol).history(period="5y", interval="1wk")
    if hist is None or hist.empty:
        raise RuntimeError(f"no weekly price history for {symbol}")
    return [(idx.strftime("%Y-%m-%d"), float(c)) for idx, c in hist["Close"].dropna().items()]


# Latest annual balance-sheet rows kept from Yahoo (screener.in does not itemise current assets and liabilities).
_YF_BS_ROWS = ("Total Assets", "Current Assets", "Current Liabilities", "Working Capital", "Retained Earnings",
               "Total Liabilities Net Minority Interest", "Minority Interest")


@_ttl_cache(900)
def _yf_balance_sheet(symbol: str) -> dict | None:
    """{"as_of": "2026-03-31", "rows": {row: absolute value}} for the latest annual balance sheet; None if Yahoo has none."""
    bs = yf.Ticker(symbol).balance_sheet
    if bs is None or bs.empty:
        return None
    col = bs.columns[0]
    rows = {k: v for k in _YF_BS_ROWS if k in bs.index and (v := _num(bs.loc[k, col])) is not None}
    return {"as_of": col.strftime("%Y-%m-%d"), "rows": rows}


def _peer_from_info(symbol: str, name: str, info: dict) -> Peer:
    mismatch = _currency_mismatch(info)  # statement fields are in another currency: leave them out
    stmt = (lambda v: None) if mismatch else (lambda v: v)
    return Peer(
        symbol=symbol,
        name=name,
        pe=_num(info.get("trailingPE")),
        pb=_num(info.get("priceToBook")),
        ev_ebitda=stmt(_num(info.get("enterpriseToEbitda"))),
        mcap_cr=_cr(info.get("marketCap")),
        fwd_pe=_num(info.get("forwardPE")),
        ev_sales=stmt(_num(info.get("enterpriseToRevenue"))),
        ev_cr=_cr(info.get("enterpriseValue")),
        revenue_cr=stmt(_cr(info.get("totalRevenue"))),
        ebitda_cr=stmt(_cr(info.get("ebitda"))),
        net_income_cr=stmt(_cr(info.get("netIncomeToCommon"))),
        rev_growth=_num(info.get("revenueGrowth")),
        op_margin=_num(info.get("operatingMargins")),
        roe=_num(info.get("returnOnEquity")),
    )


@_ttl_cache(900)
def _peer(symbol: str) -> Peer:
    info = yf.Ticker(f"{symbol}.NS").info or {}
    if not info:
        raise RuntimeError(f"no data for peer {symbol}")
    return _peer_from_info(symbol, info.get("shortName") or symbol, info)


def fetch_peers(group: str | None, exclude_slug: str) -> tuple[list[Peer], list[str]]:
    """Peers of ``group`` (minus the subject). Returns (peers, symbols that failed)."""
    if not group:
        return [], []
    symbols = [s for s in PEER_GROUPS[group] if s != exclude_slug]
    peers: list[Peer] = []
    failed: list[str] = []

    def one(sym: str) -> Peer | None:
        try:
            return _peer(sym)
        except Exception as exc:  # a delisted/renamed peer must not sink the report
            logger.warning(f"peer {sym} unavailable: {exc}")
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for sym, peer in zip(symbols, pool.map(one, symbols)):
            if peer:
                peers.append(peer)
            else:
                failed.append(sym)
    return peers, failed


_LEGAL_SUFFIX = re.compile(r"\b(ltd|limited|corporation|corp|inc)\.?\s*$", re.IGNORECASE)


def get_company_news(name: str, limit: int = 8, max_age_days: int = 45) -> list[dict]:
    """Recent dated headlines via Google News' public RSS search. Never raises."""
    if not settings.FI_NEWS_RSS or not name:
        return []
    query = urllib.parse.quote(f'"{_LEGAL_SUFFIX.sub("", name).strip()}" when:30d')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        res = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
        root = ET.fromstring(res.content)
    except Exception as exc:
        logger.warning(f"company news unavailable for {name!r}: {exc}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    items, seen = [], set()
    for item in root.iter("item"):
        source = (item.findtext("source") or "").strip()
        title = re.sub(r"[\x00-\x1f\x7f]", " ", item.findtext("title", "")).strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
        except (TypeError, ValueError):
            continue
        key = title.lower()[:60]
        if not title or key in seen or published < cutoff:
            continue
        seen.add(key)
        items.append({"title": title[:200], "source": source[:60], "date": published.date().isoformat()})
    # plus what the Indian and global business feeds carry about the company (more sources, corroboration)
    for n in fetch_news(_LEGAL_SUFFIX.sub("", name).strip(), limit=limit, max_age_hours=max_age_days * 24, google=False):
        key = n["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            items.append({"title": n["title"][:200], "source": n["source"][:60], "date": n["published"].date().isoformat()})
    return sorted(items, key=lambda i: i["date"], reverse=True)[:limit]


@_ttl_cache(86400)
def _wiki_summary(query: str) -> dict | None:
    """Best Wikipedia article for ``query`` (first search hit) as {title, text, url}; None if there is no usable article."""
    headers = {"User-Agent": "ARIA/1.0 (educational research tool)"}
    hit = requests.get("https://en.wikipedia.org/w/api.php", timeout=8, headers=headers,
                       params={"action": "opensearch", "search": query, "limit": 1, "format": "json", "redirects": "resolve"})
    hit.raise_for_status()
    titles = hit.json()[1]
    if not titles:
        return None
    page = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(titles[0].replace(" ", "_")), timeout=8, headers=headers)
    page.raise_for_status()
    d = page.json()
    text = re.sub(r"[\x00-\x1f\x7f]", " ", d.get("extract") or "").strip()
    if d.get("type") != "standard" or len(text) < 150:
        return None
    return {"title": d.get("title", titles[0]), "text": text[:900], "url": (d.get("content_urls") or {}).get("desktop", {}).get("page", "")}


def get_wiki_context(name: str, industry: str | None) -> list[dict]:
    """Encyclopedic background on the company and its industry. Soft-fails to []. The company article must
    share its first word with the company name, so a wrong-company match is dropped rather than shown."""
    out = []
    company = _LEGAL_SUFFIX.sub("", name or "").strip()
    for kind, query in (("Company", company), ("Industry", f"{industry} industry" if industry else "")):
        if not query:
            continue
        try:
            d = _wiki_summary(query)
        except Exception as exc:
            logger.warning(f"wikipedia unavailable for {query!r}: {exc}")
            continue
        if d and (kind == "Industry" or company.split()[0].lower() in d["title"].lower()):
            out.append({**d, "kind": kind})
    return out


def gather(target: Target) -> Snapshot:
    """Fetch everything for one company (concurrently) and build the Snapshot.
    Any single source failing degrades the report (and is recorded in
    ``warnings``) rather than aborting it."""
    warnings: list[str] = []

    def safe(fn: Callable, *args: Any, what: str) -> Any:
        try:
            return fn(*args)
        except Exception as exc:
            logger.warning(f"{what} unavailable for {target.symbol}: {exc}")
            warnings.append(f"{what} unavailable: {exc}")
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_scr = pool.submit(safe, _screener, target.slug, what="screener.in statements")
        f_info = pool.submit(safe, _yf_info, target.symbol, what="Yahoo Finance quote/profile")
        f_stock = pool.submit(safe, _yf_weekly, target.symbol, what="weekly price history")
        f_index = pool.submit(safe, _yf_weekly, INDEX_SYMBOL, what="Nifty price history")
        f_bs = pool.submit(safe, _yf_balance_sheet, target.symbol, what="Yahoo Finance balance sheet")
        screener_raw, info = f_scr.result(), f_info.result()
        stock, index, bs = f_stock.result(), f_index.result(), f_bs.result()
    mi = (bs or {}).get("rows", {}).get("Minority Interest")
    nci = mi / _CR if mi is not None else None

    info = info or {}
    group = _peer_group(info.get("sector"), info.get("industry"))
    name = info.get("longName") or info.get("shortName") or target.name
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_peers = pool.submit(fetch_peers, group, target.slug)
        f_news = pool.submit(get_company_news, name)
        f_wiki = pool.submit(get_wiki_context, name, info.get("industry"))
        (peers, failed), news, wiki = f_peers.result(), f_news.result(), f_wiki.result()
    if failed:
        warnings.append(f"peer data unavailable for: {', '.join(failed)}")

    return build_snapshot(
        target,
        screener_raw=screener_raw,
        info=info,
        nci_cr=nci,
        stock_weekly=stock,
        index_weekly=index,
        peers=peers,
        news=news,
        wiki=wiki,
        warnings=warnings,
        yf_statements=bs,
    )


# ── resolving the company a query is about ─────────────────────────────────
_INTENT_WORDS = re.compile(
    r"\b(equity|research|report|valuation|dcf|ddm|fair|value|intrinsic|target|price|investment|thesis|"
    r"bull|bear|case|initiate|initiating|coverage|full|detailed|deep|dive|analysis|analyse|analyze|give|"
    r"generate|write|prepare|create|make|show|me|a|an|the|on|of|for|about|is|over|under|valued|overvalued|"
    r"undervalued|stock|share|shares|please|and|vs|versus|with|to|buy|sell|hold)\b",
    re.IGNORECASE,
)


def resolve_target(query: str) -> Target | None:
    """Alias table first (no network), then Yahoo search via the existing
    ``search_company``. Only NSE/BSE listings are supported."""
    slug = resolve_company(query)
    if slug:
        return Target(slug=slug, symbol=f"{slug}.NS", name=slug)
    found = search_company(_INTENT_WORDS.sub(" ", query))
    if not found or not found["ticker"].endswith((".NS", ".BO")):
        return None
    return Target(slug=re.sub(r"\.(NS|BO)$", "", found["ticker"]), symbol=found["ticker"], name=found["company_name"])
