"""Scenario backtest WP1: cache round trip, restatement log, data-quality rules."""
from __future__ import annotations

from datetime import date

import pytest

from modules.equity_research.scenario_backtest import data
from tests.equity_research._intel_fixtures import bank_raw, operating_raw, tables_from_raw

META = {"sector": "Technology", "industry": "IT Services", "is_financial": False, "view": "consolidated"}


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)


def twelve():
    return tables_from_raw(operating_raw(y0=2015, y1=2026))


def drop_col(tables, col):
    return {t: {"cols": [c for c in tb["cols"] if c != col], "rows": {r: {c: v for c, v in vals.items() if c != col} for r, vals in tb["rows"].items()}}
            for t, tb in tables.items()}


def test_fye():
    assert data.fye("Mar 2026") == date(2026, 3, 31) and data.fye("Feb 2024") == date(2024, 2, 29)
    for bad in ("TTM", "", "Sep", "Foo 2020"):
        with pytest.raises(ValueError):
            data.fye(bad)


def test_round_trip_and_meta():
    t = twelve()
    meta = data.save_tables("T.NS", t, META)
    t2, m2 = data.load("T.NS")
    assert t2 == t
    assert m2["fiscal_years"][0] == "Mar 2015" and m2["fiscal_years"][-1] == "Mar 2026" and len(m2["sha1"]) == 40 and meta["sha1"] == m2["sha1"]
    assert m2["provider"] == "screener.in" and m2["columns"]["pl"][-1] == "TTM" and m2["retrieved_at_utc"]


def test_restatement_logged():
    t = twelve()
    data.save_tables("T.NS", t, META)
    t["pl"]["rows"]["Sales"]["Mar 2020"] *= 1.05  # 5% restated
    t["pl"]["rows"]["Sales"]["Mar 2021"] *= 1.005  # under tolerance
    m = data.save_tables("T.NS", t, META)
    (issue,) = [i for i in m["issues"] if i["reason"] == "restated"]
    assert issue["n"] == 1 and "Mar 2020" in issue["examples"][0]


def test_quality_clean_data():
    clean, issues, excl = data.quality(twelve(), META)
    assert clean["pl"]["cols"][-1] == "Mar 2026" and len(clean["pl"]["cols"]) == 12
    assert [i["reason"] for i in issues] == ["non_fy_column"]  # only TTM dropped
    assert excl == {"company": [], "spans": [], "flags": {}, "n_years": 12}


def test_half_year_column_dropped():
    t = twelve()
    for tb in (t["pl"],):
        tb["cols"] = tb["cols"][:-1] + ["Sep 2026", "TTM"][:1]
        for r in tb["rows"].values():
            r["Sep 2026"] = 1.0
    clean, issues, _ = data.quality(t, META)
    assert "Sep 2026" not in clean["pl"]["cols"] and clean["pl"]["cols"][-1] == "Mar 2026"
    assert any("Sep 2026" in i["detail"] for i in issues)


def test_gap_and_fy_change_spans():
    clean, issues, excl = data.quality(drop_col(twelve(), "Mar 2020"), META)
    assert [s["reason"] for s in excl["spans"]] == ["gap"] and excl["spans"][0]["start"] == date(2019, 3, 31) and excl["spans"][0]["end"] == date(2021, 3, 31)
    t = twelve()
    t["pl"]["cols"][5] = "Dec 2019"  # 9 months after Mar 2019?? -> Mar 2019 -> Dec 2019 -> Mar 2021 : irregular
    t["pl"]["rows"] = {r: {("Dec 2019" if c == "Mar 2020" else c): v for c, v in vals.items()} for r, vals in t["pl"]["rows"].items()}
    _, _, excl = data.quality(t, META)
    assert {s["reason"] for s in excl["spans"]} == {"fy_change"}


def test_structural_break_and_share_basis_flagged():
    raw = operating_raw(y0=2015, y1=2026)
    t = tables_from_raw(raw)
    for r in ("Sales", "Net Profit"):
        t["pl"]["rows"][r]["Mar 2024"] *= 2.0  # merger year: revenue +100% on top of growth
    t["pl"]["rows"]["EPS in Rs"]["Mar 2024"] *= 1.0
    _, issues, excl = data.quality(t, META)
    assert "structural_break" in excl["flags"]["Mar 2024"] and "share_basis" in excl["flags"]["Mar 2024"]  # NP doubled, EPS did not
    assert not excl["company"]


def test_too_few_years():
    _, issues, excl = data.quality(tables_from_raw(operating_raw(y0=2025, y1=2026)), META)
    assert excl["company"] == ["too_few_years"] and excl["n_years"] == 2
    assert any("2 fiscal years available (Mar 2025..Mar 2026); 3 needed" in i["detail"] for i in issues)
    _, _, ok3 = data.quality(tables_from_raw(operating_raw(y0=2024, y1=2026)), META)
    assert ok3["company"] == []  # 3 years: 2 to project from + 1 to score is enough


def test_bank_tables_survive_quality():
    clean, _, excl = data.quality(tables_from_raw(bank_raw(y0=2015, y1=2026)), {**META, "is_financial": True})
    assert "Deposits" in clean["bs"]["rows"] and not excl["spans"]


def test_prices_falls_back_to_cache_on_insufficient_history(monkeypatch, tmp_path):
    import pandas as pd

    from modules.equity_research.forecast import data as fdata

    monkeypatch.setattr(fdata, "CACHE_DIR", tmp_path)
    idx = pd.bdate_range("2024-01-01", periods=50)
    frame = pd.DataFrame({"close": 1.0, "adj_close": 1.0, "open": 1.0}, index=idx)
    frame.to_parquet(fdata._path("NEW.NS"))

    def boom(symbol, **kw):
        raise fdata.DataUnavailable("short", "insufficient_history")

    monkeypatch.setattr(fdata, "load_history", boom)
    assert list(data.prices("NEW.NS").columns) == ["close", "adj_close"]
    monkeypatch.setattr(fdata, "load_history", lambda s, **k: (_ for _ in ()).throw(fdata.DataUnavailable("x", "no_data")))
    with pytest.raises(fdata.DataUnavailable):
        data.prices("OTHER.NS")
