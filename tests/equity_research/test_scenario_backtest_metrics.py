"""Hand-computed checks for scenario_backtest.metrics (no network) plus a pilot smoke run on the cached companies."""
import math

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.scenario_backtest import metrics as M
from modules.equity_research.scenario_backtest.engine import ORIGIN_COLUMNS, ROW_COLUMNS


def _frames(sym, rows, origin=None):
    """rows: (origin_fy, line, k, {case: forecast}, actual[, flags])."""
    out, orig = [], {}
    for r in rows:
        fy, line, k, cases, act = r[:5]
        for c, v in cases.items():
            out.append(dict(symbol=sym, origin_fy=fy, avail_date="", model="dcf", refused_reason="", line=line, k=k, case=c,
                            forecast=v, actual=act, flags=r[5] if len(r) > 5 else ""))
        orig.setdefault(fy, {c: math.nan for c in ORIGIN_COLUMNS} | dict(symbol=sym, origin_fy=fy, model="dcf", refused_reason="", sector="IT", size_bucket="large", flags="", **(origin or {})))
    return pd.DataFrame(out, columns=ROW_COLUMNS), pd.DataFrame(list(orig.values()), columns=ORIGIN_COLUMNS)


def _cell(f, o, line="revenue", k=1):
    return M.company_summary(f, o)["lines"][line]["k"][k]


def test_error_smape_and_bias():
    f, o = _frames("A", [("Mar 2020", "revenue", 1, {"bear": 90, "base": 110, "bull": 130}, 100)])
    c = _cell(f, o)
    assert c["base"]["bias"] == pytest.approx(math.log(1.1))
    assert c["base"]["smape_pct"] == pytest.approx(9.5238, abs=1e-3)  # 0.0952 as a percentage
    assert c["base"]["median_abs_e"] == pytest.approx(math.log(1.1))


def test_band_edges_and_nearest():
    rows = [("Mar 20", "revenue", 1, {"bear": 90, "base": 100, "bull": 110}, a) for a in (90,)]  # exactly on the edge: inside
    rows += [("Mar 21", "revenue", 1, {"bear": 90, "base": 100, "bull": 110}, 110),            # upper edge: inside
             ("Mar 22", "revenue", 1, {"bear": 90, "base": 100, "bull": 110}, 89.9),           # below
             ("Mar 23", "revenue", 1, {"bear": 90, "base": 100, "bull": 110}, 111)]            # above
    f, o = _frames("A", rows)
    b = _cell(f, o)["band"]
    assert (b["below"], b["inside"], b["above"]) == (.25, .5, .25)
    n = _cell(f, o)["nearest"]  # actuals 90, 110, 89.9, 111 -> bear, bull, bear, bull
    assert (n["bear"], n["base"], n["bull"]) == (.5, 0, .5)
    assert "68%" in b["reference"]


def test_skill_vs_random_walk():
    # base |e| = ln1.1 ; rw forecast 120 -> |e| = ln(1.2): skill = 1 - ln1.1/ln1.2
    f, o = _frames("A", [("Mar 20", "revenue", 1, {"bear": 90, "base": 110, "bull": 130, "naive_rw": 120, "naive_cagr": 100}, 100)])
    s = _cell(f, o)["skill"]
    assert s["naive_rw"]["skill"] == pytest.approx(1 - math.log(1.1) / math.log(1.2))
    assert s["naive_cagr"]["skill"] is None  # zero naive error -> undefined


def test_margin_in_pp_and_undefined_counted():
    f, o = _frames("A", [("Mar 20", "margin", 1, {"bear": .2, "base": .25, "bull": .3}, .24),
                         ("Mar 20", "ebitda", 1, {"bear": -5, "base": -4, "bull": 5}, 10),
                         ("Mar 20", "revenue", 1, {"base": 100}, 100)])
    s = M.company_summary(f, o)
    assert s["lines"]["margin"]["k"][1]["base"]["bias"] == pytest.approx(1.0)
    assert s["lines"]["ebitda"]["k"][1]["n_undefined"] == 1


def test_exclusions_and_fcf_indicative():
    f, o = _frames("A", [("Mar 20", "revenue", 1, {"base": 110}, 100, "span_excluded"),
                         ("Mar 21", "revenue", 1, {"base": 110}, math.nan),
                         ("Mar 22", "revenue", 1, {"base": 110}, 100, "structural_break"),
                         ("Mar 23", "fcf", 1, {"base": 110}, 100, "fcf_not_comparable")])
    s = M.company_summary(f, o)
    assert "revenue" not in s["lines"] and s["excluded"]["span_excluded"] == 1 and s["excluded"]["nan_actual"] == 1
    assert s["structural_break"]["n"] == 1 and s["lines"]["fcf"]["indicative"]


def test_bootstrap_determinism_and_company_ci():
    g = [np.array([float(i), i + 1.0]) for i in range(40)]
    a, b = M._boot(g), M._boot(g)
    assert a == b and a[1] < a[0] < a[2]
    f, o = _frames("A", [(f"Mar {y}", "revenue", 1, {"base": 100 + y}, 100) for y in range(6)])
    assert _cell(f, o)["base"]["bias_ci90"] is not None  # 6 origins >= 5
    assert _cell(*_frames("A", [(f"Mar {y}", "revenue", 1, {"base": 110}, 100) for y in range(4)]))["base"]["bias_ci90"] is None


def _universe(n, bias_pp=0.0, sector="IT"):
    fs, os_ = [], []
    for i in range(n):
        for y in range(3):
            a = 100.0
            f, o = _frames(f"S{i}", [(f"Mar {y}", "revenue", 3, {"bear": 90, "base": a * (1 + (.05 + bias_pp / 100 + 0.001 * i / n)) ** 3, "bull": 140, "naive_rw": a}, a * 1.05 ** 3)])
            f = pd.concat([f, _frames(f"S{i}", [(f"Mar {y}", "revenue", 3, {"naive_rw": a}, a * 1.05 ** 3)])[0].iloc[:0]])
            fs.append(f); os_.append(o.assign(sector=sector, g1=.1))
    return pd.concat(fs), pd.concat(os_)


def test_suppression_effective_n_and_recommendation():
    f, o = _universe(29, 5)
    assert M.aggregate(f, o)["lines"]["revenue"]["k"][3] == {"suppressed": True, "n_companies": 29, "reason": "fewer than 30 companies"}
    f, o = _universe(40, 5)
    agg = M.aggregate(f, o)
    c = agg["lines"]["revenue"]["k"][3]
    assert c["n_companies"] == 40 and c["n_obs"] == 120 and c["n_eff"] == pytest.approx(40)
    assert agg["growth"]["k"][3]["bias_pp"] == pytest.approx(5.0, abs=.1)
    rec = M.recommendations(agg, "IT")
    assert len(rec) == 2 and "wider than needed" in rec[1] and "exceeded realised growth by 5." in rec[0] and "n=40" in rec[0]
    assert M.recommendations(agg, "Banks") == []
    assert not any("growth" in r for r in M.recommendations(M.aggregate(*_universe(40, 1)), "IT"))  # |bias| < 2 pp


def test_price_block():
    o = pd.DataFrame([{c: math.nan for c in ORIGIN_COLUMNS} | dict(symbol="A", origin_fy="Mar 20", model="dcf", refused_reason="", p0=100, v_bear=80, v_base=150,
                                                                    v_bull=200, v_weighted=145, p_k1=130, tr_k1=.3)])
    p = M._price(o)
    assert p["valuation_gap_median"] == pytest.approx(math.log(1.5)) and p["caption"].startswith("Price convergence is not proof")
    assert p["k"][1]["converged_toward_base"] == 1.0 and p["k"][1]["price_in_bear_bull"] == 1.0
    assert p["implied_return_median"]["base"] == pytest.approx(.5)


@pytest.mark.skipif(not __import__("pathlib").Path("data/scenario_backtest/TCS.NS.parquet").exists(), reason="pilot cache absent")
def test_pilot_smoke(capsys):
    from modules.equity_research.scenario_backtest import engine
    fs, os_ = [], []
    for s in ("TCS.NS", "INFY.NS", "HDFCBANK.NS", "RELIANCE.NS"):
        f, o = engine.run_company(s)
        cs = M.company_summary(f, o)
        assert cs["status"] == "ok" and cs["lines"]
        fs.append(f); os_.append(o)
        print(s, {ln: v["k"][1]["base"]["bias"] for ln, v in cs["lines"].items() if 1 in v["k"]})
    agg = M.aggregate(pd.concat(fs), pd.concat(os_))
    assert agg["n_companies"] == 4 and agg["lines"]["revenue"]["k"][1]["suppressed"] and M.recommendations(agg) == []


def test_universe_ci_is_clustered_over_companies():
    """A company with many observations must not narrow the CI: 40 companies x 1 obs and x 25 identical obs give the same interval."""
    rng = np.random.default_rng(1)
    vals = (rng.random(40) < .3).astype(float)
    one = pd.DataFrame({"symbol": [f"S{i}" for i in range(40)], "x": vals})
    many = pd.concat([one] * 25, ignore_index=True)
    a, b = M._ci(one, "x", "mean"), M._ci(many, "x", "mean")
    assert a == pytest.approx(b) and a["hi"] - a["lo"] > 0.1  # pooled observations would shrink the width about 5x
