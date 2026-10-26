"""Data-layer tests. Frames are SYNTHETIC (yfinance monkeypatched) except the one network test."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.forecast import data as D
from modules.equity_research.forecast.contracts import MIN_BARS


def synth_raw(n=1400, seed=0, split_at=300, div_at=600, tz="Asia/Kolkata"):
    """SYNTHETIC yfinance-shaped frame: adj_close = close * factor, factor steps at event dates."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n, tz=tz)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    factor = np.ones(n)
    factor[:split_at] *= 0.5  # earlier bars adjusted down before the 2:1 split
    factor[:div_at] *= 0.99
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Adj Close": close * factor,
                       "Volume": rng.integers(1000, 5000, n).astype(float), "Dividends": 0.0, "Stock Splits": 0.0},
                      index=idx)
    df.iloc[split_at, df.columns.get_loc("Stock Splits")] = 2.0
    df.iloc[div_at, df.columns.get_loc("Dividends")] = 1.0
    return df


class FakeTicker:
    frames: dict = {}
    calls: list = []
    sector = "Technology"

    def __init__(self, sym):
        self.sym = sym

    def history(self, **kw):
        FakeTicker.calls.append(self.sym)
        if self.sym not in FakeTicker.frames:
            raise RuntimeError("download failed")
        return FakeTicker.frames[self.sym].copy()

    @property
    def info(self):
        return {"sector": FakeTicker.sector}

    @property
    def fast_info(self):
        return {"currency": "INR", "exchange": "NSI", "timezone": "Asia/Kolkata"}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    FakeTicker.frames, FakeTicker.calls = {}, []
    monkeypatch.setattr(D.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(D, "CACHE_DIR", tmp_path / "cache")
    return FakeTicker


def test_load_history_shape_meta_and_cache(fake):
    raw = synth_raw()
    raw = pd.concat([raw, raw.iloc[[5]]]).sort_index()  # one duplicated timestamp
    fake.frames = {"TCS.NS": raw, "^NSEI": synth_raw(seed=1), "^CNXIT": synth_raw(seed=2)}
    df, meta = D.load_history("TCS.NS")
    assert list(df.columns) == D.COLS and df.index.tz is None
    assert df.index.is_monotonic_increasing and df.index.is_unique and len(df) == 1400
    assert meta.market == "IN" and meta.currency == "INR" and meta.benchmark_symbol == "^NSEI"
    assert meta.sector_symbol == "^CNXIT" and meta.n_bars == 1400
    assert meta.quality.duplicates == 1 and meta.quality.split_events == 1 and meta.quality.dividend_events == 1
    assert meta.quality.split_consistency_ok
    assert "adjusted" in meta.price_basis and len(meta.limitations) == 4
    n = len(fake.calls)
    D.load_history("TCS.NS")  # cache hit: no further downloads
    assert len(fake.calls) == n
    D.load_history("TCS.NS", force=True)
    assert len(fake.calls) > n


def test_benchmark_and_sector_failures_are_tolerated(fake):
    fake.frames = {"INFY.NS": synth_raw()}  # no ^NSEI, no ^CNXIT
    _, meta = D.load_history("INFY.NS")
    assert meta.benchmark_symbol is None and meta.sector_symbol is None
    assert any("benchmark" in w for w in meta.quality.warnings) and any("sector" in w for w in meta.quality.warnings)


def test_missing_and_nonfinite_price_bars_are_excluded_with_warning(fake):
    raw = synth_raw()
    raw.iloc[-1, raw.columns.get_loc("Close")] = np.nan
    raw.iloc[-2, raw.columns.get_loc("Adj Close")] = np.inf
    fake.frames = {"TCS.NS": raw}
    df, meta = D.load_history("TCS.NS")
    assert len(df) == len(raw) - 2
    assert np.isfinite(df[D.COLS[:5]]).all().all()
    assert meta.last_bar == str(raw.index[-3].date())
    assert any("2 bars with missing/nonfinite" in w for w in meta.quality.warnings)
    # Also sanitize an older cache, without changing its provider timestamp.
    cached = pd.read_parquet(D._path("TCS.NS"))
    cached.iloc[-1, cached.columns.get_loc("close")] = np.nan
    cached.to_parquet(D._path("TCS.NS"))
    replay, cached_meta = D.load_history("TCS.NS")
    assert len(replay) == len(df) - 1
    assert cached_meta.retrieved_at_utc == meta.retrieved_at_utc
    assert any("cached bars with missing/nonfinite" in w for w in cached_meta.quality.warnings)


def test_insufficient_history_raises(fake):
    fake.frames = {"NEW.NS": synth_raw(n=MIN_BARS - 1, split_at=100, div_at=200)}
    with pytest.raises(D.DataUnavailable):
        D.load_history("NEW.NS")
    with pytest.raises(D.DataUnavailable):
        D.load_history("MISSING.NS")  # download error -> DataUnavailable


def test_benchmark_choice_and_sector_mapping(fake):
    fake.frames = {"^NSEI": synth_raw(seed=1), "^GSPC": synth_raw(seed=2)}
    assert D.load_benchmark("TCS.NS").index.tz is None
    assert fake.calls == ["^NSEI"]
    D.load_benchmark("AAPL")
    assert fake.calls[-1] == "^GSPC"
    assert D.sector_symbol("TCS.NS") == "^CNXIT" and D.sector_symbol("HDFCBANK.NS") == "^NSEBANK"
    assert D.sector_symbol("AAPL") == "XLK"
    fake.sector = "Nonsense"
    assert D.sector_symbol("ZZZ") is None
    fake.sector = "Technology"


def test_quality_report_flags():
    raw = synth_raw()
    d = raw.rename(columns=D._RENAME)
    d.index = d.index.tz_localize(None)
    d = d[D.COLS]
    d = d.drop(d.index[100:110])  # ~14 calendar-day gap
    d.iloc[50, d.columns.get_loc("volume")] = 0.0
    d.iloc[700, d.columns.get_loc("adj_close")] *= 1.8  # fat-finger spike, flagged not removed
    q = D.quality_report(d)
    assert q.gaps == 1 and q.zero_volume_days == 1 and q.outliers >= 1 and q.duplicates == 0
    assert len(d) == 1390  # nothing removed
    # an event with no adjustment change is reported as inconsistent
    bad = d.copy()
    bad["adj_close"] = bad["close"]
    q2 = D.quality_report(bad)
    assert not q2.split_consistency_ok and any("inconsistent" in w for w in q2.warnings)


@pytest.mark.network
def test_real_tcs_history(tmp_path, monkeypatch):
    import socket
    try:
        socket.create_connection(("query1.finance.yahoo.com", 443), timeout=3).close()
    except OSError:
        pytest.skip("Yahoo unreachable")
    monkeypatch.setattr(D, "CACHE_DIR", tmp_path)
    df, meta = D.load_history("TCS.NS")
    assert len(df) >= MIN_BARS and df.index.tz is None and meta.market == "IN"
    assert (df.adj_close <= df.close * 1.0001).all()


def test_a_corrupt_cache_file_is_refetched_not_fatal(tmp_path, monkeypatch):
    """An interrupted write left a truncated parquet that crashed every later run for that symbol."""
    monkeypatch.setattr(D, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(D, "_SERIES_MEM", {})
    good = pd.DataFrame({"adj_close": [1.0, 2.0, 3.0]}, index=pd.date_range("2026-01-01", periods=3))
    (tmp_path / "^X.parquet").write_bytes(b"PAR1 truncated")
    monkeypatch.setattr(D, "_fetch", lambda s: good)
    assert list(D.load_series("^X")) == [1.0, 2.0, 3.0]
    assert list(pd.read_parquet(tmp_path / "^X.parquet")["adj_close"]) == [1.0, 2.0, 3.0]
