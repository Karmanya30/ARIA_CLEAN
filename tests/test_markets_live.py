from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from modules.market import live


def _frame(closes: dict[str, list[float]], idx, volume: float = 1_000_000) -> pd.DataFrame:
    """Shaped like yf.download for several tickers: MultiIndex columns (field, ticker)."""
    cols = {}
    for field in ("Close", "Volume"):
        for sym, vals in closes.items():
            cols[(field, sym)] = vals if field == "Close" else [volume] * len(vals)
    df = pd.DataFrame(cols, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Price", "Ticker"])
    return df


def _intraday() -> pd.DataFrame:
    prev = pd.date_range("2026-10-08 03:45", periods=25, freq="15min", tz="UTC")
    today = pd.date_range("2026-10-09 03:45", periods=60, freq="15min", tz="UTC")  # 60 bars -> must be cut to 40
    idx = prev.append(today)
    vals = [100.0] * 25 + list(np.linspace(100, 110, 60))
    return _frame({s: vals for s in live._ALL_INDEX}, idx)


def _daily() -> pd.DataFrame:
    idx = pd.date_range("2026-10-08", periods=2, freq="D", tz="UTC")
    syms = list(live.NIFTY50)
    closes = {s: [100.0, 100.0 + i - 25] for i, s in enumerate(syms)}  # change % runs from -25 to +24
    df = _frame(closes, idx)
    for i, s in enumerate(syms):
        df[("Volume", s)] = [1.0, 1e6 * (50 - i)]  # RELIANCE-first = most active
    return df


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    live._snap.clear()
    monkeypatch.setattr(live, "_started", True)  # never spawn the refresher in tests
    yield
    live._snap.clear()


def _patch_downloads(monkeypatch, fail=False):
    def fake(symbols, interval):
        if fail:
            raise RuntimeError("yahoo down")
        return _intraday() if interval == "15m" else _daily()

    monkeypatch.setattr(live, "_download", fake)
    monkeypatch.setattr(live, "_build_news", lambda: (_ for _ in ()).throw(RuntimeError("no news")))


def test_overview_change_and_sparkline(monkeypatch):
    _patch_downloads(monkeypatch)
    with pytest.raises(RuntimeError):  # news failed, the rest still landed
        live.refresh_once()
    nifty = next(i for i in live.snapshot("overview")["items"] if i["symbol"] == "^NSEI")
    assert nifty["prev_close"] == 100.0 and nifty["price"] == 110.0
    assert nifty["change"] == 10.0 and nifty["change_pct"] == 10.0
    assert len(nifty["spark"]) <= 40


def test_movers_and_sector_grouping(monkeypatch):
    _patch_downloads(monkeypatch)
    with pytest.raises(RuntimeError):
        live.refresh_once()
    m = live.snapshot("movers")
    gains = [r["change_pct"] for r in m["gainers"]]
    assert len(gains) == 8 and gains == sorted(gains, reverse=True)
    assert [r["change_pct"] for r in m["losers"]] == sorted(r["change_pct"] for r in m["losers"])
    vals = [r["value_cr"] for r in m["active"]]
    assert vals == sorted(vals, reverse=True) and m["active"][0]["symbol"] == "RELIANCE.NS"
    it = next(s for s in live.snapshot("sectors")["sectors"] if s["name"] == "IT")
    assert it["index_symbol"] == "^CNXIT" and it["change_pct"] == 10.0
    assert {s["symbol"] for s in it["stocks"]} == {"TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"}


def test_failure_keeps_last_good_copy_and_flags_stale(monkeypatch):
    _patch_downloads(monkeypatch)
    with pytest.raises(RuntimeError):
        live.refresh_once()
    good = live.snapshot("movers")["gainers"]
    _patch_downloads(monkeypatch, fail=True)
    with pytest.raises(RuntimeError):
        live.refresh_once()
    s = live.snapshot("movers")
    assert s["gainers"] == good and s["meta"]["stale"] is True and "yahoo down" in s["meta"]["error"]


def test_warming_state_starts_refresher(monkeypatch):
    called = []
    monkeypatch.setattr(live, "start", lambda: called.append(1))
    s = live.snapshot("overview")
    assert s["warming"] is True and s["items"] == [] and called


@pytest.mark.parametrize("when,open_", [
    ("2026-10-09 09:14", False), ("2026-10-09 09:15", True), ("2026-10-09 15:29", True),
    ("2026-10-09 15:30", False), ("2026-10-10 11:00", False),  # Saturday
])
def test_market_status(when, open_):
    now = datetime.fromisoformat(when).replace(tzinfo=live.IST)
    assert live.market_status(now)["open"] is open_


def test_market_status_holiday_label():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=live.IST)
    st = live.market_status(now, last_bar=datetime(2026, 10, 8, 15, 29, tzinfo=live.IST))
    assert st["open"] and st["label"] == "No recent trades (holiday?)" and "holidays" in st["note"]
    assert live.market_status(now, last_bar=now)["label"] == "Market open"


def test_news_tagging(monkeypatch):
    raw = [{"title": "Reliance profit jumps", "source": "ET", "url": "u1", "age_hours": 1.0, "sources": 3},
           {"title": "Weather is nice", "source": "Mint", "url": "u2", "age_hours": 2.0, "sources": 1}]
    monkeypatch.setattr(live, "fetch_news", lambda q, limit: raw)
    monkeypatch.setattr(live, "resolve_company", lambda t: "RELIANCE" if "Reliance" in t else None)
    n = live._build_news()
    assert n["items"][0]["symbols"] == ["RELIANCE.NS"] and n["items"][1]["symbols"] == []
    assert n["items"][0]["sources"] == 3 and n["engine"] in ("finbert", "keywords") and "2 feeds" in n["meta"]["source"]
