import math

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.intelligence.comps import verdict
from modules.equity_research.scenario_backtest import data as sbd
from modules.equity_research.scenario_backtest import report_validation as rv


def _px(p0=1000.0, ph=1100.0, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=400)
    close = np.full(len(idx), p0)
    close[idx >= pd.Timestamp("2024-08-01")] = ph  # A=2024-06-29 -> +91d lands after this
    return pd.DataFrame({"close": close, "adj_close": close}, index=idx)


def _nifty(px, ret):
    n = pd.Series(100.0, index=px.index)
    n[n.index >= pd.Timestamp("2024-08-01")] = 100 * (1 + ret)
    return n


def test_hand_computed_example():
    px = _px()
    sig = dict(symbol="X.NS", avail_date="2024-06-29", tp=1200.0, rating="BUY", upside=0.2)
    r = [x for x in rv.compute_outcomes(sig, px, _nifty(px, 0.14)) if x["horizon_m"] == 3][0]
    assert r["forecast_return"] == pytest.approx(0.20)
    assert r["price_return"] == pytest.approx(0.10)
    assert r["tp_err_abs"] == pytest.approx(100 / 1100)  # 9.09%
    assert r["tp_err_signed"] == pytest.approx(100 / 1100)
    assert r["excess_return"] == pytest.approx(-0.04)  # 10% - 14%
    assert r["hit"] is False or r["hit"] == False  # noqa: E712  BUY with negative excess = miss


def test_hit_logic():
    px = _px()
    for rating, bench, hit in [("BUY", 0.05, True), ("SELL", 0.05, False), ("SELL", 0.14, True), ("HOLD", 0.08, True), ("HOLD", 0.20, False)]:
        sig = dict(symbol="X.NS", avail_date="2024-06-29", tp=1200.0, rating=rating, upside=0.2)
        r = [x for x in rv.compute_outcomes(sig, px, _nifty(px, bench)) if x["horizon_m"] == 3][0]
        assert bool(r["hit"]) is hit, (rating, bench)  # HOLD band at 3m is 5pp


def test_aria_rule_is_comps_verdict():
    assert verdict(0.30, "medium")[0] == "BUY" and verdict(0.29, "medium")[0] == "HOLD"
    assert verdict(-0.35, "medium")[0] == "SELL" and verdict(-0.34, "medium")[0] == "HOLD"


def test_leakage_poisoned_future_prices_do_not_change_signal():
    sym = next((s for s in rv.pilot_symbols() if sbd.cached(s)), None)
    if sym is None:
        pytest.skip("no cached company")
    tables, meta = sbd.load(sym)
    clean, _, _ = sbd.quality(tables, meta)
    px, nifty = rv.load_prices(sym, meta), rv.load_nifty()
    o = pd.read_parquet(rv.RESULTS / f"{sym}.origins.parquet")
    fy = o[o.refused_reason == ""].origin_fy.iloc[0]
    A = pd.Timestamp(o[o.origin_fy == fy].avail_date.iloc[0])
    a = rv.signal(sym, clean, meta, px, nifty, fy)
    bad, nbad = px.copy(), nifty.copy()
    bad.loc[bad.index > A + pd.Timedelta(days=10), ["close", "adj_close"]] *= 7.0
    nbad[nbad.index > A + pd.Timedelta(days=10)] *= 0.1
    b = rv.signal(sym, clean, meta, bad, nbad, fy)
    for k in ("tp", "rating", "tier", "upside", "p0"):
        assert (a[k] == b[k]) or (isinstance(a[k], float) and math.isnan(a[k]) and math.isnan(b[k])), k


def test_broker_csv(tmp_path):
    f = tmp_path / "b.csv"
    f.write_text("symbol,date,broker,rating,target,horizon\nNOPE,2020-01-01,A,BUY,10,12\nTCS,2020-01-01,A,WEIRD,10,12\n")
    b, notes = rv.broker_rows(f, rv.load_nifty())
    assert b.empty and len(notes) == 2
