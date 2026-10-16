"""Owner: WP1. Price history, benchmark/sector series, data-quality report.

Price basis (never mixed): RETURNS and targets come from `adj_close` (split+dividend adjusted);
`close` (raw, as traded) is for DISPLAY only. `open/high/low` are split-adjusted by Yahoo but
not dividend-adjusted (auto_adjust=False), so they are not comparable with adj_close levels.
"""
from __future__ import annotations

import contextlib
import json
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from config.paths import DATA_DIR

from .contracts import MIN_BARS, DataQuality, DatasetMeta

CACHE_DIR = DATA_DIR / "forecast_cache"
CACHE_TTL_S = 12 * 3600
COLS = ["open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]
_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
           "Volume": "volume", "Dividends": "dividends", "Stock Splits": "splits"}

LIMITATIONS = [
    "Survivorship bias: delisted, merged or renamed companies are absent from the data source.",
    "Yahoo Finance data is revised/adjusted after the fact; it is not a point-in-time record.",
    "No point-in-time fundamentals: fundamentals are not used as model inputs.",
    "Adjusted prices follow Yahoo's adjustment methodology (splits and dividends); it may differ from other vendors.",
]
_NSE_SECTOR = {"it": "^CNXIT", "banks": "^NSEBANK", "pharma": "^CNXPHARMA", "auto": "^CNXAUTO",
               "fmcg": "^CNXFMCG", "metals": "^CNXMETAL", "energy": "^CNXENERGY", "realty": "^CNXREALTY"}
_US_SECTOR = {"technology": "XLK", "financial services": "XLF", "healthcare": "XLV",
              "consumer cyclical": "XLY", "consumer defensive": "XLP", "energy": "XLE", "industrials": "XLI",
              "basic materials": "XLB", "utilities": "XLU", "real estate": "XLRE", "communication services": "XLC"}


class DataUnavailable(Exception):
    """History missing or unusable; the job maps this to status data_unavailable.

    `reason` is one of REASONS so a universe sweep can count gaps honestly."""

    def __init__(self, msg: str = "", reason: str = "bad_data"):
        super().__init__(msg)
        self.reason = reason


REASONS = ("no_data", "insufficient_history", "stale", "all_zero_volume", "bad_data", "download_error")
MAX_STALE_DAYS: int | None = None  # the universe sweep sets 30: a last bar older than this = suspended/delisted
MAX_YAHOO_CONCURRENT = 4
_JITTER = (0.2, 0.6)
_RETRIES = 4
_SERIES_MEM: dict[str, tuple[float, pd.Series]] = {}  # benchmark/sector series, once per process
_mem_lock = threading.Lock()


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def polite():
    """At most MAX_YAHOO_CONCURRENT Yahoo requests across ALL processes (file locks die with their process),
    each followed by 0.2-0.6 s of jitter before the slot is released."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fds = [os.open(str(CACHE_DIR / f".yahoo_slot{i}"), os.O_RDWR | os.O_CREAT) for i in range(MAX_YAHOO_CONCURRENT)]
    held = None
    try:
        while held is None:
            for fd in fds:
                if _try_lock(fd):
                    held = fd
                    break
            else:
                time.sleep(0.05 + random.random() * 0.1)
        yield
        time.sleep(random.uniform(*_JITTER))
    finally:
        for fd in fds:  # closing releases the lock
            os.close(fd)


def _transient(e: Exception) -> bool:
    t = f"{type(e).__name__} {e}".lower()
    return any(k in t for k in ("429", "too many", "rate", "timeout", "timed out", "connection", "temporar", "502", "503", "504"))


def _retry(fn, what: str):
    """Run fn under the Yahoo slot; retry transient errors with exponential backoff (2, 4, 8 s + jitter)."""
    for attempt in range(_RETRIES):
        try:
            with polite():
                return fn()
        except DataUnavailable:
            raise
        except Exception as e:
            if attempt == _RETRIES - 1 or not _transient(e):
                raise
            time.sleep(2 ** (attempt + 1) + random.random())


def _market(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith((".NS", ".BO")):
        return "IN"
    return "OTHER" if s.startswith("^") or "." in s else "US"


def _path(key: str, ext: str = "parquet") -> Path:
    return CACHE_DIR / f"{re.sub(r'[^A-Za-z0-9_.^-]', '_', key)}.{ext}"


def _fresh(p: Path, force: bool) -> bool:
    return not force and p.exists() and time.time() - p.stat().st_mtime < CACHE_TTL_S


def _fetch(symbol: str) -> pd.DataFrame:
    """One yfinance call; raw frame with tz-naive index and renamed columns (may have duplicates)."""
    def get():
        return yf.Ticker(symbol).history(period="max", auto_adjust=False, actions=True)

    raw = _retry(get, symbol)
    if raw is None or raw.empty:  # yfinance sometimes returns empty on a throttle: look once more
        time.sleep(1.5 + random.random())
        raw = _retry(get, symbol)
    if raw is None or raw.empty:
        raise DataUnavailable(f"no price history returned for {symbol}", "no_data")
    df = raw.rename(columns=_RENAME)
    for c in ("dividends", "splits"):
        if c not in df:
            df[c] = 0.0
    if "adj_close" not in df:  # indices
        df["adj_close"] = df["close"]
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return df[COLS]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    d = df[~df.index.duplicated(keep="last")].sort_index()
    # Missing provider bars are not observations. Never forward-fill a price
    # or feed NaN/inf to models; retain finite outliers for quality reporting.
    prices = [column for column in ("open", "high", "low", "close", "adj_close") if column in d]
    return d.loc[np.isfinite(d[prices]).all(axis=1)]


def load_series(index_symbol: str, force: bool = False) -> pd.Series:
    """Adjusted close of any symbol (benchmark/sector), parquet-cached for 12 h."""
    mkey = f"{CACHE_DIR}|{index_symbol}"  # tests repoint CACHE_DIR
    hit = _SERIES_MEM.get(mkey)
    if hit and not force and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    p = _path(index_symbol)
    if _fresh(p, force):
        s = pd.read_parquet(p)["adj_close"]
    else:
        s = _clean(_fetch(index_symbol))["adj_close"].dropna()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        s.to_frame("adj_close").to_parquet(p)
    s = s[np.isfinite(s) & (s > 0)]
    if s.empty:
        raise DataUnavailable(f"{index_symbol}: no usable adjusted prices", "bad_data")
    _SERIES_MEM[mkey] = (time.time(), s)
    return s


def load_benchmark(symbol: str) -> pd.Series:
    """Benchmark adjusted-close series (tz-naive DatetimeIndex): ^NSEI for .NS/.BO, else ^GSPC."""
    return load_series("^NSEI" if _market(symbol) == "IN" else "^GSPC")


def _info(symbol: str) -> dict:
    try:
        return dict(_retry(lambda: yf.Ticker(symbol).info, symbol) or {})
    except Exception:
        return {}


def sector_symbol(symbol: str) -> str | None:
    """Sector index (NSE) or SPDR ETF (US) for the stock, or None when unknown."""
    mk = _market(symbol)
    if mk == "IN":
        from modules.equity_research.intelligence.data import PEER_GROUPS, _peer_group

        base = symbol.upper().rsplit(".", 1)[0]
        group = next((g for g, names in PEER_GROUPS.items() if base in names), None)
        if group is None:
            info = _info(symbol)
            group = _peer_group(info.get("sector"), info.get("industry"))
        return _NSE_SECTOR.get(group)
    if mk == "US":
        return _US_SECTOR.get(str(_info(symbol).get("sector") or "").lower())
    return None


def quality_report(df: pd.DataFrame) -> DataQuality:
    """Data checks on a raw (possibly unsorted/duplicated) frame. Outliers are flagged, never removed."""
    w: list[str] = []
    dups = int(df.index.duplicated().sum())
    d = _clean(df)
    invalid = len(df[~df.index.duplicated(keep="last")]) - len(d)
    gaps = int((d.index.to_series().diff().dt.days > 5).sum())
    zero_vol = int((d["volume"].fillna(0) <= 0).sum())
    r = np.log(d["adj_close"]).diff()
    mad = r.abs().rolling(63, min_periods=20).median()  # MAD about zero, trailing window
    outliers = int(((r.abs() > 8 * mad) & (mad > 0)).sum())
    splits, divs = d["splits"].fillna(0) != 0, d["dividends"].fillna(0) != 0
    ratio = (d["close"] / d["adj_close"]).pct_change().abs()
    events = (splits | divs) & ratio.notna()
    bad = int((events & (ratio < 1e-5)).sum())
    ok = bad == 0
    for cond, msg in [
        (dups, f"{dups} duplicate timestamps removed (kept last)."),
        (invalid, f"{invalid} bars with missing/nonfinite prices excluded; no prices imputed."),
        (gaps, f"{gaps} gaps longer than 5 calendar days."),
        (zero_vol, f"{zero_vol} zero-volume days."),
        (outliers, f"{outliers} returns beyond 8x rolling MAD flagged (kept, not removed)."),
        (not ok, f"{bad} split/dividend dates where close/adj_close did not change: adjustment may be inconsistent."),
    ]:
        if cond:
            w.append(msg)
    return DataQuality(gaps=gaps, duplicates=dups, zero_volume_days=zero_vol, outliers=outliers,
                       split_events=int(splits.sum()), dividend_events=int(divs.sum()),
                       split_consistency_ok=ok, warnings=w)


def _ticker_meta(symbol: str, market: str) -> dict:
    out = {"currency": "INR" if market == "IN" else ("USD" if market == "US" else None),
           "exchange": None, "timezone": None}
    try:
        with polite():
            fi = yf.Ticker(symbol).fast_info
        for k, a in (("currency", "currency"), ("exchange", "exchange"), ("timezone", "timezone")):
            try:
                v = fi[a]
            except Exception:
                v = None
            if v:
                out[k] = str(v)
    except Exception:
        pass
    return out


def _check(symbol: str, df: pd.DataFrame) -> None:
    """Raise DataUnavailable(reason) for series that cannot be validated."""
    px = df["adj_close"]
    if px.notna().sum() == 0 or (px.dropna() <= 0).any():
        raise DataUnavailable(f"{symbol}: adj_close missing or non-positive", "bad_data")
    if (df["volume"].fillna(0) <= 0).all():
        raise DataUnavailable(f"{symbol}: every bar has zero volume", "all_zero_volume")
    age = (pd.Timestamp.now().normalize() - df.index[-1]).days
    if MAX_STALE_DAYS is not None and age > MAX_STALE_DAYS:
        raise DataUnavailable(f"{symbol}: last bar {df.index[-1].date()} is {age} days old", "stale")
    if len(df) < MIN_BARS:
        raise DataUnavailable(f"{symbol}: {len(df)} bars < {MIN_BARS} required", "insufficient_history")


def load_history(symbol: str, *, force: bool = False) -> tuple[pd.DataFrame, DatasetMeta]:
    """Daily bars. Columns: open,high,low,close,adj_close,volume,dividends,splits; tz-naive ascending DatetimeIndex."""
    market = _market(symbol)
    p, mp = _path(symbol), _path(symbol, "json")
    if _fresh(p, force) and mp.exists():
        df = pd.read_parquet(p)
        side = json.loads(mp.read_text())
        cleaned = _clean(df)
        invalid = len(df) - len(cleaned)
        if invalid:
            side["quality"]["warnings"].append(f"{invalid} cached bars with missing/nonfinite prices excluded; no prices imputed.")
        df = cleaned
    else:
        try:
            raw = _fetch(symbol)
        except DataUnavailable:
            raise
        except Exception as e:
            raise DataUnavailable(f"download failed for {symbol}: {type(e).__name__}: {str(e)[:120]}",
                                  "download_error") from e
        side = {"quality": quality_report(raw).model_dump(), "retrieved_at_utc":
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **_ticker_meta(symbol, market)}
        df = _clean(raw)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p)
        mp.write_text(json.dumps(side))
    _check(symbol, df)
    q = DataQuality(**side["quality"])
    warnings = list(q.warnings)
    bench_sym = "^NSEI" if market == "IN" else "^GSPC"
    b_first = None
    try:
        b_first = str(load_series(bench_sym, force).index[0].date())
    except Exception as e:
        warnings.append(f"benchmark {bench_sym} unavailable: {e}")
        bench_sym = None
    sec = None
    try:
        sec = sector_symbol(symbol)
        if sec:
            load_series(sec, force)
    except Exception as e:
        warnings.append(f"sector series {sec} unavailable: {e}")
        sec = None
    q = q.model_copy(update={"warnings": warnings})
    return df, DatasetMeta(
        symbol=symbol, market=market, provider="yfinance", retrieved_at_utc=side["retrieved_at_utc"],
        first_bar=str(df.index[0].date()), last_bar=str(df.index[-1].date()), n_bars=len(df),
        currency=side.get("currency"), exchange=side.get("exchange"), timezone=side.get("timezone"),
        benchmark_symbol=bench_sym, benchmark_first_bar=b_first, sector_symbol=sec,
        quality=q, limitations=list(LIMITATIONS))
