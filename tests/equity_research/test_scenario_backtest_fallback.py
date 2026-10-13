"""Scenario backtest: yfinance fallback, short-history mode, transient failures, outage pause (offline, mocked HTTP)."""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
import requests

from modules.equity_research.forecast import data as fdata
from modules.equity_research.scenario_backtest import data, engine, jobs
from modules.equity_research.scenario_backtest import metrics as M
from tests.equity_research._intel_fixtures import daily_prices, operating_raw, tables_from_raw

PX, NIFTY = daily_prices()


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(fdata, "CACHE_DIR", tmp_path / "px")
    monkeypatch.setattr(data, "JITTER", (0, 0))
    monkeypatch.setattr(engine, "fdata_nifty", lambda: NIFTY)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    jobs._running.clear()


def yf_frames(years=(2022, 2023, 2024, 2025), bank=False):
    ts = [pd.Timestamp(f"{y}-03-31") for y in years]
    cr = 1e7
    inc = {"Total Revenue": [100 * cr * (1.1 ** i) for i in range(len(ts))], "Reconciled Depreciation": [5 * cr] * len(ts),
           "Operating Income": [18 * cr] * len(ts), "Pretax Income": [15 * cr] * len(ts), "Tax Provision": [3.75 * cr] * len(ts),
           "Net Income Common Stockholders": [11 * cr] * len(ts), "Diluted EPS": [22.0] * len(ts), "Interest Expense": [1 * cr] * len(ts)}
    if bank:
        inc["Net Interest Income"] = [30 * cr] * len(ts)
    bs = {"Common Stock": [5 * cr] * len(ts), "Stockholders Equity": [80 * cr] * len(ts), "Total Debt": [20 * cr] * len(ts), "Total Assets": [200 * cr] * len(ts)}
    cf = {"Operating Cash Flow": [14 * cr] * len(ts), "Free Cash Flow": [9 * cr] * len(ts), "Cash Dividends Paid": [-3.3 * cr] * len(ts)}
    mk = lambda d: pd.DataFrame(d, index=ts).T  # noqa: E731
    return mk(inc), mk(bs), mk(cf)


# ── mapping ───────────────────────────────────────────────────────────────
def test_yfinance_mapping_rows_units_and_split_adjustment():
    inc, bs, cf = yf_frames()
    splits = pd.Series([0.0, 2.0], index=pd.to_datetime(["2023-06-01", "2024-09-01"]))  # 2:1 after FY2024 year-end
    t, issues = data.map_yfinance(inc, bs, cf, splits=splits)
    assert t["pl"]["cols"] == ["Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025"]
    pl = t["pl"]["rows"]
    assert pl["Sales"]["Mar 2022"] == pytest.approx(100.0)  # Rs Cr
    assert pl["Operating Profit"]["Mar 2022"] == pytest.approx(23.0)  # operating income + depreciation
    assert pl["Net Profit"]["Mar 2023"] == pytest.approx(11.0) and pl["Tax %"]["Mar 2022"] == pytest.approx(25.0)
    assert pl["EPS in Rs"]["Mar 2024"] == pytest.approx(11.0) and pl["EPS in Rs"]["Mar 2025"] == pytest.approx(22.0)  # restated only before the split
    assert pl["Dividend Payout %"]["Mar 2022"] == pytest.approx(30.0)
    assert t["bs"]["rows"]["Reserves"]["Mar 2022"] == pytest.approx(75.0) and t["bs"]["rows"]["Borrowings"]["Mar 2022"] == pytest.approx(20.0)
    assert t["cf"]["rows"]["Free Cash Flow"]["Mar 2022"] == pytest.approx(9.0)
    assert "ratios" not in t and any(i["reason"] == "yfinance_fallback" for i in issues)
    _, issues2 = data.map_yfinance(inc, bs, cf)
    assert any(i["reason"] == "eps_not_split_adjusted" for i in issues2)


def test_mapped_tables_pass_quality_and_run_the_engine():
    inc, bs, cf = yf_frames(years=(2021, 2022, 2023, 2024, 2025))
    t, _ = data.map_yfinance(inc, bs, cf, splits=pd.Series(dtype=float, index=pd.DatetimeIndex([])))
    meta = {"provider": "yfinance", "view": "yfinance fallback (5 fiscal years)", "sector": "Technology", "industry": "IT Services", "is_financial": False}
    clean, _, excl = data.quality(t, meta)
    assert not excl["company"] and excl["n_years"] == 5
    assert engine.origin_years(clean, excl) == ["Mar 2022", "Mar 2023", "Mar 2024"]
    r, o = engine.run_origin("YF.NS", clean, meta, PX, NIFTY, "Mar 2024", exclusions=excl)
    assert o["provider"] == "yfinance" and o["n_years"] == 4 and o["v_base"] > 0
    r, o = engine.run_origin("YF.NS", clean, meta, PX, NIFTY, "Mar 2022", exclusions=excl)
    assert "short_history" in o["flags"] and o["n_years"] == 2


# ── fallback chain ────────────────────────────────────────────────────────
def fake_yf(monkeypatch, inc_bs_cf=None, boom=None):
    import yfinance as yf

    class T:
        def __init__(self, s):
            if boom:
                raise boom
            self.income_stmt, self.balance_sheet, self.cashflow = inc_bs_cf or yf_frames()

    monkeypatch.setattr(yf, "Ticker", T)
    monkeypatch.setattr(fdata, "_info", lambda s: {"sector": "Technology", "industry": "IT Services"})


def test_screener_down_falls_back_to_yfinance_and_tags_the_provider(monkeypatch):
    calls = []

    def down(*a, **k):
        calls.append(1)
        raise requests.ConnectTimeout("connect timed out")

    monkeypatch.setattr(requests, "get", down)
    fake_yf(monkeypatch)
    tables, meta = data.fetch_tables("NEWCO", symbol="NEWCO.NS")
    assert meta["provider"] == "yfinance" and meta["view"] == "yfinance fallback (4 fiscal years)"
    assert meta["screener_status"] == "unreachable" and "ConnectTimeout" in meta["fallback_reason"]
    assert data.provider_label(meta) == "yfinance fallback (4 fiscal years)"
    assert len(calls) == data.CONNECT_RETRIES  # connect failures are not hammered
    assert data.load("NEWCO.NS")[1]["provider"] == "yfinance"


def test_breaker_opens_after_three_failures_and_skips_screener(monkeypatch):
    n = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: (n.append(1), (_ for _ in ()).throw(requests.ConnectionError("down")))[1])
    fake_yf(monkeypatch)
    for i in range(3):
        data.fetch_tables(f"C{i}", symbol=f"C{i}.NS")
    assert data.breaker_open()
    before = len(n)
    data.fetch_tables("C9", symbol="C9.NS")
    assert len(n) == before  # breaker open: straight to the fallback, no screener request
    data.reset_breaker()
    assert not data.breaker_open()


def test_both_sources_unreachable_is_transient_not_failure(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectTimeout("t")))
    fake_yf(monkeypatch, boom=RuntimeError("429 Too Many Requests"))
    monkeypatch.setattr(fdata, "_retry", lambda fn, what: fn())
    with pytest.raises(data.Transient):
        data.fetch_tables("X", symbol="X.NS")
    s = jobs.compute("X.NS")
    assert s["status"] == "retry" and "Transient" in s["reason"] and not jobs.is_current("X.NS")


def test_screener_404_uses_yfinance_and_both_missing_is_lookup_error(monkeypatch):
    class R:
        status_code, text, url = 404, "", "https://www.screener.in/company/X/"
        headers: dict = {}

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    fake_yf(monkeypatch)
    _, meta = data.fetch_tables("X", symbol="X.NS")
    assert meta["provider"] == "yfinance" and meta["screener_status"] == "no_page"
    fake_yf(monkeypatch, inc_bs_cf=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()))
    with pytest.raises(LookupError):
        data.fetch_tables("Y", symbol="Y.NS")


def test_classify():
    assert jobs.classify(requests.ConnectTimeout("x")) == "retry"
    assert jobs.classify(fdata.DataUnavailable("download failed", "download_error")) == "retry"
    assert jobs.classify(RuntimeError("HTTP 429 Too Many Requests")) == "retry"
    assert jobs.classify(fdata.DataUnavailable("none", "no_data")) == "no_price"
    assert jobs.classify(fdata.DataUnavailable("bad", "bad_data")) == "failed"
    assert jobs.classify(KeyError("x")) == "failed"


# ── prices ────────────────────────────────────────────────────────────────
def test_prices_tries_other_ticker_and_records_precise_reason(monkeypatch):
    seen = []

    def load(s, **k):
        seen.append(s)
        if s == "ACME.NS":
            return PX.assign(open=1.0), None
        raise fdata.DataUnavailable(f"no price history returned for {s}", "no_data")

    monkeypatch.setattr(fdata, "load_history", load)
    df = data.prices("500001.BO", {"nse_symbol": "ACME"})
    assert seen == ["500001.BO", "ACME.NS"] and df.attrs["price_symbol"] == "ACME.NS"
    monkeypatch.setattr(fdata, "load_history", lambda s, **k: (_ for _ in ()).throw(fdata.DataUnavailable("none", "no_data")))
    with pytest.raises(fdata.DataUnavailable) as e:
        data.prices("500002.BO")
    assert "500002.BO: no_data" in str(e.value) and "500002.NS: no_data" in str(e.value) and e.value.reason == "no_data"


def test_prices_cache_first_never_refetches_old_history(monkeypatch, tmp_path):
    fdata.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PX.to_parquet(fdata._path("OLD.NS"))
    monkeypatch.setattr(fdata, "load_history", lambda *a, **k: pytest.fail("network used with a fresh cache file"))
    assert len(data.prices("OLD.NS")) == len(PX)


def test_price_download_error_with_no_cache_is_retry(monkeypatch):
    monkeypatch.setattr(fdata, "load_history", lambda s, **k: (_ for _ in ()).throw(fdata.DataUnavailable("download failed", "download_error")))
    data.save_tables("NP.NS", tables_from_raw(operating_raw(y0=2015, y1=2026)), {"is_financial": False})
    assert jobs.compute("NP.NS")["status"] == "retry"


def test_no_price_status_names_every_ticker(monkeypatch):
    monkeypatch.setattr(fdata, "load_history", lambda s, **k: (_ for _ in ()).throw(fdata.DataUnavailable("none", "no_data")))
    data.save_tables("544937.BO", tables_from_raw(operating_raw(y0=2015, y1=2026)), {"is_financial": False})
    s = jobs.compute("544937.BO")
    assert s["status"] == "no_price" and "544937.NS" in s["reason"] and not jobs.is_current("544937.BO")


# ── short-history mode through the job ────────────────────────────────────
def test_new_company_runs_in_short_history_mode(monkeypatch):
    monkeypatch.setattr(data, "prices", lambda s, meta=None: PX)
    meta = {"provider": "yfinance", "view": "yfinance fallback (4 fiscal years)", "sector": "Technology", "industry": "IT Services", "is_financial": False}
    s = jobs.compute("NEW.NS", tables_from_raw(operating_raw(y0=2023, y1=2026)), meta)
    assert s["status"] == "ok" and s["provider"] == "yfinance" and s["n_fiscal_years"] == 4
    assert s["n_origins"] == 2 and s["n_origins_short"] == 2  # FY24 (2 years) and FY25 (3 years); FY26 has 4 years but nothing later to score
    assert s["metrics"]["short_history"]["n_origins"] == 2
    assert s["metrics"]["excluded"]["short_history"] > 0
    o = pd.read_parquet(jobs._p("NEW.NS", "origins.parquet"))
    assert set(o.provider) == {"yfinance"} and sorted(o.n_years) == [2, 3]


def test_short_rows_stay_out_of_headline_cells():
    from tests.equity_research.test_scenario_backtest_metrics import _frames

    f, o = _frames("A", [("Mar 2020", "revenue", 1, {"bear": 90, "base": 110, "bull": 130}, 100, "short_history"),
                         ("Mar 2021", "revenue", 1, {"bear": 90, "base": 120, "bull": 130}, 100)])
    s = M.company_summary(f, o)
    assert s["lines"]["revenue"]["k"][1]["base"]["bias"] == pytest.approx(math.log(1.2))
    assert s["short_history"]["lines"]["revenue"]["k"][1]["base"]["bias"] == pytest.approx(math.log(1.1))
    assert s["excluded"]["short_history"] >= 1


# ── resume semantics for results already on disk ─────────────────────────
def test_resume_reruns_insufficient_but_keeps_unchanged_ok(monkeypatch):
    monkeypatch.setattr(data, "prices", lambda s, meta=None: PX)
    old = tables_from_raw(operating_raw(y0=2015, y1=2026))  # long history: sb2 adds nothing
    young = tables_from_raw(operating_raw(y0=2022, y1=2026))  # sb1 would have said insufficient_history
    for sym, t in (("OLD.NS", old), ("YNG.NS", young)):
        jobs.compute(sym, t, {"sector": "Technology", "industry": "IT Services"})
        sm = jobs._read_summary(sym)
        sm.update(engine="sb1", key=jobs._key(sym, "sb1"), status="ok" if sym == "OLD.NS" else "insufficient_history")
        jobs._p(sym, "summary.json").write_text(json.dumps(sm))
    assert jobs.is_current("OLD.NS")  # sb1 ok result, long history: numbers cannot change
    assert not jobs.is_current("YNG.NS")  # sb1 insufficient_history / short company: re-evaluated
    jobs.compute("YNG.NS")
    assert jobs._read_summary("YNG.NS")["engine"] == "sb2" and jobs.is_current("YNG.NS")


# ── sweep: retry statuses and outage pause ────────────────────────────────
def test_sweep_retries_transient_and_pauses_on_outage(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import scenario_backtest_universe as sw
    from modules.equity_research.forecast.universe import UniverseEntry

    for st in ("retry", "no_price", "failed", "timeout"):
        assert not sw.already_done("A.NS", {"meta": {}, "symbols": {"A.NS": {"status": st}}}, "sb")
    sleeps, saved = [], []
    ents = [UniverseEntry(f"A{i}", f"A{i}.NS", "NSE", "n") for i in range(25)]
    state = {"meta": {}, "symbols": {}}
    monkeypatch.setattr(sw.vu, "save_state", lambda s, path=None: saved.append(1))
    sweep = sw.OutageSweep(ents, "sb", 1, 300, state, sleep=lambda s: sleeps.append(s))
    sweep.slots = []
    from collections import Counter

    c, secs = Counter(), []
    for e in ents[:10]:
        sweep._record(e, {"status": "retry", "reason": "ConnectTimeout", "seconds": 1}, c, secs)
    assert sweep.pauses == 1 and sum(sleeps) == sw.PAUSE_S and sweep.pause_s == sw.PAUSE_S * 2 and sweep.streak == 0
    for e in ents[10:20]:
        sweep._record(e, {"status": "retry", "reason": "x", "seconds": 1}, c, secs)
    assert sweep.pauses == 2 and sweep.pause_s == sw.PAUSE_S * 4  # doubling backoff
    sweep._record(ents[20], {"status": "ok", "seconds": 1}, c, secs)
    assert sweep.pause_s == sw.PAUSE_S and state["symbols"]["A0.NS"]["status"] == "retry"
    for e in ents[21:24]:
        sweep._record(e, {"status": "retry", "seconds": 1}, c, secs)
    assert sweep.pauses == 2  # 3 failures: below the threshold, no pause


def test_universe_report_provider_short_slice_and_data_flags_not_reasons():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import scenario_backtest_universe as sw
    from modules.equity_research.forecast.universe import UniverseEntry

    ents = [UniverseEntry(f"S{i}", f"S{i}.NS", "NSE", "n") for i in range(3)]
    state = {"meta": {}, "symbols": {f"S{i}.NS": {"status": "insufficient_history", "seconds": 1} for i in range(3)}}
    # one with only data-flag issues and no reason: must NOT show structural_break / share_basis as the reason
    jobs._write("S0.NS", {"status": "insufficient_history", "key": "k", "issues": [{"reason": "structural_break"}, {"reason": "share_basis"}],
                          "provider": "screener.in", "n_fiscal_years": 2, "reason": "2 fiscal years available (Mar 2025..Mar 2026); 3 needed (2 to project from + 1 to score)"})
    jobs._write("S1.NS", {"status": "insufficient_history", "key": "k", "issues": [{"reason": "structural_break"}], "provider": "yfinance", "n_fiscal_years": 1,
                          "reason": "1 fiscal years available (Mar 2026..Mar 2026); 3 needed (2 to project from + 1 to score)"})
    jobs._write("S2.NS", {"status": "insufficient_history", "key": "k", "issues": [{"reason": "structural_break"}, {"reason": "share_basis"}]})
    df = sw.build_summary(ents, state)
    text = sw.write_report(df, data.CACHE_DIR / "R.md", 3)
    reasons = text.split("### Exclusions by reason")[1].split("###")[0]
    assert "structural_break" not in reasons and "share_basis" not in reasons
    assert "fiscal years available; 3 needed" in reasons  # exact counts, dates grouped away
    assert "### Coverage by data provider" in text and "yfinance" in text and "screener.in" in text
    assert "### Insufficient history by fiscal years available" in text


def test_aggregate_has_short_history_slice_and_provider_split():
    from tests.equity_research.test_scenario_backtest_metrics import _universe

    f, o = _universe(40, 5)
    fs, os_ = _universe(35, -5)
    fs = fs.assign(symbol="Z" + fs.symbol, flags="short_history")
    os_ = os_.assign(symbol="Z" + os_.symbol, flags="short_history", provider="yfinance")
    agg = M.aggregate(pd.concat([f, fs]), pd.concat([o, os_]))
    assert agg["lines"]["revenue"]["k"][3]["n_companies"] == 40  # short rows never reach the headline cell
    assert agg["short_history"]["n_companies"] == 35 and agg["short_history"]["lines"]["revenue"]["k"][3]["n_companies"] == 35
    assert agg["excluded"]["short_history"] == 35 * 3
    assert set(agg["by_provider"]) == {"screener.in"}  # the yfinance origins are all short, so none reach the headline slice
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import scenario_backtest_universe as sw

    text = "\n".join(sw._results(agg))
    assert "Short-history slice" in text and "short history" in text.lower()


def test_too_few_screener_years_trigger_one_yfinance_attempt(monkeypatch):
    monkeypatch.setattr(data, "prices", lambda s, meta=None: PX)
    data.save_tables("TINY.NS", tables_from_raw(operating_raw(y0=2026, y1=2026)), {"sector": "Technology", "is_financial": False})
    fake_yf(monkeypatch, inc_bs_cf=yf_frames(years=(2022, 2023, 2024, 2025, 2026)))
    f, o = engine.run_company("TINY.NS")
    assert f.attrs["provider"] == "yfinance" and f.attrs["status"] == "ok" and len(o) >= 2 and "short_history" in o["flags"].iloc[0]
    meta = data.load("TINY.NS")[1]
    assert meta["provider"] == "yfinance" and meta["screener_status"] == "too_few_years"
    # yfinance with nothing more to offer: the attempt is recorded and not repeated
    data.save_tables("TINY2.NS", tables_from_raw(operating_raw(y0=2026, y1=2026)), {"is_financial": False})
    fake_yf(monkeypatch, inc_bs_cf=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()))
    f, _ = engine.run_company("TINY2.NS")
    assert f.attrs["status"] == "insufficient_history" and data.load("TINY2.NS")[1]["fallback_tried"]
    fake_yf(monkeypatch, boom=AssertionError("second attempt"))
    engine.run_company("TINY2.NS")


def _page(url, with_rows):
    body = ('<tr><td>Sales</td><td>100</td><td>110</td></tr><tr><td>Net Profit</td><td>10</td><td>12</td></tr>' if with_rows else "")
    html = (f'<html><body><section id="profit-loss"><table><thead><tr><th></th>{"<th>Mar 2024</th><th>Mar 2025</th>" if with_rows else ""}'
            f"</tr></thead><tbody>{body}</tbody></table></section></body></html>")
    r = requests.Response()
    r.status_code, r._content, r.url = 200, html.encode(), url
    return r


def test_empty_consolidated_page_falls_back_to_standalone(monkeypatch):
    """screener answers 200 (not 404) with an empty consolidated table for companies that report standalone only."""
    seen = []

    def fake_get(url):
        seen.append(url)
        return _page(url, with_rows=not url.rstrip("/").endswith("/consolidated"))

    monkeypatch.setattr(data, "_get", fake_get)
    monkeypatch.setattr(fdata, "_info", lambda sym: {})
    tables, meta = data._from_screener("500016", "500016.BO")
    assert [u.rstrip("/").rsplit("/", 1)[-1] for u in seen] == ["consolidated", "500016"]
    assert meta["view"] == "standalone"
    assert "Sales" in tables["pl"]["rows"] and len(tables["pl"]["cols"]) == 2


def test_numeric_bse_code_maps_to_the_security_id_yahoo_serves(monkeypatch):
    """Yahoo has no data under 500016.BO but does under ARUNAHTEL.BO: the id is tried first."""
    monkeypatch.setattr(data, "_BSE_IDS", {"500016": "ARUNAHTEL"})
    assert data.alt_symbols("500016.BO")[0] == "ARUNAHTEL.BO"
    assert data.alt_symbols("500016.BO", {"nse_symbol": "ARUNA"})[:2] == ["ARUNAHTEL.BO", "ARUNA.NS"]
    assert data.alt_symbols("500999.BO")[0] == "500999.NS"  # unknown code: previous behaviour
    assert data.alt_symbols("TCS.NS") == ["TCS.BO"]
