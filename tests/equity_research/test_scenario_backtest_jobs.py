"""Scenario backtest WP5: result files, cache key, job states, API, pipeline hook, sweep helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from modules.equity_research.scenario_backtest import data, engine, jobs
from tests.equity_research._intel_fixtures import bank_raw, daily_prices, operating_raw, tables_from_raw

PX, NIFTY = daily_prices()
META = {"sector": "Financial Services", "industry": "Banks - Regional", "is_financial": True}
client = TestClient(app)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(data, "prices", lambda s, meta=None: PX)
    monkeypatch.setattr(engine, "fdata_nifty", lambda: NIFTY)
    jobs._running.clear()


def bank():
    return tables_from_raw(bank_raw(y0=2015, y1=2026))


def test_compute_writes_files_and_reuses_by_key(monkeypatch):
    s = jobs.compute("TSTB.NS", bank(), META)
    assert s["status"] == "ok" and s["n_origins"] == 8 and len(s["key"]) == 40
    for ext in ("forecasts.parquet", "origins.parquet", "summary.json"):
        assert jobs._p("TSTB.NS", ext).exists()
    monkeypatch.setattr(engine, "run_company", lambda s: pytest.fail("recomputed despite an unchanged key"))
    assert jobs.compute("TSTB.NS", bank(), META)["key"] == s["key"]
    t = bank()
    next(iter(t["pl"]["rows"].values()))["Mar 2020"] *= 2  # different inputs -> new key
    data.save_tables("TSTB.NS", t, META)
    assert not jobs.is_current("TSTB.NS")


def test_engine_version_is_part_of_the_key(monkeypatch):
    jobs.compute("TSTB.NS", bank(), META)
    assert jobs.is_current("TSTB.NS")
    monkeypatch.setattr(jobs, "ENGINE_VERSION", "sb9")
    assert not jobs.is_current("TSTB.NS")


def test_insufficient_history_and_no_screener_page(monkeypatch):
    s = jobs.compute("SHORT.NS", tables_from_raw(operating_raw(y0=2025, y1=2026)), {"is_financial": False})
    assert s["status"] == "insufficient_history" and jobs.status("SHORT.NS") == "insufficient_history"
    assert "2 fiscal years available" in s["reason"] and s["n_fiscal_years"] == 2

    def nope(slug, **kw):
        raise LookupError("no_screener_page (500325: status 404)")

    monkeypatch.setattr(data, "fetch_tables", nope)
    s = jobs.compute("500325.BO")
    assert s["status"] == "no_screener_page" and jobs.is_current("500325.BO")


def test_failure_is_recorded_not_raised(monkeypatch):
    monkeypatch.setattr(engine, "run_company", lambda s: 1 / 0)
    assert jobs.compute("X.NS")["status"] == "failed"
    assert not jobs.is_current("X.NS")  # failures are retried


def test_submit_runs_in_background_and_status_progression():
    assert jobs.status("TSTB.NS") == "not_run"
    assert jobs.submit("TSTB.NS", bank(), META) == "computing"
    assert jobs.wait_idle(60)
    assert jobs.status("TSTB.NS") == "ok"
    r = jobs.get_result("TSTB.NS")
    assert len(r["origins"]) == 8 and r["forecasts"] == [] and not r["stale"]
    assert len(jobs.get_result("TSTB.NS", include_forecasts=True)["forecasts"]) > 0


def test_api(monkeypatch):
    assert client.get("/api/research/scenario-backtest/TSTB").status_code == 404
    assert client.post("/api/research/scenario-backtest", json={"symbol": "bad symbol!"}).status_code == 422
    assert client.get("/api/research/scenario-backtest/universe/summary").json() == {"symbols": 0, "by_status": {}, "last_updated": None}
    jobs.compute("TSTB.NS", bank(), META)
    r = client.get("/api/research/scenario-backtest/tstb.ns").json()
    assert r["status"] == "ok" and len(r["origins"]) == 8
    seen = []
    monkeypatch.setattr(jobs, "submit", lambda sym, force=False, **kw: seen.append((sym, force)) or "computing")
    assert client.post("/api/research/scenario-backtest", json={"symbol": "tcs", "force": True}).json() == {"symbol": "TCS.NS", "status": "computing"}
    assert seen == [("TCS.NS", True)]
    import pandas as pd

    pd.DataFrame({"status": ["ok", "ok", "failed"]}).to_parquet(data.CACHE_DIR / "summary.parquet")
    u = client.get("/api/research/scenario-backtest/universe/summary").json()
    assert u["symbols"] == 3 and u["by_status"] == {"ok": 2, "failed": 1}


def test_pipeline_hook_respects_flags(monkeypatch):
    from types import SimpleNamespace

    from modules.equity_research.intelligence import pipeline

    calls = []
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: calls.append(a))
    snap = SimpleNamespace(tables=bank(), info={"sector": "Financial Services"}, is_financial=True, view="consolidated",
                           target=SimpleNamespace(symbol="TSTB.NS"))
    for k, v in (("ARIA_FORECAST", "0"), ("ARIA_SCENARIO_BACKTEST", "0")):
        monkeypatch.setenv("ARIA_FORECAST", "1")
        monkeypatch.setenv("ARIA_SCENARIO_BACKTEST", "1")
        monkeypatch.setenv(k, v)
        pipeline._queue_scenario_backtest(snap)
        assert calls == []
    monkeypatch.setenv("ARIA_FORECAST", "1")
    monkeypatch.setenv("ARIA_SCENARIO_BACKTEST", "1")
    pipeline._queue_scenario_backtest(snap)
    assert calls[0][0] == "TSTB.NS" and calls[0][2]["is_financial"] is True


def test_sweep_summary_and_report(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import scenario_backtest_universe as sw
    from modules.equity_research.forecast.universe import UniverseEntry

    jobs.compute("TSTB.NS", bank(), META)
    ents = [UniverseEntry("TSTB", "TSTB.NS", "NSE", "Test Bank"), UniverseEntry("500325", "500325.BO", "BSE", "Bse Only")]
    state = {"meta": {}, "symbols": {"TSTB.NS": {"status": "ok", "seconds": 1.0}, "500325.BO": {"status": "no_screener_page", "reason": "404", "seconds": 0.5}}}
    df = sw.build_summary(ents, state)
    assert list(df.status) == ["ok", "no_screener_page"] and df.n_origins[0] == 8
    assert sw.already_done("TSTB.NS", state, "sb") and not sw.already_done("TSTB.NS", {"meta": {}, "symbols": {"TSTB.NS": {"status": "failed"}}}, "sb")
    text = sw.write_report(df, data.CACHE_DIR / "R.md", 2)
    assert "## Coverage" in text and "no_screener_page" in text and "## Limits" in text


def test_report_rendering_reasons_and_tables():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import pandas as pd

    import scenario_backtest_universe as sw

    cell = {"n_companies": 40, "base": {"bias": .05, "median_abs_e": .2, "smape_pct": 15.0, "bias_ci90": {"est": .05, "lo": .01, "hi": .09}},
            "band": {"below": .2, "inside": .5, "above": .3}, "nearest": {"bear": .3, "base": .4, "bull": .3},
            "skill": {"naive_rw": {"skill": .25}, "naive_cagr": {"skill": None}}}
    rows = sw._line_rows({1: cell, 2: {"suppressed": True, "n_companies": 7}}, False)
    assert "+0.050 [+0.010, +0.090]" in rows[0] and "20% / 50% / 30%" in rows[0] and "rw +0.25 ; cagr -" in rows[0][-1]
    assert rows[1] == [2, 7] + ["n<30"] * 6
    df = pd.DataFrame([{"status": "model_refused", "reason": None, "why": "share count is not available | x", "yahoo_symbol": "A.NS"},
                       {"status": "model_refused", "reason": None, "why": "share count is not available", "yahoo_symbol": "B.NS"}])
    text = sw.write_report(df, data.CACHE_DIR / "R2.md", 2)
    assert "| model_refused | share count is not available | 2 |" in text and "## How to read this" in text
