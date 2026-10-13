"""Scenario-backtest report section: states, trust tags, SVG, never raising."""
import pandas as pd

from modules.equity_research.intelligence.report_html import render_html  # noqa: F401
from modules.equity_research.scenario_backtest import report as R


def _frames(origins=("Mar 2022",), model="dcf"):
    rows = []
    for fy in origins:
        for k, a in ((1, 110.0), (2, 125.0)):
            for case, v in (("bear", 100.0), ("base", 112.0), ("bull", 120.0), ("naive_rw", 100.0)):
                rows.append(dict(symbol="X.NS", origin_fy=fy, avail_date="2022-06-29", model=model, refused_reason="", line="revenue", k=k,
                                 case=case, forecast=v * (1 + 0.1 * (k - 1)), actual=a, flags=""))
    o = pd.DataFrame({"origin_fy": list(origins), "refused_reason": [""] * len(origins)})
    return pd.DataFrame(rows), o


def _attach(monkeypatch, res):
    monkeypatch.setattr(R, "_result", lambda s: res)
    return R.attach({"cover": {"symbol": "X.NS"}})


def test_ok_section_with_one_origin(monkeypatch):
    f, o = _frames()
    rep = _attach(monkeypatch, (f, o, {"status": "ok"}))
    h, md = R.html_section(rep), R.md_section(rep)
    assert "Historical backtest of these scenarios" in h and "ACTUAL" in h and "CALCULATED" in h
    assert "<svg" in h and 'role="img"' in h and "<caption" in h
    assert "Price convergence is not proof" in h and "| Revenue" in md.replace("revenue", "Revenue")
    st = rep["scenario_backtest"]["stats"]
    assert st["n"] == 2 and st["in_band"] == 1.0


def test_degraded_states(monkeypatch):
    for res, text in (((pd.DataFrame(), pd.DataFrame(), {"status": "insufficient_history", "n_years": 2}), "2 fiscal years available; 3 needed"),
                      ((pd.DataFrame(), pd.DataFrame(), {"status": "model_refused", "reasons": []}), "refused at every origin"),
                      (None, "not been run")):
        h = R.html_section(_attach(monkeypatch, res))
        assert text in h.replace("Model refused", "model refused") or text in h


def test_missing_attach_is_silent():
    assert R.html_section({}) == "" and R.md_section({}) == ""


def test_metrics_block_drives_the_section_and_percentile(monkeypatch, tmp_path):
    f, o = _frames()
    cell = {"n_obs": 5, "base": {"median_abs_e": 0.1, "bias": 0.0}, "band": {"inside": .4}, "nearest": {"bear": .2, "base": .5, "bull": .3},
            "skill": {"naive_rw": {"skill": .25}, "naive_cagr": {"skill": -.1}}}
    m = {"model": "dcf", "sector": "IT", "lines": {"revenue": {"k": {"1": cell}}}, "growth": {"k": {"1": {"bias_pp": 2.5}}}}
    pq = pd.DataFrame({"yahoo_symbol": [f"S{i}" for i in range(40)], "m_sector": "IT", "m_medabs_e": [i / 100 for i in range(40)]})
    pq.to_parquet(tmp_path / "summary.parquet")
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path)
    rep = _attach(monkeypatch, (f, o, {"status": "ok", "metrics": m, "provider": "yfinance", "n_fiscal_years": 4}))
    h = R.html_section(rep)
    assert "40%" in h and "+0.25" in h and "-0.10" in h and "+2.5" in h and "20% / 50% / 30%" in h
    assert "yfinance fallback (4 fiscal years)" in h and "smaller than that of" in h and "sector" in h
    pq.iloc[:10].to_parquet(tmp_path / "summary.parquet")  # < 30 companies: no percentile
    assert "smaller than that of" not in R.html_section(_attach(monkeypatch, (f, o, {"status": "ok", "metrics": m})))
