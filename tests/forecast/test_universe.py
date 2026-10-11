"""Universe discovery, data-failure reasons, the sweep (resume, timeout isolation) and the summary.

All CSV/JSON/price fixtures below are SYNTHETIC samples written for these tests, not real exchange data.
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from modules.equity_research.forecast import contracts as c
from modules.equity_research.forecast import data as D
from modules.equity_research.forecast import universe as U

spec = importlib.util.spec_from_file_location("validate_universe", Path(__file__).parents[2] / "scripts" / "validate_universe.py")
vu = importlib.util.module_from_spec(spec)
sys.modules["validate_universe"] = vu
spec.loader.exec_module(vu)

# SYNTHETIC sample of the NSE EQUITY_L.csv layout (note the leading spaces in headers)
NSE_CSV = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
AAA,Alpha Industries Limited,EQ,06-OCT-2008,5,1,INE000A01011,5
BBB,Beta Corp Limited,BE,03-MAY-1995,10,1,INE000B01011,10
CCC,Gamma SME Limited,SM,19-SEP-2019,1,1,INE000C01011,1
"""
# SYNTHETIC sample of BSE ListofScripData JSON
BSE_JSON = [
    {"SCRIP_CD": "500001", "Scrip_Name": "ALPHA IND", "scrip_id": "AAA", "Issuer_Name": "Alpha Industries Ltd",
     "ISIN_NUMBER": "INE000A01011", "GROUP": "A", "Status": "Active"},
    {"SCRIP_CD": "500002", "Scrip_Name": "DELTA", "scrip_id": "DDD", "Issuer_Name": "Delta Ltd",
     "ISIN_NUMBER": "INE000D01011", "GROUP": "B", "Status": "Active"},
    {"SCRIP_CD": "500003", "Scrip_Name": "OLD", "scrip_id": "OLD", "Issuer_Name": "Old Ltd",
     "ISIN_NUMBER": "INE000E01011", "GROUP": "B", "Status": "Suspended"},
]
# SYNTHETIC sample of the BSE Bhavcopy layout (a bond row must be dropped)
BHAV = """TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,FinInstrmNm,TtlTrfVal
2026-01-02,2026-01-02,CM,BSE,STK,500001,INE000A01011,AAA,A,ALPHA IND LTD,1000.5
2026-01-02,2026-01-02,CM,BSE,STK,500002,INE000D01011,DDD,B,DELTA LTD,50
2026-01-02,2026-01-02,CM,BSE,STK,700001,INE000F07014,BOND,F,SOME DEBENTURE,9
"""


def test_parse_nse():
    e = U.parse_nse(NSE_CSV)
    assert [(x.symbol, x.yahoo_symbol, x.series, x.isin) for x in e] == [
        ("AAA", "AAA.NS", "EQ", "INE000A01011"), ("BBB", "BBB.NS", "BE", "INE000B01011"),
        ("CCC", "CCC.NS", "SM", "INE000C01011")]
    assert all(x.exchange == "NSE" for x in e)


def test_parse_bse_api_and_bhav():
    api = U.parse_bse_api(BSE_JSON)
    assert [x.yahoo_symbol for x in api] == ["500001.BO", "500002.BO"]  # suspended row dropped
    bh = U.parse_bse_bhav(BHAV)
    assert [(x.yahoo_symbol, x.traded_value) for x in bh] == [("500001.BO", 1000.5), ("500002.BO", 50.0)]


def test_merge_dedupes_by_isin_preferring_nse():
    m = U.merge(U.parse_nse(NSE_CSV), U.parse_bse_bhav(BHAV), {"AAA"})
    assert [x.yahoo_symbol for x in m] == ["AAA.NS", "BBB.NS", "CCC.NS", "500002.BO"]
    a = m[0]
    assert a.also_on == "BSE" and a.bse_yahoo_symbol == "500001.BO" and a.nifty500 and a.traded_value == 1000.5
    assert m[3].exchange == "BSE" and not m[3].nifty500  # BSE-only company kept


def test_discover_cache_refresh_and_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "UNIVERSE_DIR", tmp_path)
    monkeypatch.setattr(U, "CACHE", tmp_path / "universe.parquet")
    calls = []
    monkeypatch.setattr(U, "fetch_nse", lambda: calls.append("nse") or U.parse_nse(NSE_CSV))
    monkeypatch.setattr(U, "fetch_bse", lambda: (U.parse_bse_bhav(BHAV), "bhavcopy test"))
    monkeypatch.setattr(U, "fetch_nifty500", lambda: {"AAA"})
    first = U.discover_universe()
    assert len(first) == 4 and (tmp_path / "universe.parquet").exists()
    assert "retrieved_at_utc" in pd.read_parquet(tmp_path / "universe.parquet").columns
    assert len(U.discover_universe()) == 4 and calls == ["nse"]  # fresh cache: no refetch
    old = time.time() - 8 * 86400
    os.utime(tmp_path / "universe.parquet", (old, old))

    def boom():
        raise RuntimeError("unreachable")

    monkeypatch.setattr(U, "fetch_nse", boom)
    assert len(U.discover_universe()) == 4  # stale cache beats nothing
    (tmp_path / "universe.parquet").unlink()
    fb = U.discover_universe()  # no cache, no network: ARIA's own tables, a smaller list
    assert all(x.yahoo_symbol.endswith(".NS") for x in fb)


# -- data failure reasons -------------------------------------------------------------------------------------
def frame(n=1300, vol=1000.0, price=100.0, end=None):
    idx = pd.bdate_range(end=end or pd.Timestamp.now().normalize(), periods=n, tz="Asia/Kolkata")
    px = np.full(n, price)
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Adj Close": px, "Volume": np.full(n, vol),
                         "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)


class FakeTicker:
    frames: dict = {}
    fail: dict = {}

    def __init__(self, sym):
        self.sym = sym

    def history(self, **kw):
        if self.sym in FakeTicker.fail:
            FakeTicker.fail[self.sym]()
        return FakeTicker.frames.get(self.sym, pd.DataFrame())

    info = {}
    fast_info = {}


@pytest.fixture
def yf_fake(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(D, "_JITTER", (0.0, 0.0))
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    monkeypatch.setattr(D, "MAX_STALE_DAYS", 30)
    monkeypatch.setattr(D.yf, "Ticker", FakeTicker)
    FakeTicker.frames, FakeTicker.fail = {}, {}
    return FakeTicker


def reason(sym):
    with pytest.raises(D.DataUnavailable) as ei:
        D.load_history(sym)
    return ei.value.reason


def test_failure_reasons(yf_fake):
    nan = frame()
    nan["Adj Close"] = np.nan
    yf_fake.frames = {"EMPTY.NS": pd.DataFrame(), "SHORT.NS": frame(n=300), "ZERO.NS": frame(vol=0.0),
                      "OLD.NS": frame(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=90)), "NAN.NS": nan,
                      "NEG.NS": frame(price=-1.0)}
    assert reason("EMPTY.NS") == "no_data"
    assert reason("SHORT.NS") == "insufficient_history"
    assert reason("ZERO.NS") == "all_zero_volume"
    assert reason("OLD.NS") == "stale"
    assert reason("NAN.NS") == "bad_data" and reason("NEG.NS") == "bad_data"
    yf_fake.fail["DOWN.NS"] = lambda: (_ for _ in ()).throw(ValueError("weird parse error"))
    assert reason("DOWN.NS") == "download_error"


def test_transient_errors_are_retried(yf_fake):
    n = {"calls": 0}

    def flaky():
        n["calls"] += 1
        if n["calls"] < 3:
            raise RuntimeError("HTTP Error 429: Too Many Requests")

    yf_fake.frames = {"OK.NS": frame()}
    yf_fake.fail["OK.NS"] = flaky
    df = D._fetch("OK.NS")
    assert len(df) == 1300 and n["calls"] == 3


def test_benchmark_loaded_once_per_process(yf_fake):
    D._SERIES_MEM.clear()
    yf_fake.frames = {"^NSEI": frame()}
    a = D.load_series("^NSEI")
    (D.CACHE_DIR / "^NSEI.parquet").unlink()
    assert D.load_series("^NSEI") is a  # served from memory, no file or network


# -- sweep ----------------------------------------------------------------------------------------------------
def entry(sym):
    return U.UniverseEntry(symbol=sym.split(".")[0], yahoo_symbol=sym, exchange="NSE", name=sym)


def fake_worker(conn, mode):
    """Stand-in for the real worker, picklable by name under spawn."""
    while True:
        sym = conn.recv()
        if sym is None:
            return
        if "SLOW" in sym:
            time.sleep(120)
        if "DIE" in sym:
            os._exit(3)
        conn.send({"status": "ok_beats_baseline", "reason": None, "seconds": 0.1})


def test_timeout_isolated_and_sweep_never_raises(tmp_path, monkeypatch, tmpdb):
    monkeypatch.setattr(vu, "state_path", lambda: tmp_path / "s.json")
    state = {"meta": {}, "symbols": {}}
    syms = ["A.NS", "SLOW.NS", "DIE.NS", "B.NS", "C.NS"]
    t0 = time.time()
    sw = vu.Sweep([entry(s) for s in syms], "light", 2, 20.0, state, worker=fake_worker)
    counts = sw.run()
    got = {k: v["status"] for k, v in state["symbols"].items()}
    assert got == {"A.NS": "ok_beats_baseline", "SLOW.NS": "timeout", "DIE.NS": "failed",
                   "B.NS": "ok_beats_baseline", "C.NS": "ok_beats_baseline"}
    assert counts["timeout"] == 1 and time.time() - t0 < 90
    assert vu.load_state(tmp_path / "s.json")["symbols"]["SLOW.NS"]["status"] == "timeout"


def test_work_never_raises(monkeypatch):
    from modules.equity_research.forecast import jobs

    def boom(*a, **k):
        raise MemoryError("synthetic")

    monkeypatch.setattr(jobs, "run_inline", boom)
    r = vu._work("X.NS", "light")
    assert r["status"] == "failed" and "MemoryError" in r["reason"]


def completed_run(sym, cutoff):
    from modules.equity_research.forecast import jobs

    return c.RunResult(run_id=f"r{sym}", symbol=sym, status="no_model_beats_baseline", cache_key=jobs._key(sym, cutoff),
                       training_cutoff=cutoff)


def test_resume_skips_completed(tmpdb, monkeypatch):
    from modules.equity_research.forecast import store

    cutoff = str(np.busday_offset(np.datetime64("today"), -1, roll="backward"))
    store.save_run(completed_run("DONE.NS", cutoff))
    st = {"meta": {}, "symbols": {"DONE.NS": {"status": "no_model_beats_baseline", "mode": "light", "ts": vu._now()},
                                  "BAD.NS": {"status": "failed", "mode": "light", "ts": vu._now()},
                                  "NODATA.NS": {"status": "data_unavailable", "reason": "no_data", "mode": "light",
                                                "ts": vu._now()}}}
    assert vu.already_done("DONE.NS", st, "light")
    assert not vu.already_done("DONE.NS", st, "full")  # different model set
    assert not vu.already_done("BAD.NS", st, "light")  # failures are retried
    assert vu.already_done("NODATA.NS", st, "light")  # recent data verdict kept
    assert not vu.already_done("NEW.NS", st, "light")
    store.save_run(completed_run("OLD.NS", "2020-01-02"))
    assert not vu.already_done("OLD.NS", st, "light")  # data cutoff too old to count as current

    seen = {}

    class Spy:
        def __init__(self, todo, *a, **k):
            seen["todo"], seen["skipped"] = [e.yahoo_symbol for e in todo], a[-1] if a else k.get("skipped")

        def run(self):
            return {}

    monkeypatch.setattr(vu, "Sweep", Spy)
    monkeypatch.setattr(vu, "save_state", lambda *a, **k: None)
    vu.run_sweep([entry(s) for s in ("DONE.NS", "NEW.NS", "BAD.NS")], "light", 2, 10, True, state=st)
    assert seen["todo"] == ["NEW.NS", "BAD.NS"]


# -- summary --------------------------------------------------------------------------------------------------
def horizon(h, sel, ps, tps, status="ok_beats_baseline"):
    def res(name, p, tp):
        return c.HorizonModelResult(horizon=h, model=name, family="ml",
                                    test=c.MetricBlock(n=500, coverage_90=0.88, mae_ret=0.9),
                                    vs_baseline=c.BaselineComparison(mae_improvement_pct=2.0, dm_p=p, dm_p_test=tp))

    base = c.HorizonModelResult(horizon=h, model="rw", family="baseline", test=c.MetricBlock(n=500, mae_ret=1.0))
    return c.HorizonResult(horizon=h, status=status, selected_model=sel, baseline_results=[base],
                           results=[res("ridge", ps[0], tps[0]), res("ar", ps[1], tps[1])])


def run_of(sym, **kw):
    d = c.DatasetMeta(symbol=sym, market="IN", provider="yfinance", retrieved_at_utc="x", first_bar="2005-01-03",
                      last_bar="2026-01-02", n_bars=5000)
    hs = [horizon(5, **kw)] if kw else []
    return c.RunResult(run_id=sym, symbol=sym, status="ok_beats_baseline" if kw else "no_model_beats_baseline",
                       dataset=d, horizons=hs)


def test_summary_aggregation_and_fdr(tmp_path):
    runs = {"A.NS": run_of("A.NS", sel="ridge", ps=(1e-7, 0.5), tps=(1e-5, 0.4)),
            "B.NS": run_of("B.NS", sel="ridge", ps=(0.03, 0.6), tps=(0.2, 0.7)),
            "C.NS": run_of("C.NS")}
    states = {s: {"status": r.status, "reason": None, "seconds": 5.0} for s, r in runs.items()}
    states["D.NS"] = {"status": "data_unavailable", "reason": "stale", "seconds": 1.0}
    entries = [entry(s) for s in ("A.NS", "B.NS", "C.NS", "D.NS", "E.NS")]  # E never attempted
    df = vu_summary(entries, states, runs)
    assert len(df) == 4 and df.set_index("symbol").loc["D", "outcome"] == "stale"
    ix = df.set_index("symbol")
    assert bool(ix.loc["A", "fdr_val_h5"]) and not bool(ix.loc["B", "fdr_val_h5"])  # B's p=0.03 does not survive BH
    assert bool(ix.loc["A", "fdr_test_h5"]) and not bool(ix.loc["B", "fdr_test_h5"])
    assert ix.loc["A", "n_bars"] == 5000 and ix.loc["A", "sel_test_impr_h5"] == pytest.approx(10.0)
    assert ix.loc["A", "cov90_h5"] == pytest.approx(0.88)
    text = U.write_report(df, 5, tmp_path / "r.md")
    for needle in ("## Honesty section", "Survivorship", "stale | 1", "5%", "| 5d |"):
        assert needle in text
    assert (tmp_path / "r.md").read_text(encoding="utf-8") == text


def vu_summary(entries, states, runs):
    return U.build_summary(entries, states, runs.get)


def test_summary_endpoints(tmp_path, monkeypatch):
    from api.main import app

    monkeypatch.setattr(U, "UNIVERSE_DIR", tmp_path)
    client = TestClient(app)
    base = "/api/research/validation/universe"
    assert client.get(f"{base}/summary").json()["symbols"] == 0
    assert client.get(f"{base}/RELIANCE.NS").status_code == 404
    pd.DataFrame([{"yahoo_symbol": "RELIANCE.NS", "outcome": "no_model_beats_baseline", "status": "x", "n_bars": 5000,
                   "selected_h5": None},
                  {"yahoo_symbol": "ZZZ.NS", "outcome": "stale", "status": "data_unavailable", "n_bars": None,
                   "selected_h5": None}]).to_parquet(tmp_path / "summary.parquet")
    s = client.get(f"{base}/summary").json()
    assert s["symbols"] == 2 and s["by_outcome"] == {"no_model_beats_baseline": 1, "stale": 1} and s["last_updated"]
    r = client.get(f"{base}/reliance.ns").json()
    assert r["n_bars"] == 5000 and r["selected_h5"] is None
    assert client.get(f"{base}/NOPE.NS").status_code == 404
