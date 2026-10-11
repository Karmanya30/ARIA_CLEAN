from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import markets
from modules.market import live

client = TestClient(app)
META = {"as_of": "2026-10-09T10:00:00+00:00", "fetched_at": "2026-10-09T10:01:00+00:00", "stale": False,
        "source": "Yahoo Finance", "delay_min": 15}


@pytest.fixture(autouse=True)
def snaps(monkeypatch):
    monkeypatch.setattr(live, "_started", True)
    markets._store.clear()
    live._snap.clear()
    live._snap.update({
        "overview": {"items": [{"symbol": "^NSEI", "name": "Nifty 50", "group": "india", "price": 1.0, "change": 0.0, "change_pct": 0.0,
                                "prev_close": 1.0, "currency": "INR", "spark": [1.0]}],
                     "last_bar": datetime.now(timezone.utc), "meta": META},
        "movers": {"gainers": [], "losers": [], "active": [], "meta": META},
        "sectors": {"sectors": [], "meta": META},
        "news": {"items": [], "engine": "keywords", "meta": {**META, "source": "RSS, 3 feeds"}},
    })
    yield
    live._snap.clear()
    markets._store.clear()


@pytest.mark.parametrize("name", ["overview", "movers", "sectors", "news"])
def test_snapshot_endpoints_match_schema(name):
    r = client.get(f"/api/markets/{name}")
    assert r.status_code == 200
    body = r.json()
    assert markets.SCHEMA[name] <= body.keys() and markets.META_KEYS <= body["meta"].keys()
    assert "last_bar" not in body


def test_overview_status():
    st = client.get("/api/markets/overview").json()["status"]
    assert {"open", "label", "now_ist", "note"} <= st.keys()


class _Ticker:
    fast_info = {"currency": "INR", "lastPrice": 110.0, "previousClose": 100.0, "dayLow": 99.0, "dayHigh": 111.0,
                 "yearLow": 50.0, "yearHigh": 120.0, "marketCap": 1e12, "lastVolume": 5}

    def __init__(self, sym):
        self.sym = sym

    def history(self, **kw):
        idx = pd.date_range("2026-10-09 04:00", periods=3, freq="5min", tz="UTC")
        return pd.DataFrame({"Open": [1.0] * 3, "High": [2.0] * 3, "Low": [0.5] * 3, "Close": [1.5] * 3, "Volume": [10] * 3}, index=idx)


def test_chart_and_fallback(monkeypatch):
    monkeypatch.setattr(markets.yf, "Ticker", _Ticker)
    body = client.get("/api/markets/chart?symbol=^NSEI&range=1D").json()
    assert markets.SCHEMA["chart"] <= body.keys() and body["interval"] == "5m" and len(body["bars"]) == 3
    assert body["bars"][0].keys() == {"t", "o", "h", "l", "c", "v"}
    markets._store[("chart", "^NSEI", "1D")] = (0.0, markets._store[("chart", "^NSEI", "1D")][1])  # expire it
    monkeypatch.setattr(markets.yf, "Ticker", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.get("/api/markets/chart?symbol=^NSEI&range=1D").json()["meta"]["stale"] is True
    r = client.get("/api/markets/chart?symbol=TCS.NS&range=1Y")  # nothing cached for this one
    assert r.status_code == 503 and r.json()["detail"]["meta"]["error"]


def test_quote(monkeypatch):
    monkeypatch.setattr(markets.yf, "Ticker", _Ticker)
    monkeypatch.setattr(markets, "_yf_info", lambda s: {"shortName": "Reliance", "trailingPE": 25.0, "sector": "Energy"})
    body = client.get("/api/markets/quote?symbol=RELIANCE.NS").json()
    assert markets.SCHEMA["quote"] <= body.keys() and body["change_pct"] == 10.0 and body["pe"] == 25.0


@pytest.mark.parametrize("url", [
    "/api/markets/chart?symbol=bad symbol!", "/api/markets/chart?symbol=" + "A" * 21, "/api/markets/quote?symbol=%3Cx%3E",
    "/api/markets/chart?symbol=TCS.NS&range=9Y",
])
def test_bad_input_422(url):
    assert client.get(url).status_code == 422


def test_search():
    res = client.get("/api/markets/search?q=infosys").json()
    assert res[0]["symbol"] == "INFY.NS" and len(res) <= 8
    assert any(r["symbol"] == "ZOMATO.NS" for r in client.get("/api/markets/search?q=zomato").json())
