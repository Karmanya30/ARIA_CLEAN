"""Scenario backtest WP2: point-in-time snapshot, no look-ahead, origins and refusals."""
from __future__ import annotations

import copy
import math
from datetime import timedelta

import pandas as pd
import pytest

from modules.equity_research.scenario_backtest import data, engine
from tests.equity_research._intel_fixtures import bank_raw, daily_prices, operating_raw, tables_from_raw

PX, NIFTY = daily_prices()


def make(kind="op", **kw):
    raw = bank_raw(y0=2015, y1=2026, **kw) if kind == "bank" else operating_raw(y0=2015, y1=2026, **kw)
    meta = {"sector": "Financial Services" if kind == "bank" else "Technology", "industry": "Banks - Regional" if kind == "bank" else "IT Services",
            "is_financial": kind == "bank", "view": "consolidated", "symbol": "TST.NS"}
    clean, _, excl = data.quality(tables_from_raw(raw), meta)
    return clean, meta, excl


def run_all(kind="op", **kw):
    clean, meta, excl = make(kind, **kw)
    out = [engine.run_origin("TST.NS", clean, meta, PX, NIFTY, c, exclusions=excl) for c in engine.origin_years(clean, excl)]
    return clean, meta, excl, out


def test_snapshot_has_nothing_after_T():
    clean, meta, _ = make()
    snap = engine.as_of_snapshot(clean, meta, PX, NIFTY, "Mar 2020")
    A = engine.avail_date("Mar 2020")
    for t in ("pl", "bs", "cf", "ratios"):
        assert all(data.fye(c) <= data.fye("Mar 2020") for c in snap.tables[t]["cols"]) and "TTM" not in snap.tables[t]["cols"]
    assert snap.tables["pl"]["cols"][-1] == "Mar 2020"
    for c in snap.tables["quarterly"]["cols"]:
        assert data.fye(c) + timedelta(days=45) <= A
    assert "shp" not in snap.tables and snap.peers == [] and snap.news == [] and snap.documents == {} and snap.concall is None and snap.yf_statements is None
    assert snap.info["currentPrice"] == pytest.approx(float(PX["close"][PX.index >= pd.Timestamp(A)].iloc[0]))
    assert snap.info["sharesOutstanding"] == pytest.approx(snap.tables["pl"]["rows"]["Net Profit"]["Mar 2020"] / snap.tables["pl"]["rows"]["EPS in Rs"]["Mar 2020"] * 1e7)
    assert "totalCash" not in snap.info and snap.stock_returns and len(snap.stock_returns) <= 260


@pytest.mark.parametrize("kind", ["op", "bank"])
def test_leakage_poisoned_future_changes_nothing(kind):
    clean, meta, excl = make(kind)
    T = "Mar 2021"
    base_rows, base_origin = engine.run_origin("TST.NS", clean, meta, PX, NIFTY, T, exclusions=excl)
    d0 = PX.index[PX.index >= pd.Timestamp(engine.avail_date(T))][0]
    poisoned = copy.deepcopy(clean)
    for t, tb in poisoned.items():
        for r, vals in tb["rows"].items():
            for c in tb["cols"]:
                d = data._parse(c)
                later = d + timedelta(days=45) > engine.avail_date(T) if t == "quarterly" else d > data.fye(T)
                if d and later and vals.get(c) is not None:
                    vals[c] *= 1e6
    px2, nifty2 = PX.copy(), NIFTY.copy()
    px2.loc[px2.index > d0] *= 1e6
    nifty2.loc[nifty2.index > d0] *= 1e6
    rows2, origin2 = engine.run_origin("TST.NS", poisoned, meta, px2, nifty2, T, full=poisoned, exclusions=excl)

    def model_side(rows):  # the three cases, their derived paths and the naive baselines
        return [(r["line"], r["k"], r["case"], r["forecast"]) for r in rows]

    assert model_side(rows2) == model_side(base_rows)
    for key in ("v_bear", "v_base", "v_bull", "v_weighted", "g1", "margin", "wacc_or_coe", "tg", "p0", "mcap_cr"):
        assert origin2[key] == base_origin[key] or (math.isnan(origin2[key]) and math.isnan(base_origin[key]))
    assert any(r["actual"] != b["actual"] for r, b in zip(rows2, base_rows) if r["actual"] == r["actual"])  # the poison did reach the outcomes
    assert base_origin["v_bear"] < base_origin["v_base"] < base_origin["v_bull"]


def test_operating_origins_lines_and_actuals():
    clean, _, _, out = run_all("op")
    assert [o["origin_fy"] for _, o in out] == [f"Mar {y}" for y in range(2018, 2026)] and len(out) >= 6
    rows, origin = out[0]
    assert origin["model"] == "dcf" and not origin["refused_reason"] and origin["p0"] > 0 and origin["v_base"] > 0
    f = pd.DataFrame(rows)
    assert set(f.case) == {"bear", "base", "bull", "weighted", "naive_rw", "naive_cagr", "naive_mr"}
    assert set(f.line) == {"revenue", "ebitda", "margin", "fcf"}
    # base year is FY2018, so k=1 is FY2019 and the actual is the reported FY2019 sales
    sales = clean["pl"]["rows"]["Sales"]
    g = f[(f.line == "revenue") & (f.case == "base") & (f.k == 1)].iloc[0]
    assert g.actual == pytest.approx(sales["Mar 2019"]) and g.forecast == pytest.approx(sales["Mar 2018"] * (1 + origin["g1"]), rel=1e-9)
    # only the elapsed part has actuals: k=9 -> FY2027 (not reported), k=8 -> FY2026 (reported)
    assert math.isnan(f[(f.line == "revenue") & (f.case == "base") & (f.k == 9)].actual.iloc[0])
    assert f[(f.line == "revenue") & (f.case == "base") & (f.k == 8)].actual.iloc[0] == sales["Mar 2026"]
    assert f[f.line == "fcf"]["flags"].str.contains("fcf_not_comparable").all()
    nrw = f[(f.line == "revenue") & (f.case == "naive_rw") & (f.k == 3)].forecast.iloc[0]
    assert nrw == pytest.approx(sales["Mar 2018"])
    w = f[(f.line == "revenue") & (f.k == 2)].set_index("case").forecast
    assert w["weighted"] == pytest.approx(0.25 * w["bear"] + 0.5 * w["base"] + 0.25 * w["bull"])
    assert origin["p_k1"] > 0 and not math.isnan(origin["tr_k1"]) and not math.isnan(origin["p_k8"])
    assert origin["size_bucket"] in ("small", "mid", "large") and origin["sector"]


def test_bank_gets_ddm_path_with_eps_and_dps():
    clean, _, _, out = run_all("bank")
    assert len(out) >= 6
    rows, origin = out[0]
    assert origin["model"] == "ddm" and not origin["refused_reason"] and origin["v_bear"] < origin["v_base"] < origin["v_bull"]
    f = pd.DataFrame(rows)
    assert set(f.line) == {"eps", "dps"}
    eps = clean["pl"]["rows"]["EPS in Rs"]
    first = f[(f.line == "eps") & (f.case == "base") & (f.k == 1)].iloc[0]
    assert first.actual == pytest.approx(eps["Mar 2019"]) and first.forecast > eps["Mar 2018"]
    dps = f[(f.line == "dps") & (f.case == "base") & (f.k == 1)].iloc[0]
    assert dps.actual == pytest.approx(eps["Mar 2019"] * 0.25)


def test_loss_making_company_is_recorded_as_model_refusal():
    clean, meta, excl = make("op", opm=-0.10)
    rows, origin = engine.run_origin("TST.NS", clean, meta, PX, NIFTY, "Mar 2020", exclusions=excl)
    assert len(rows) == 1 and rows[0]["refused_reason"] and rows[0]["line"] is None and origin["refused_reason"] == rows[0]["refused_reason"]
    assert math.isnan(origin["v_base"]) and origin["p0"] > 0


def test_two_years_gives_no_origins_three_give_one_short_origin():
    clean, _, excl = data.quality(tables_from_raw(operating_raw(y0=2025, y1=2026)), {})
    assert excl["company"] == ["too_few_years"] and excl["n_years"] == 2
    clean, _, excl = data.quality(tables_from_raw(operating_raw(y0=2024, y1=2026)), {})
    assert excl["company"] == [] and engine.origin_years(clean, excl) == ["Mar 2025"]  # 2 years at T, FY2026 to score


def test_short_history_origin_runs_and_is_tagged():
    clean, _, excl = data.quality(tables_from_raw(operating_raw(y0=2022, y1=2026)), {})
    assert engine.origin_years(clean, excl) == ["Mar 2023", "Mar 2024", "Mar 2025"]
    r, o = engine.run_origin("TST.NS", clean, {"sector": "Technology", "industry": "IT Services"}, PX, NIFTY, "Mar 2024", exclusions=excl)
    assert o["n_years"] == 3 and "short_history" in o["flags"] and o["v_base"] > 0
    assert all("short_history" in x["flags"] for x in r if x["line"])
    r, o = engine.run_origin("TST.NS", clean, {"sector": "Technology", "industry": "IT Services"}, PX, NIFTY, "Mar 2025", exclusions=excl)
    assert o["n_years"] == 4 and "short_history" not in o["flags"]


def test_long_history_companies_get_no_short_origins():
    clean, _, excl = data.quality(tables_from_raw(operating_raw(y0=2015, y1=2026)), {})
    assert engine.origin_years(clean, excl)[0] == "Mar 2018"  # unchanged from sb1: 12 years > SHORT_MAX_COMPANY_YEARS


def test_gap_year_excludes_origins_whose_window_spans_it():
    raw = tables_from_raw(operating_raw(y0=2015, y1=2026))
    t = {k: {"cols": [c for c in v["cols"] if c != "Mar 2020"], "rows": {r: {c: x for c, x in vals.items() if c != "Mar 2020"} for r, vals in v["rows"].items()}} for k, v in raw.items()}
    clean, _, excl = data.quality(t, {})
    ys = engine.origin_years(clean, excl)
    assert ys == ["Mar 2018", "Mar 2019"]  # every later origin has the gap inside its five-year history window


def test_structural_break_is_scored_but_flagged():
    raw = tables_from_raw(operating_raw(y0=2015, y1=2026))
    for r in ("Sales", "Operating Profit", "Net Profit", "EPS in Rs"):
        raw["pl"]["rows"][r]["Mar 2022"] *= 2.0
    meta = {"sector": "Technology", "industry": "IT Services", "is_financial": False, "symbol": "TST.NS"}
    clean, _, excl = data.quality(raw, meta)
    rows, _ = engine.run_origin("TST.NS", clean, meta, PX, NIFTY, "Mar 2019", exclusions=excl)
    f = pd.DataFrame(rows)
    k3 = f[(f.line == "revenue") & (f.case == "base") & (f.k == 3)].iloc[0]
    assert "structural_break" in k3["flags"] and k3.actual == pytest.approx(clean["pl"]["rows"]["Sales"]["Mar 2022"])
    assert "structural_break" not in f[(f.line == "revenue") & (f.case == "base") & (f.k == 2)].iloc[0]["flags"]


def test_no_price_before_listing():
    clean, meta, excl = make()
    late = PX[PX.index >= "2019-06-01"]
    with pytest.raises(engine.NoOrigin):
        engine.run_origin("TST.NS", clean, meta, late, NIFTY, "Mar 2018", exclusions=excl)


def test_run_company_end_to_end_from_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    t = tables_from_raw(bank_raw(y0=2015, y1=2026))
    data.save_tables("TSTB.NS", t, {"sector": "Financial Services", "industry": "Banks - Regional", "is_financial": True})
    monkeypatch.setattr(data, "prices", lambda s, meta=None: PX)
    monkeypatch.setattr(engine, "fdata_nifty", lambda: NIFTY)
    f, o = engine.run_company("TSTB.NS")
    assert list(f.columns) == engine.ROW_COLUMNS and list(o.columns) == engine.ORIGIN_COLUMNS
    assert len(o) == 8 and f.attrs["status"] == "ok" and set(f.model) == {"ddm"}
    data.save_tables("SHORT.NS", tables_from_raw(operating_raw(y0=2025, y1=2026)), {"is_financial": False})
    f2, o2 = engine.run_company("SHORT.NS")
    assert f2.empty and o2.empty and f2.attrs["status"] == "insufficient_history"
    assert "2 fiscal years available (Mar 2025..Mar 2026); 3 needed" in f2.attrs["reason"] and f2.attrs["n_years"] == 2
