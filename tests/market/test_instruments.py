"""Instrument catalogue, quote/chart/profile/SIP and the /api/instruments routes. Offline: AMFI, mfapi, Yahoo, CoinGecko and
FRED are replaced by canned data. The two @pytest.mark.network tests at the bottom hit AMFI and mfapi for real."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules.market import amfi, instrument_chat
from modules.market import instruments as I

client = TestClient(app)

NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

Parag Parikh Mutual Fund

122639;INF879O01027;-;Parag Parikh Flexi Cap Fund;Direct Plan;Growth Option;80.5000;12-Oct-2026
122640;INF879O01019;-;Parag Parikh Flexi Cap Fund;Regular Plan;Growth Option;70.2500;12-Oct-2026
153964;INF879O01100;-;Parag Parikh Flexi Cap Fund;Direct Plan;IDCW Option;60.0000;12-Oct-2026

Open Ended Schemes(Debt Scheme - Liquid Fund)

Axis Mutual Fund

135762;INF846K01WO1;-;Axis Liquid Fund;Direct Plan;Growth Option;2800.1000;12-Oct-2026
135763;INF846K01WS2;-;Axis Liquid Fund;Regular Plan;Growth Option;N.A.;12-Oct-2026
"""

UNIVERSE = pd.DataFrame([
    dict(symbol="RELIANCE", yahoo_symbol="RELIANCE.NS", exchange="NSE", name="Reliance Industries Limited", isin="INE002A01018", series="EQ", also_on="BSE", traded_value=9e9, nifty500=True),
    dict(symbol="M&M", yahoo_symbol="M&M.NS", exchange="NSE", name="Mahindra & Mahindra Limited", isin="INE101A01026", series="EQ", also_on="BSE", traded_value=5e9, nifty500=True),
    dict(symbol="VERTEXPP", yahoo_symbol="890234.BO", exchange="BSE", name="Vertex Securities Ltd.", isin="IN9316D01014", series="X", also_on=None, traded_value=4e5, nifty500=False),
    dict(symbol="GSEC10YEAR", yahoo_symbol="543875.BO", exchange="BSE", name="Mirae Asset Mutual Fund", isin="INF769K01ER0", series="F", also_on=None, traded_value=1e6, nifty500=False),
    dict(symbol="MOSILVER", yahoo_symbol="590147.BO", exchange="BSE", name="MOTILAL OSWAL MUTUAL FUND", isin="INF247L01AB0", series="B", also_on=None, traded_value=1e6, nifty500=False),
])

CG = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 80000.0, "market_cap": 1.6e12, "total_volume": 3e10,
       "market_cap_rank": 1, "price_change_percentage_24h": 1.5, "price_change_24h": 1200.0, "high_24h": 81000.0, "low_24h": 78000.0},
      {"id": "ethereum", "symbol": "eth", "name": "Ethereum", "current_price": 2500.0, "market_cap": 3e11, "total_volume": 1e10,
       "market_cap_rank": 2, "price_change_percentage_24h": -0.5, "price_change_24h": -12.0}]


def daily(n: int = 1500, start: float = 100.0, drift: float = 0.0005, end: str = "2026-10-12") -> pd.DataFrame:
    idx = pd.bdate_range(end=end, periods=n)
    px = start * np.exp(np.cumsum(np.full(n, drift) + np.sin(np.arange(n) / 7) * 0.004))
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99, "Close": px, "Adj Close": px, "Volume": 1000}, index=idx)


def mfapi_json() -> dict:
    d = daily(1500, 20)
    return {"meta": {"fund_house": "Parag Parikh Mutual Fund", "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                     "scheme_category": "Equity Scheme - Flexi Cap Fund", "scheme_code": 122639},
            "data": [{"date": ts.strftime("%d-%m-%Y"), "nav": f"{v:.4f}"} for ts, v in d["Close"][::-1].items()]}


class _Resp:
    def __init__(self, content: bytes | None = None, js=None):
        self.content, self._js, self.text = content or b"", js, (content or b"").decode("utf-8", "replace")

    def json(self):
        return self._js


def _prime(force: bool = False):
    """Stands in for amfi._load (which refuses a download this small as truncated)."""
    if amfi._funds is None:
        amfi._funds = amfi.parse(NAVALL)
        amfi._by_code.clear()
        amfi._by_code.update({f["code"]: f for f in amfi._funds})
    return amfi._funds


def _boom(*a, **k):
    raise RuntimeError("nope")


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    # Instrument tests assert text/grounding; background speech has its own tests.
    monkeypatch.setattr("api.routes.instruments.register_later", lambda fn: "synthetic-audio")
    uni = tmp_path / "universe.parquet"
    UNIVERSE.to_parquet(uni)
    for mod in (amfi, I):
        monkeypatch.setattr(mod, "DIR", tmp_path / "cache")
    monkeypatch.setattr(I, "UNIVERSE", uni)
    monkeypatch.setattr(amfi, "_funds", None)
    monkeypatch.setattr(amfi, "_load", _prime)
    for name, val in (("_cat", None), ("_mf_key", None), ("_crypto_key", None), ("_facet_key", None), ("_cg", (0.0, [])),
                      ("_cg_fail_until", 0.0), ("_yf_down_until", 0.0)):
        monkeypatch.setattr(I, name, val)
    I._mem.clear()
    I._px.clear()

    def fake_get(url, timeout=15, **kw):
        if "mfapi.in" in url:
            return _Resp(js=mfapi_json())
        if "market_chart" in url:
            return _Resp(js={"prices": [[1_700_000_000_000, 70000.0], [1_700_086_400_000, 71000.0]]})
        if "coingecko" in url:
            return _Resp(js=CG)
        if "fred" in url:
            return _Resp(b"observation_date,INDIRLTLT01STM\n2026-05-01,7.0\n2026-06-01,6.9\n2026-07-01,6.8\n")
        raise RuntimeError("unexpected url " + url)

    monkeypatch.setattr(amfi, "http_get", fake_get)
    monkeypatch.setattr(I, "_hist", lambda sym, period, interval: (daily(), False))
    monkeypatch.setattr(I, "_info", lambda sym: {"longBusinessSummary": "A company.", "marketCap": 123456789, "trailingPE": 20.5, "sector": "Energy", "currency": "INR"})
    monkeypatch.setattr(I, "_yahoo_lookup", lambda q: [])
    monkeypatch.setattr(I, "_prices", lambda syms: {s: {"price": 10.0, "change_pct": 1.0, "as_of": "2026-10-12"} for s in syms})
    monkeypatch.setattr("shared.news.fetch_news", lambda *a, **k: [])


def test_amfi_parse_reads_category_amc_plan_and_skips_na():
    funds = amfi.parse(NAVALL)
    assert [f["code"] for f in funds] == ["122639", "122640", "153964", "135762"]  # the "N.A." NAV row is dropped
    f = funds[0]
    assert (f["amc"], f["category"], f["plan"], f["option"], f["isin"], f["nav"], f["date"]) == (
        "Parag Parikh Mutual Fund", "Equity Scheme - Flexi Cap Fund", "Direct", "Growth", "INF879O01027", 80.5, "2026-10-12")
    assert funds[2]["option"] == "IDCW"


def test_search_finds_every_type_with_the_contract_shape():
    r = client.get("/api/instruments/search", params={"q": "reliance"}).json()
    it = r["items"][0]
    assert set(it) == {"id", "symbol", "name", "type", "exchange", "currency", "source", "subtitle"}
    assert it["id"] == "stock:RELIANCE.NS" and it["type"] == "stock"
    assert {"query", "type", "count", "coverage", "limited_coverage"} <= set(r["meta"])

    def ids(q, t="all"):
        return [i["id"] for i in client.get("/api/instruments/search", params={"q": q, "type": t}).json()["items"]]

    assert "mf:122639" in ids("parag parikh flexi")
    assert ids("INF846K01WO1") == ["mf:135762"] and ids("135762") == ["mf:135762"]
    assert "crypto:BTC-USD" in ids("bitcoin")
    assert "bond:^TNX" in ids("treasury") and "bond:IN10Y" in ids("india 10")
    assert "index:^NSEI" in ids("nifty 50") and "commodity:GC=F" in ids("gold") and "currency:USDINR=X" in ids("usd inr")
    assert "etf:NIFTYBEES.NS" in ids("nifty bees")
    assert ids("m&m")[0] == "stock:M&M.NS"


def test_search_bse_only_stock_uses_the_bo_symbol_and_etf_bond_split():
    assert I.search("vertex")["items"][0]["id"] == "stock:890234.BO"
    assert any(i["id"] == "bond:543875.BO" for i in I.search("gsec")["items"])  # BSE series F -> bond
    assert any(i["id"] == "etf:590147.BO" for i in I.search("MOSILVER")["items"])  # "... Mutual Fund" on BSE series B -> ETF


def test_search_type_filter_limit_and_validation():
    r = client.get("/api/instruments/search", params={"q": "fund", "type": "mutual_fund", "limit": 2}).json()
    assert len(r["items"]) == 2 and {i["type"] for i in r["items"]} == {"mutual_fund"}
    assert client.get("/api/instruments/search", params={"q": "x", "type": "nonsense"}).status_code == 422
    r = client.get("/api/instruments/search", params={"q": "bond", "type": "bond"}).json()
    assert r["meta"]["limited_coverage"] == ["bond"] and "LIMITED" in r["meta"]["coverage"]["bond"]


def test_search_caps_funds_so_other_types_stay_visible():
    base = _prime()[0]
    amfi._funds = [{**base, "code": str(900000 + i), "name": f"Gold Fund {i}"} for i in range(40)]
    types = [i["type"] for i in I.search("gold", limit=10)["items"]]
    assert "commodity" in types and types.count("mutual_fund") <= 5


def test_online_lookup_fills_gaps(monkeypatch):
    extra = I._item("stock", "AAPL", "Apple Inc.", "NASDAQ", "", "Yahoo Finance", "AAPL · NASDAQ", 3)
    monkeypatch.setattr(I, "_yahoo_lookup", lambda q: [extra])
    r = I.search("AAPL")
    assert r["items"][0]["id"] == "stock:AAPL" and r["meta"]["online_lookup_used"]


def test_browse_mutual_funds_filters_and_facets():
    r = client.get("/api/instruments/browse", params={"type": "mutual_fund", "plan": "Direct", "option": "Growth"}).json()
    assert {i["id"] for i in r["items"]} == {"mf:122639", "mf:135762"}
    assert r["items"][0]["amc"] and r["items"][0]["price"] and r["meta"]["facets"]["amcs"]
    r = client.get("/api/instruments/browse", params={"type": "mutual_fund", "amc": "axis", "sort": "-nav"}).json()
    assert [i["id"] for i in r["items"]] == ["mf:135762"] and r["meta"]["total"] == 1
    r = client.get("/api/instruments/browse", params={"type": "mutual_fund", "category": "liquid", "page_size": 1}).json()
    assert r["meta"]["pages"] == 1


def test_browse_prices_and_paging_for_yahoo_types():
    r = client.get("/api/instruments/browse", params={"type": "stock", "page_size": 2}).json()
    assert len(r["items"]) == 2 and r["meta"]["total"] == 3 and r["meta"]["pages"] == 2
    assert r["items"][0]["price"] == 10.0 and r["items"][0]["change_pct"] == 1.0
    r = client.get("/api/instruments/browse", params={"type": "index", "prices": "false"}).json()
    assert r["items"] and r["items"][0]["price"] is None
    assert client.get("/api/instruments/browse", params={"type": "bogus"}).status_code == 422


def test_browse_crypto_uses_coingecko_and_falls_back_to_the_curated_list(monkeypatch):
    r = client.get("/api/instruments/browse", params={"type": "crypto", "sort": "-change"}).json()
    assert r["items"][0]["id"] == "crypto:BTC-USD" and r["items"][0]["price"] == 80000.0 and r["items"][0]["rank"] == 1
    monkeypatch.setattr(I, "_coingecko", lambda network=False: [])  # CoinGecko down and nothing cached
    monkeypatch.setattr(I, "_crypto_key", None)
    monkeypatch.setattr(I, "_cg", (0.0, []))
    r = I.browse("crypto", prices=False)
    assert r["meta"]["total"] >= 90 and r["items"][0]["id"] == "crypto:BTC-USD"


def test_quote_mutual_fund_combines_amfi_nav_and_mfapi_history():
    q = client.get("/api/instruments/mf:122639/quote").json()
    assert q["price"] == 80.5 and q["nav"] == 80.5 and q["as_of"] == "2026-10-12" and q["amc"] == "Parag Parikh Mutual Fund"
    assert q["isin"] == "INF879O01027" and q["scheme_category"] == "Equity Scheme - Flexi Cap Fund" and q["expense_ratio"] is None
    assert q["change"] is not None and "once a day" in q["delay_note"]
    assert {"id", "name", "type", "price", "change", "change_pct", "currency", "as_of", "delay_note", "stale", "source"} <= set(q)


def test_quote_stock_crypto_and_bond():
    q = client.get("/api/instruments/stock:RELIANCE.NS/quote").json()
    assert q["price"] and q["currency"] == "INR" and q["market_cap"] == 123456789 and q["year_high"] > q["year_low"]
    c = client.get("/api/instruments/crypto:BTC-USD/quote").json()
    assert c["market_cap"] == 1.6e12 and c["volume_24h"] == 3e10 and c["currency"] == "USD" and "CoinGecko" in c["source"]
    b = client.get("/api/instruments/bond:IN10Y/quote").json()
    assert b["yield"] == 6.8 and b["stale"] is True  # monthly series, older than 75 days
    y = client.get("/api/instruments/bond:^TNX/quote").json()
    assert y["yield"] == y["price"] and "yield" in y["delay_note"].lower()


def test_quote_degrades_instead_of_failing(monkeypatch):
    monkeypatch.setattr(I, "_hist", _boom)
    q = client.get("/api/instruments/index:^NSEI/quote").json()
    assert q["price"] is None and q["stale"] is True and "nope" in q["error"] and q["name"] == "Nifty 50"
    c = client.get("/api/instruments/crypto:BTC-USD/quote").json()  # crypto falls back to CoinGecko's own price
    assert c["price"] == 80000.0 and c["source"] == "CoinGecko"


def test_unknown_or_malformed_ids_are_404():
    for iid in ("nope:XYZ", "mf:999999999", "stock:", "stock:bad%20id"):
        assert client.get(f"/api/instruments/{iid}/quote").status_code == 404, iid
    assert client.get("/api/instruments/stock:AAPL/quote").json()["price"]  # unlisted but well-formed: opened as a Yahoo symbol


def test_chart_ranges_for_yahoo_and_funds():
    for rng in ("1d", "5d", "1m", "6m", "1y", "5y", "max"):
        c = client.get("/api/instruments/stock:RELIANCE.NS/chart", params={"range": rng}).json()
        assert c["points"] and set(c["points"][0]) == {"t", "v"} and c["meta"]["range"] == rng
        assert client.get("/api/instruments/mf:122639/chart", params={"range": rng}).json()["points"], rng
    one_y = client.get("/api/instruments/mf:122639/chart", params={"range": "1y"}).json()
    assert 200 < len(one_y["points"]) < 300 and one_y["meta"]["change_pct"] is not None
    assert len(client.get("/api/instruments/mf:122639/chart", params={"range": "max"}).json()["points"]) <= 600
    assert client.get("/api/instruments/stock:RELIANCE.NS/chart", params={"range": "9y"}).status_code == 422


def test_chart_failure_returns_empty_points_with_error(monkeypatch):
    monkeypatch.setattr(I, "_hist", _boom)
    c = client.get("/api/instruments/stock:RELIANCE.NS/chart").json()
    assert c["points"] == [] and "nope" in c["meta"]["error"]


def test_crypto_chart_falls_back_to_coingecko(monkeypatch):
    monkeypatch.setattr(I, "_hist", _boom)
    c = client.get("/api/instruments/crypto:BTC-USD/chart", params={"range": "1m"}).json()
    assert [p["v"] for p in c["points"]] == [70000.0, 71000.0] and c["meta"]["source"] == "CoinGecko"


def test_profile_has_plain_language_stats_and_tags():
    p = client.get("/api/instruments/mf:122639/profile").json()
    assert "mutual fund" in p["what_is"].lower() and p["key_stats"] and p["disclaimer"]
    assert any(t["tag"] == "Equity fund" for t in p["risk_tags"]) and p["stats"].get("return_1y_pct") is not None
    assert p["stats"].get("cagr_since_start_pct") is not None
    assert any(r["label"] == "Category" for r in p["key_stats"])
    assert any(r["label"] == "CAGR since start" for r in p["key_stats"])
    assert set(p["key_stats"][0]) == {"label", "value"}
    c = client.get("/api/instruments/crypto:BTC-USD/profile").json()
    assert any("legal tender" in t["tag"] for t in c["risk_tags"])
    assert "Futures" in " ".join(t["tag"] for t in client.get("/api/instruments/commodity:GC=F/profile").json()["risk_tags"])


def test_simulate_sip_flat_price_and_known_growth():
    idx = pd.bdate_range("2021-01-01", "2026-10-12")
    flat = [(d.date().isoformat(), 100.0) for d in idx]
    r = I.simulate_sip(flat, 1000, 5)
    assert r["installments"] == 60
    assert r["invested"] == 60 * 1000 and r["value"] == pytest.approx(r["invested"]) and abs(r["xirr_pct"]) < 0.01
    assert r["worst_drawdown_pct"] == 0 and r["years_used"] == pytest.approx(5.0, abs=0.05)
    grow = [(d.date().isoformat(), 100.0 + i * 100.0 / len(idx)) for i, d in enumerate(idx)]
    g = I.simulate_sip(grow, 1000, 5)
    assert g["value"] > g["invested"] and g["xirr_pct"] > 0 and g["cagr_pct"] > 0
    with pytest.raises(I.NoData):
        I.simulate_sip(flat[:30], 1000, 5)


def test_sip_endpoint_shape_validation_and_short_history():
    s = client.get("/api/instruments/mf:122639/sip", params={"monthly": 5000, "years": 5}).json()
    for k in ("invested", "value", "xirr_pct", "cagr_pct", "worst_drawdown_pct", "caveat", "installments", "series"):
        assert k in s
    assert s["installments"] == 60 and s["invested"] == 300000
    assert "does not predict" in s["caveat"] and s["invested"] == s["installments"] * 5000
    assert client.get("/api/instruments/currency:USDINR=X/sip").status_code == 422
    assert client.get("/api/instruments/stock:RELIANCE.NS/sip", params={"years": 99}).status_code == 422
    assert client.get("/api/instruments/stock:RELIANCE.NS/sip", params={"monthly": 5}).status_code == 422
    short = client.get("/api/instruments/stock:RELIANCE.NS/sip", params={"years": 30}).json()
    assert short["years_used"] < 30 and short["meta"]["notes"]


def test_ungrounded_number_check():
    src = '{"price": 1166.7, "change_pct": -0.31, "market_cap": 15788334383104, "date": "2026-10-12"} what is the 5 year trend'
    assert instrument_chat.ungrounded("It trades at ₹1,166.7, down 0.31% on 2026-10-12, over 5 years.", src) == []
    assert instrument_chat.ungrounded("Market cap is about 15.79 trillion, price about 1,167.", src) == []
    assert instrument_chat.ungrounded("The target is ₹1,500.", src) == [1500.0]


def test_ask_is_grounded_and_has_the_chat_shape(mock_llm):
    q = I.quote(I.resolve("stock:RELIANCE.NS"))
    mock_llm.set_response(f"The latest price is ₹{q['price']:,.2f}, as of {q['as_of'][:10]}. Markets can fall as well as rise.")
    body = {"id": "stock:RELIANCE.NS", "question": "How is it doing?", "session_id": "s-inst", "owner_id": "o1"}
    r = client.post("/api/instruments/ask", json=body).json()
    assert r["domain"] == "instrument" and r["query"] == "How is it doing?" and "audio_token" in r
    assert f"{q['price']:,.2f}" in r["response"] and r["response"].strip().endswith("This is not investment advice.")
    assert r["grounding"]["passed"] and not r["grounding"]["fallback"]
    assert "How is it doing?" in mock_llm.calls[0] and "FACTS" in mock_llm.calls[0]
    hist = client.get("/api/chat/history", params={"session_id": "s-inst", "owner_id": "o1"}).json()["history"]
    assert hist and hist[-1]["query"] == "How is it doing?"


def test_ask_replaces_invented_numbers_with_a_facts_only_summary(mock_llm):
    mock_llm.set_response("Analysts expect ₹98,765 by next year, a sure 300% gain.")
    r = client.post("/api/instruments/ask", json={"id": "stock:RELIANCE.NS", "question": "Target price?", "session_id": "s2"}).json()
    assert r["grounding"]["fallback"] and not r["grounding"]["passed"] and "98,765" not in r["response"]
    assert len(mock_llm.calls) == 2  # one retry with the offending numbers named
    assert "not investment advice" in r["response"].lower()


def test_ask_survives_model_failure_and_missing_data(mock_llm, monkeypatch):
    mock_llm.set_response("Error: all backends down")
    r = client.post("/api/instruments/ask", json={"id": "mf:122639", "question": "Is it good?", "session_id": "s3"}).json()
    assert r["grounding"]["fallback"] and "NAV" in r["response"]
    monkeypatch.setattr(I, "_hist", _boom)
    monkeypatch.setattr(I, "_info", lambda s: {})
    mock_llm.calls.clear()
    r = client.post("/api/instruments/ask", json={"id": "index:^NSEI", "question": "Level?", "session_id": "s4"}).json()
    assert mock_llm.calls == [] and "right now" in r["response"] and not r["grounding"]["numbers_checked"]
    assert client.post("/api/instruments/ask", json={"id": "bogus:1", "question": "x", "session_id": "s"}).status_code == 404
    assert client.post("/api/instruments/ask", json={"id": "mf:122639", "question": "", "session_id": "s"}).status_code == 422


def test_ask_directly_answers_since_start_cagr_without_model(mock_llm):
    r = client.post("/api/instruments/ask", json={"id": "mf:122639", "question": "whats the cagr since start of this fund", "session_id": "s-cagr"}).json()
    assert mock_llm.calls == []
    assert not r["grounding"]["fallback"] and r["grounding"]["passed"]
    assert "CAGR since the available history starts" in r["response"]
    assert "Not available right now" not in r["response"]
    assert "profile (TypeError)" not in r["response"]
    assert "This is not investment advice." in r["response"]


def test_grounding_requires_explicit_scale_units():
    assert instrument_chat.ungrounded("Price is 98765", "volatility 99.0495") == [98765]
    assert instrument_chat.ungrounded("Gain is 300%", "investment 300000") == [300]
    assert instrument_chat.ungrounded("Investment is 300 thousand", "investment 300000") == []


def test_user_question_numbers_are_not_quote_evidence(mock_llm):
    mock_llm.set_response("The target price is 98765.")
    r = client.post("/api/instruments/ask", json={"id": "stock:RELIANCE.NS", "question": "Will the target reach 98765?", "session_id": "untrusted-number"}).json()
    assert r["grounding"]["fallback"] and "98765" not in r["response"]


def test_ask_rejects_rupee_sign_for_foreign_currency(mock_llm):
    q = I.quote(I.resolve("crypto:BTC-USD"))
    mock_llm.set_response(f"Bitcoin is at ₹{q['price']:,.0f}.")
    r = client.post("/api/instruments/ask", json={"id": "crypto:BTC-USD", "question": "price?", "session_id": "s5"}).json()
    assert r["grounding"]["passed"] and not r["grounding"]["fallback"]
    assert "₹" not in r["response"] and "USD" in r["response"]
    assert not mock_llm.calls  # Deterministic quote cannot inherit the model's currency error.


@pytest.mark.network
def test_amfi_navall_is_reachable_and_parses():
    import requests

    try:
        text = requests.get(amfi.NAVALL_URL, headers=amfi._UA, timeout=30).content.decode("utf-8", "replace")
    except requests.RequestException as exc:
        pytest.skip(f"AMFI unreachable: {exc}")
    funds = amfi.parse(text)
    assert len(funds) > 5000 and all(f["code"].isdigit() and f["nav"] > 0 for f in funds[:50])
    assert any(f["isin"].startswith("INF") and f["amc"] and f["category"] for f in funds)


@pytest.mark.network
def test_mfapi_history_is_reachable_and_parses():
    import requests

    try:
        js = requests.get(amfi.MFAPI_URL.format(code=119551), headers=amfi._UA, timeout=20).json()
    except (requests.RequestException, ValueError) as exc:
        pytest.skip(f"mfapi unreachable: {exc}")
    rows = amfi._parse_history(js)
    assert len(rows) > 100 and rows == sorted(rows) and js["meta"]["scheme_code"] == 119551
