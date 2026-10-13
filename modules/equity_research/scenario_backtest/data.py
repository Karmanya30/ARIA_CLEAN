"""Owner: scenario backtest WP1. Screener.in statements cached long-format on disk, data-quality rules, prices.

Statements come from screener.in (12 fiscal years); Yahoo is used for prices only. screener.in has no public API and
its terms may restrict automated access: fetch_tables keeps the rate low (1 concurrent, 3-6 s jitter, backoff,
30-day cache) and the report pipeline saves what it already fetched, so reports add no extra requests.
"""
from __future__ import annotations

import calendar
import contextlib
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

from config.paths import DATA_DIR
from modules.equity_research.forecast import data as fdata
from modules.equity_research.intelligence.data import numeric_table, row

CACHE_DIR = DATA_DIR / "scenario_backtest"
CACHE_TTL_S = 30 * 24 * 3600
MAX_CONCURRENT = 1
JITTER = (3.0, 6.0)
RETRIES = 5
TABLES = ("pl", "bs", "cf", "ratios", "quarterly")
FY_TABLES = ("pl", "bs", "cf", "ratios")
MIN_YEARS = 4          # full history: 3y CAGR needs 4 points (headline cells)
SHORT_MIN_YEARS = 2    # valuation.py truly needs 2 fiscal years at T (one YoY growth; margins are medians of what exists)
MIN_TOTAL_YEARS = SHORT_MIN_YEARS + 1  # ... plus one later reported year to score against
SHORT_MAX_COMPANY_YEARS = 7  # short-history origins are generated only for companies with at most this many fiscal years
CONNECT_RETRIES, BREAKER_FAILS, BREAKER_BASE_S, BREAKER_MAX_S = 2, 3, 900, 7200
PRICE_TTL_S = 30 * 24 * 3600
_YF_FALLBACK = "yfinance"
BREAK_REVENUE, BREAK_ASSETS, SHARE_JUMP, RESTATE_TOL = 0.60, 0.50, 0.30, 0.01
_COL = re.compile(r"^([A-Z][a-z]{2}) (\d{4})$")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}


def fye(col: str) -> date:
    """'Mar 2026' -> 2026-03-31 (last day of the period). ValueError for TTM or anything else."""
    m = _COL.match(col or "")
    if not m or m.group(1) not in list(calendar.month_abbr)[1:]:
        raise ValueError(f"not a period column: {col!r}")
    month, year = list(calendar.month_abbr).index(m.group(1)), int(m.group(2))
    return date(year, month, calendar.monthrange(year, month)[1])


def _parse(col: str) -> date | None:
    try:
        return fye(col)
    except ValueError:
        return None


def _path(symbol: str, ext: str) -> Path:
    return CACHE_DIR / f"{re.sub(r'[^A-Za-z0-9_.^-]', '_', symbol)}.{ext}"


# ── cache ──────────────────────────────────────────────────────────────────
def _long(tables: dict) -> pd.DataFrame:
    recs = [(t, r, c, v) for t, tb in tables.items() for r, vals in tb["rows"].items() for c, v in vals.items()]
    return pd.DataFrame(recs, columns=["table", "row", "col", "value"]).astype({"value": "float64"})


def _sha1(tables: dict) -> str:
    return hashlib.sha1(json.dumps({t: [tb["cols"], tb["rows"]] for t, tb in sorted(tables.items())}, sort_keys=True, default=str).encode()).hexdigest()


def _restated(old: pd.DataFrame, new: pd.DataFrame) -> list[str]:
    m = old.merge(new, on=["table", "row", "col"], suffixes=("_o", "_n")).dropna()
    m = m[(m.value_o - m.value_n).abs() > RESTATE_TOL * m.value_o.abs().clip(lower=1e-9)]
    return [f"{r.table}/{r.row}/{r.col}: {r.value_o:g} -> {r.value_n:g}" for r in m.itertuples()]


def save_tables(symbol: str, tables: dict, meta: dict) -> dict:
    """Write the long-format parquet and its meta. Overlapping values that moved > 1% since the last save are
    logged as restated (meta.issues). tables: {"pl": {"cols": [...], "rows": {row: {col: value}}}, ...}."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tables = {t: tb for t, tb in tables.items() if t in TABLES and tb}
    df, p = _long(tables), _path(symbol, "parquet")
    issues = [i for i in meta.get("issues", [])]
    if p.exists():
        try:
            restated = _restated(pd.read_parquet(p), df)
        except Exception:
            restated = []
        if restated:
            logger.info(f"{symbol}: {len(restated)} values restated since the last cache")
            issues.append({"reason": "restated", "n": len(restated), "examples": restated[:10]})
    fys = sorted({c for t in FY_TABLES for c in tables.get(t, {}).get("cols", []) if _parse(c)}, key=fye)
    out = {**meta, "symbol": symbol, "provider": meta.get("provider", "screener.in"), "view": meta.get("view", "consolidated"),
           "retrieved_at_utc": meta.get("retrieved_at_utc") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "fiscal_years": fys, "columns": {t: tb["cols"] for t, tb in tables.items()}, "sha1": _sha1(tables), "issues": issues}
    df.to_parquet(p)
    _path(symbol, "meta.json").write_text(json.dumps(out, default=str))
    return out


def load(symbol: str) -> tuple[dict, dict]:
    """(tables, meta) from the cache; FileNotFoundError when absent."""
    df, meta = pd.read_parquet(_path(symbol, "parquet")), json.loads(_path(symbol, "meta.json").read_text())
    tables = {}
    for t, cols in meta["columns"].items():
        rows: dict[str, dict] = {}
        sub = df[df.table == t]
        for r, c, v in zip(sub.row, sub.col, sub.value):
            rows.setdefault(r, {})[c] = None if v != v else float(v)
        tables[t] = {"cols": list(cols), "rows": {r: {c: vals.get(c) for c in cols} for r, vals in rows.items()}}
    return tables, meta


def cached(symbol: str) -> bool:
    return _path(symbol, "parquet").exists() and _path(symbol, "meta.json").exists()


# ── polite screener.in fetch ───────────────────────────────────────────────
@contextlib.contextmanager
def _slot():
    """At most MAX_CONCURRENT screener.in requests across all processes, 2-4 s jitter before the slot is freed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fds = [os.open(str(CACHE_DIR / f".screener_slot{i}"), os.O_RDWR | os.O_CREAT) for i in range(MAX_CONCURRENT)]
    held = None
    try:
        while held is None:
            held = next((fd for fd in fds if fdata._try_lock(fd)), None)
            if held is None:
                time.sleep(0.1 + random.random() * 0.2)
        yield
        time.sleep(random.uniform(*JITTER))
    finally:
        for fd in fds:
            os.close(fd)


class Transient(Exception):
    """Network-level failure (timeout, connect error, 429, 5xx): the job should be retried later, never recorded as failed."""


def is_transient(e: BaseException) -> bool:
    if isinstance(e, (Transient, requests.RequestException)):
        return True
    reason = getattr(e, "reason", None)  # forecast.data.DataUnavailable
    t = f"{type(e).__name__} {e}".lower()
    return reason == "download_error" or any(k in t for k in ("429", "too many requests", "rate limit", "timed out", "timeout", "connection"))


def _breaker_path() -> Path:
    return CACHE_DIR / ".screener_breaker.json"


def _breaker() -> dict:
    try:
        return json.loads(_breaker_path().read_text())
    except Exception:
        return {}


def breaker_open() -> bool:
    """True while screener.in is considered down (BREAKER_FAILS consecutive connect failures across all processes)."""
    return time.time() < _breaker().get("open_until", 0)


def reset_breaker() -> None:
    with contextlib.suppress(OSError):
        _breaker_path().unlink()


def _note(ok: bool) -> None:
    """Record a screener.in outcome. Success closes the breaker; failures open it for 15 min, doubling up to 2 h
    (after a re-opened probe a single failure re-opens it). Not atomic across processes: good enough for a breaker."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if ok:
            reset_breaker()
            return
        b = _breaker()
        b["fails"] = b.get("fails", 0) + 1
        if b["fails"] >= (1 if b.get("level") else BREAKER_FAILS):
            b.update(fails=0, level=b.get("level", 0) + 1, open_until=time.time() + min(BREAKER_BASE_S * 2 ** b.get("level", 0), BREAKER_MAX_S))
        _breaker_path().write_text(json.dumps(b))
    except OSError:
        pass


def _get(url: str) -> requests.Response:
    """GET with exponential backoff on 429/5xx; connect errors/timeouts give up after CONNECT_RETRIES attempts (feeds the
    breaker). Retry-After is honoured. Raises requests.RequestException or Transient when it gives up."""
    for attempt in range(RETRIES):
        wait = 2 ** (attempt + 1) + random.random()
        try:
            with _slot():
                res = requests.get(url, headers=_HEADERS, timeout=(8, 25))
            if res.status_code in (200, 404):
                _note(True)
                return res
            if res.status_code == 429 or res.status_code >= 500:
                with contextlib.suppress(ValueError):
                    wait = max(wait, float(res.headers.get("Retry-After", 0)))
            else:
                res.raise_for_status()
        except requests.RequestException as e:
            conn = isinstance(e, (requests.ConnectionError, requests.Timeout))
            if attempt == RETRIES - 1 or (conn and attempt >= CONNECT_RETRIES - 1):
                if conn:
                    _note(False)
                raise
            logger.warning(f"screener.in {url}: {type(e).__name__}; retry in {wait:.0f}s")
        if attempt < RETRIES - 1:
            time.sleep(wait)
    _note(False)
    raise Transient(f"screener.in kept answering 429/5xx for {url}")


def _from_screener(slug: str, symbol: str) -> tuple[dict, dict]:
    from bs4 import BeautifulSoup

    from modules.equity_research.screener_adapter import Screener

    base = f"https://www.screener.in/company/{slug.upper().strip()}/"
    res = _get(base + "consolidated/")
    if res.status_code == 404:
        res = _get(base)
    if res.status_code != 200:
        raise LookupError(f"no_screener_page ({slug}: status {res.status_code})")
    scr = Screener()

    def _tables(r):
        soup = BeautifulSoup(r.text, "html.parser")
        return {k: numeric_table(scr._scrape_table(soup, sid)) for k, sid in
                (("pl", "profit-loss"), ("bs", "balance-sheet"), ("cf", "cash-flow"), ("ratios", "ratios"), ("quarterly", "quarters"))}

    tables = _tables(res)
    if not tables["pl"]["rows"] and res.url.rstrip("/").endswith("/consolidated"):
        # companies with no consolidated accounts answer 200 with an empty consolidated table (not 404): use the standalone page
        alt = _get(base)
        if alt.status_code == 200:
            res, tables = alt, _tables(alt)
    info = fdata._info(symbol)
    nse = re.search(r"nseindia\.com/get-quotes/equity\?symbol=([A-Za-z0-9&%-]+)", res.text)
    meta = {"provider": "screener.in", "view": "consolidated" if res.url.rstrip("/").endswith("/consolidated") else "standalone",
            "sector": info.get("sector"), "industry": info.get("industry"), "nse_symbol": nse.group(1) if nse else None,
            "is_financial": info.get("sector") == "Financial Services" or "financing profit" in {k.lower() for k in tables["pl"]["rows"]}}
    return tables, meta


def fetch_tables(slug: str, *, symbol: str | None = None, force: bool = False, fallback: bool = True) -> tuple[dict, dict]:
    """Statements for ``slug``: cache (30-day TTL) -> screener.in -> yfinance annual statements (``fallback``).

    Returns (tables, meta); meta.provider says which source filled it. Raises LookupError when neither source has the
    company and Transient when a source was only unreachable (the caller should retry later, not record a failure)."""
    symbol = symbol or f"{slug.upper()}.NS"
    p = _path(symbol, "parquet")
    if not force and cached(symbol) and time.time() - p.stat().st_mtime < CACHE_TTL_S:
        return load(symbol)
    err: Exception
    if breaker_open():
        err = Transient("screener.in unreachable (circuit breaker open)")
    else:
        try:
            tables, meta = _from_screener(slug, symbol)
            return tables, save_tables(symbol, tables, meta)
        except LookupError as e:
            err = e
        except (requests.RequestException, Transient) as e:
            err = e
    if not fallback:
        raise err
    missing = isinstance(err, LookupError)
    try:
        tables, meta = _from_yfinance(symbol)
    except LookupError as e:
        if missing:
            raise LookupError(f"{err}; yfinance: {e}") from e
        raise Transient(f"screener.in unreachable ({type(err).__name__}) and yfinance has no annual statements ({e})") from e
    except Exception as e:  # yfinance itself unreachable / throttled
        raise Transient(f"{type(err).__name__} from screener.in, then {type(e).__name__} from yfinance: {str(e)[:120]}") from e
    meta.update(screener_status="no_page" if missing else "unreachable", fallback_reason=f"{type(err).__name__}: {err}"[:200])
    return tables, save_tables(symbol, tables, meta)


# ── yfinance fallback ─────────────────────────────────────────────────────
# Row mapping into the screener rows analyze()/value_company() read (Rs Cr = Yahoo absolute / 1e7; EPS stays in Rs):
#   pl  Sales = Total Revenue | Operating Profit = Operating Income + Reconciled Depreciation (else EBITDA)
#       Depreciation = Reconciled Depreciation | Interest = Interest Expense
#       Profit before tax = Pretax Income | Net Profit = Net Income Common Stockholders | Net Income
#       EPS in Rs = Diluted EPS | Basic EPS, divided by every split after the fiscal year-end (screener restates for
#       splits and bonuses; Yahoo history does not) | Tax % = Tax Provision / Pretax Income
#       Dividend Payout % = |Cash Dividends Paid| / Net Income (else dividends per share from the price file / EPS)
#   bs  Equity Capital = Common Stock | Reserves = Stockholders Equity - Equity Capital | Borrowings = Total Debt
#       Total Assets = Total Assets
#   cf  Cash from Operating Activity = Operating Cash Flow | Free Cash Flow = Free Cash Flow
#   not available: ratios (Working Capital Days, ROCE: nil working capital is assumed), quarterly (no TTM), Deposits.
def _v(df, names, ts):
    if df is None or getattr(df, "empty", True) or ts not in df.columns:
        return None
    for n in names:
        if n in df.index:
            x = df.loc[n, ts]
            x = x.iloc[0] if hasattr(x, "iloc") else x
            if pd.notna(x):
                return float(x)
    return None


def map_yfinance(inc, bs, cf, *, splits: pd.Series | None = None, dps: pd.Series | None = None) -> tuple[dict, list[dict]]:
    """Yahoo annual statements -> (screener-shaped tables, issues). Pure: no network."""
    issues: list[dict] = []
    cr = lambda x: None if x is None else x / 1e7  # noqa: E731
    stamps = sorted(c for c in inc.columns if _v(inc, ("Total Revenue", "Operating Revenue"), c) is not None) if inc is not None else []
    if splits is None:
        issues.append({"reason": "eps_not_split_adjusted", "detail": "no price file with split history: EPS is as reported"})
    pl: dict[str, dict] = {k: {} for k in ("Sales", "Operating Profit", "Depreciation", "Interest", "Profit before tax", "Net Profit",
                                           "EPS in Rs", "Tax %", "Dividend Payout %")}
    bsr: dict[str, dict] = {k: {} for k in ("Equity Capital", "Reserves", "Borrowings", "Total Assets")}
    cfr: dict[str, dict] = {k: {} for k in ("Cash from Operating Activity", "Free Cash Flow")}
    cols = []
    for ts in stamps:
        c = pd.Timestamp(ts).strftime("%b %Y")
        cols.append(c)
        rev = _v(inc, ("Total Revenue", "Operating Revenue"), ts)
        dep = _v(inc, ("Reconciled Depreciation", "Depreciation And Amortization In Income Statement", "Depreciation And Amortization"), ts)
        oi, ebitda = _v(inc, ("Operating Income",), ts), _v(inc, ("EBITDA", "Normalized EBITDA"), ts)
        pbt, ni = _v(inc, ("Pretax Income",), ts), _v(inc, ("Net Income Common Stockholders", "Net Income"), ts)
        eps, tax = _v(inc, ("Diluted EPS", "Basic EPS"), ts), _v(inc, ("Tax Provision",), ts)
        if eps is not None and splits is not None:
            later = splits[(splits.index > pd.Timestamp(ts)) & (splits != 0)]
            eps = eps / float(later.prod()) if len(later) else eps
        pay = None
        cash_div = _v(cf, ("Cash Dividends Paid", "Common Stock Dividend Paid"), ts)
        if cash_div is not None and ni and ni > 0:
            pay = abs(cash_div) / ni * 100
        elif dps is not None and eps and eps > 0:
            w = dps[(dps.index > pd.Timestamp(ts) - pd.Timedelta(days=365)) & (dps.index <= pd.Timestamp(ts))]
            pay = float(w.sum()) / eps * 100 if len(w) else None
        pl["Sales"][c] = cr(rev)
        pl["Operating Profit"][c] = cr(oi + dep) if oi is not None and dep is not None else cr(ebitda)
        pl["Depreciation"][c], pl["Interest"][c] = cr(dep), cr(_v(inc, ("Interest Expense",), ts))
        pl["Profit before tax"][c], pl["Net Profit"][c], pl["EPS in Rs"][c] = cr(pbt), cr(ni), eps
        pl["Tax %"][c] = tax / pbt * 100 if tax is not None and pbt and pbt > 0 else None
        pl["Dividend Payout %"][c] = pay
        eq = cr(_v(bs, ("Common Stock", "Capital Stock"), ts))
        se = cr(_v(bs, ("Stockholders Equity", "Common Stock Equity"), ts))
        bsr["Equity Capital"][c], bsr["Reserves"][c] = eq, (se - eq if se is not None and eq is not None else None)
        bsr["Borrowings"][c], bsr["Total Assets"][c] = cr(_v(bs, ("Total Debt",), ts)), cr(_v(bs, ("Total Assets",), ts))
        cfr["Cash from Operating Activity"][c], cfr["Free Cash Flow"][c] = cr(_v(cf, ("Operating Cash Flow",), ts)), cr(_v(cf, ("Free Cash Flow",), ts))
    issues.append({"reason": "yfinance_fallback", "detail": f"{len(cols)} fiscal years from Yahoo annual statements; no ratios table (working-capital days, ROCE), no quarterly/TTM"})
    tables = {k: {"cols": cols, "rows": rows} for k, rows in (("pl", pl), ("bs", bsr), ("cf", cfr))} if cols else {}
    return tables, issues


def _price_extras(symbol: str) -> tuple[pd.Series | None, pd.Series | None]:
    """(splits, per-share dividends) from the cached price file, if one exists (no network)."""
    try:
        df = pd.read_parquet(fdata._path(symbol), columns=["splits", "dividends"])
    except Exception:
        return None, None
    return df["splits"].fillna(0), df["dividends"][df["dividends"].fillna(0) > 0]


def _from_yfinance(symbol: str) -> tuple[dict, dict]:
    """Annual statements from Yahoo (4-5 fiscal years). LookupError when Yahoo has none; other errors are network errors."""
    import yfinance as yf

    def get():
        t = yf.Ticker(symbol)
        return t.income_stmt, t.balance_sheet, t.cashflow

    inc, bs, cf = fdata._retry(get, symbol)
    splits, dps = _price_extras(symbol)
    tables, issues = map_yfinance(inc, bs, cf, splits=splits, dps=dps)
    if not tables:
        raise LookupError("no annual income statement")
    info = fdata._info(symbol)
    bank = inc is not None and "Net Interest Income" in inc.index
    n_fy = len(tables["pl"]["cols"])
    if not info.get("sector"):
        issues.append({"reason": "sector_unknown", "detail": "Yahoo returned no sector; bank/non-bank decided from the statement rows"})
    meta = {"provider": _YF_FALLBACK, "view": f"yfinance fallback ({n_fy} fiscal years)", "sector": info.get("sector"),
            "industry": info.get("industry"), "is_financial": bool(info.get("sector") == "Financial Services" or bank), "issues": issues}
    return tables, meta


def supplement(symbol: str, tables: dict, meta: dict) -> tuple[dict, dict]:
    """The cached screener.in statements have too few fiscal years: ask yfinance once and switch to it only when it has more.
    The attempt is recorded (meta.fallback_tried) so a resume never repeats it. Network errors propagate (status 'retry')."""
    n_old = len(meta.get("fiscal_years") or [])
    try:
        t2, m2 = _from_yfinance(symbol)
    except LookupError:
        t2 = None
    if t2 and len(t2["pl"]["cols"]) > n_old:
        m2.update(screener_status="too_few_years", fallback_reason=f"screener.in cache had {n_old} fiscal years")
        return t2, save_tables(symbol, t2, m2)
    meta = {**meta, "fallback_tried": True}
    _path(symbol, "meta.json").write_text(json.dumps(meta, default=str))
    return tables, meta


def provider_label(meta: dict) -> str:
    """'screener.in (12 fiscal years)' / 'yfinance fallback (4 fiscal years)' for reports."""
    n = len(meta.get("fiscal_years") or [])
    if meta.get("provider", "screener.in") == _YF_FALLBACK:
        return f"yfinance fallback ({n} fiscal years)" if n else "yfinance fallback"
    return f"screener.in ({n} fiscal years)" if n else "screener.in"


# ── data quality ───────────────────────────────────────────────────────────
def _months(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def quality(tables: dict, meta: dict) -> tuple[dict, list[dict], dict]:
    """(clean tables, issues, exclusions).

    clean: pl/bs/cf/ratios keep fiscal-year columns only (TTM and trailing part-year columns such as 'Sep 2026' dropped).
    issues: [{reason, detail}] for the report.
    exclusions: {"company": [reasons], "spans": [{reason, start, end}] (date objects: windows touching them are
    excluded), "flags": {col: [reasons]} (scored, but reported separately)}.
    """
    issues: list[dict] = []
    excl: dict = {"company": [], "spans": [], "flags": {}, "n_years": 0}
    pl = tables.get("pl", {"cols": [], "rows": {}})
    dated = [(c, d) for c in pl["cols"] if (d := _parse(c))]
    if dated:
        mode = Counter(d.month for _, d in dated).most_common(1)[0][0]
        last = max(i for i, (_, d) in enumerate(dated) if d.month == mode)
        fy = dated[:last + 1]
    else:
        fy = []
    keep = [c for c, _ in fy]
    dropped = [c for c in pl["cols"] if c not in keep]
    if dropped:
        issues.append({"reason": "non_fy_column", "detail": f"dropped {', '.join(dropped)}"})
    clean = {t: {"cols": [c for c in tb["cols"] if c in keep], "rows": {r: {c: v.get(c) for c in tb["cols"] if c in keep} for r, v in tb["rows"].items()}}
             for t, tb in tables.items() if t in FY_TABLES}
    if "quarterly" in tables:
        q = tables["quarterly"]
        clean["quarterly"] = {"cols": [c for c in q["cols"] if _parse(c)], "rows": q["rows"]}
    for (c0, d0), (c1, d1) in zip(fy, fy[1:]):
        gap = _months(d0, d1)
        if gap != 12:
            reason = "gap" if gap % 12 == 0 else "fy_change"
            excl["spans"].append({"reason": reason, "start": d0, "end": d1})
            issues.append({"reason": reason, "detail": f"{c0} -> {c1} is {gap} months"})
    rev = row(clean.get("pl", {}), "Sales", "Revenue")
    ta, np_, eps = row(clean.get("bs", {}), "Total Assets"), row(clean.get("pl", {}), "Net Profit"), row(clean.get("pl", {}), "EPS in Rs")
    splits = {str(y) for y in meta.get("split_years", [])}

    def jump(s, c0, c1, lim):
        a, b = s.get(c0), s.get(c1)
        return bool(a and b and a > 0 and b / a - 1 > lim)

    def shares(c):
        return np_[c] / eps[c] if np_.get(c) and eps.get(c) and np_[c] > 0 and eps[c] > 0 else None

    for (c0, d0), (c1, d1) in zip(fy, fy[1:]):
        if _months(d0, d1) != 12:
            continue
        s0, s1 = shares(c0), shares(c1)
        for reason, hit in (("structural_break", jump(rev, c0, c1, BREAK_REVENUE) or jump(ta, c0, c1, BREAK_ASSETS)),
                            ("share_basis", bool(s0 and s1 and abs(s1 / s0 - 1) > SHARE_JUMP and str(d1.year) not in splits))):
            if hit:
                excl["flags"].setdefault(c1, []).append(reason)
                issues.append({"reason": reason, "detail": c1})
    yrs = [c for c in keep if rev.get(c) is not None]
    excl["n_years"] = len(yrs)
    if len(yrs) < MIN_TOTAL_YEARS:
        excl["company"].append("too_few_years")
        used = f" ({yrs[0]}..{yrs[-1]})" if yrs else ""
        issues.append({"reason": "too_few_years", "detail": f"{len(yrs)} fiscal years available{used}; {MIN_TOTAL_YEARS} needed ({SHORT_MIN_YEARS} to project from + 1 to score)"})
    return clean, issues, excl


# ── prices ─────────────────────────────────────────────────────────────────
_BSE_IDS: dict[str, str] | None = None


def bse_security_id(code: str) -> str | None:
    """BSE scrip code -> the alphabetic security id Yahoo actually serves ("500016" -> "ARUNAHTEL"; Yahoo has no data
    under the numeric code). Read from the cached universe file; None when unknown."""
    global _BSE_IDS
    if _BSE_IDS is None:
        try:
            u = pd.read_parquet(Path(__file__).resolve().parents[3] / "data" / "forecast_universe" / "universe.parquet")
            b = u[u["exchange"] == "BSE"]
            _BSE_IDS = {y.split(".")[0]: str(s) for y, s in zip(b["yahoo_symbol"], b["symbol"]) if str(s) and not str(s).isdigit()}
        except Exception:
            _BSE_IDS = {}
    return _BSE_IDS.get(str(code))


def alt_symbols(symbol: str, meta: dict | None = None) -> list[str]:
    """Other Yahoo tickers worth trying when ``symbol`` returns nothing: the BSE security id for a numeric BSE code, the
    NSE ticker screener lists, the other suffix."""
    base, _, suf = symbol.rpartition(".")
    alts = []
    if suf.upper() == "BO" and base.isdigit() and bse_security_id(base):
        alts.append(f"{bse_security_id(base)}.BO")
    if (meta or {}).get("nse_symbol"):
        alts.append(f"{(meta or {}).get('nse_symbol')}.NS")
    alts.append(f"{base}.{'NS' if suf.upper() == 'BO' else 'BO'}")
    return [a for a in dict.fromkeys(alts) if a != symbol and not a.startswith("None")]


def _prices_one(symbol: str) -> pd.DataFrame:
    """Cache first (a price file under 30 days old is used as is: this is history, not a quote), else download; a stale
    file is used when the download fails, and a too-short history is read straight from its cache file."""
    p = fdata._path(symbol)
    if p.exists() and time.time() - p.stat().st_mtime < PRICE_TTL_S:
        return pd.read_parquet(p)
    try:
        return fdata.load_history(symbol)[0]
    except fdata.DataUnavailable as e:
        if p.exists() and e.reason in ("insufficient_history", "download_error", "stale"):
            return pd.read_parquet(p)
        raise


def prices(symbol: str, meta: dict | None = None) -> pd.DataFrame:
    """Daily [close, adj_close]. Tries ``symbol``, then alternate tickers; df.attrs['price_symbol'] says which one answered.
    On total failure raises DataUnavailable whose message lists every ticker tried and why."""
    tried, last = [], None
    for s in [symbol, *alt_symbols(symbol, meta)]:
        try:
            df = _prices_one(s)[["close", "adj_close"]].dropna()
        except fdata.DataUnavailable as e:
            tried.append(f"{s}: {e.reason}")
            last = last if last and last.reason == "download_error" else e  # a network error outranks 'no data'
            continue
        if df.empty:
            tried.append(f"{s}: empty")
            continue
        df.attrs["price_symbol"] = s
        return df
    raise fdata.DataUnavailable("no_price (" + "; ".join(tried) + ")", last.reason if last else "no_data")


def nifty() -> pd.Series:
    """^NSEI adjusted close, cache-first like prices()."""
    p = fdata._path("^NSEI")
    if p.exists() and time.time() - p.stat().st_mtime < PRICE_TTL_S:
        return pd.read_parquet(p)["adj_close"]
    try:
        return fdata.load_series("^NSEI")
    except Exception:
        if p.exists():
            return pd.read_parquet(p)["adj_close"]
        raise
