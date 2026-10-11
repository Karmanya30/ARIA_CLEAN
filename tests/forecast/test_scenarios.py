"""WP4 scenarios. All price paths here are SYNTHETIC (seeded random walks), never market data."""
import time

import numpy as np
import pandas as pd

from modules.equity_research.forecast import scenarios as sc
from modules.equity_research.forecast.contracts import ForecastOutput, HorizonResult, RunResult


def synthetic_px(n=15000, seed=7, drift=0.0004, vol=0.012):  # SYNTHETIC
    r = np.random.default_rng(seed).normal(drift, vol, n)
    return pd.DataFrame({"adj_close": 100 * np.exp(np.cumsum(r))}, index=pd.bdate_range("1970-01-01", periods=n))


def report(price, bear, base, bull):
    mk = lambda k, v: {"key": k, "value": v}  # noqa: E731
    return {"cover": {"price": price}, "scenarios": {"cases": [mk("bear", bear), mk("base", base), mk("bull", bull)]}}


def run(lo=-0.15, hi=0.15, status="ok_beats_baseline"):
    f = ForecastOutput(symbol="X", created_at="t", data_cutoff="d", horizon=126, target_date="d2", model="rw",
                       lower_return=lo, upper_return=hi, point_return=0.0, status="ok_beats_baseline")
    return RunResult(run_id="r", symbol="X", status=status, horizons=[HorizonResult(horizon=126, status="ok_beats_baseline", selected_model="rw")],
                     forecasts=[f])


def brute_dates(p):
    """O(n^2) reference: terciles from np.sort of strictly earlier states."""
    n = len(p)
    ret = np.full(n, np.nan)
    ret[252:] = p[252:] / p[:-252] - 1
    vol = pd.Series(np.log(p)).diff().rolling(63).std().to_numpy()

    def bucket(t, a):
        s = np.sort(a[252:t])
        m = len(s)
        return 0 if a[t] < s[m // 3] else (2 if a[t] >= s[(2 * m) // 3] else 1)

    today = (bucket(n - 1, ret), bucket(n - 1, vol))
    return [t for t in range(504, n - 252) if (bucket(t, ret), bucket(t, vol)) == today]


def test_analogue_dates_match_brute_force_and_do_not_peek():
    p = synthetic_px(1800)["adj_close"].to_numpy()
    got, why = sc._analogue_dates(p)
    assert why is None and got == brute_dates(p) and got
    assert max(got) <= len(p) - 1 - 252  # forward return known


def test_effective_n_and_event_by_hand():
    assert sc._effective_n([0, 1, 2, 300, 301, 700]) == 3.0
    fwd = np.array([-0.2, 0.0, 0.1, 0.3])
    assert sc._event("bull", fwd, 0.1) == 0.5 and sc._event("bear", fwd, 0.0) == 0.5
    assert sc._event("base", fwd, 0.05) == 0.5  # 0.0 and 0.1 are within 10pp


def test_full_run_fields_and_status_contradicted():
    px = synthetic_px()
    rep = report(100.0, 90.0, 110.0, 600.0)  # bull = +500% is far outside any history and the ML interval
    v = sc.validate_scenarios(rep, run(), px)
    assert [c.scenario for c in v.checks] == ["bear", "base", "bull"]
    bull = v.checks[2]
    assert bull.implied_return == 5.0 and bull.horizon_days == 252 and bull.horizon_is_assumption
    assert bull.ml_horizon_used == 126 and bull.ml_forecast.p_positive is None
    a = bull.analogue
    assert a.effective_n >= 10 and a.n_analogues >= a.effective_n and a.warning is None
    assert a.freq_at_least_target == 0.0 and a.p10_forward_return < a.median_forward_return < a.p90_forward_return
    assert bull.status == "contradicted"
    assert any("above the 90th percentile" in e for e in bull.evidence_against)
    assert any("126" in x for x in bull.limitations) and any("assumption" in x for x in bull.limitations)
    assert bull.hist_vol_252 > 0 and -1 < bull.hist_max_drawdown < 0


def test_status_consistent_and_stretched():
    px = synthetic_px()
    v = sc.validate_scenarios(report(100.0, 95.0, 100.0, 105.0), run(-0.5, 0.5), px)
    assert v.checks[1].status == "consistent" and v.checks[1].evidence_for
    # inside the analogue band but outside a narrow ML interval -> stretched
    s = sc.validate_scenarios(report(100.0, 95.0, 125.0, 126.0), run(-0.01, 0.01), px).checks[1]
    assert s.status == "stretched" and s.evidence_against


def test_run_none_and_px_none_are_insufficient_but_keep_numbers():
    rep = report(100.0, 80.0, 115.0, 140.0)
    for v in (sc.validate_scenarios(rep, None, None), sc.validate_scenarios(rep, run(), None).checks and
              sc.validate_scenarios(rep, None, synthetic_px(600))):
        for c, t in zip(v.checks, (80.0, 115.0, 140.0)):
            assert c.status == "insufficient_evidence" and c.fundamental_target == t and c.reference_price == 100.0
            assert c.implied_return == t / 100 - 1 and c.limitations
    # ML alone is enough to leave insufficient_evidence
    assert sc.validate_scenarios(rep, run(), None).checks[1].status == "consistent"


def test_failed_run_is_not_used():
    c = sc.validate_scenarios(report(100, 90, 110, 130), run(status="failed"), None).checks[1]
    assert c.ml_forecast is None and c.status == "insufficient_evidence"


def test_small_sample_warns_and_is_insufficient():
    px = synthetic_px(1400)
    c = sc.validate_scenarios(report(100, 90, 110, 130), None, px).checks[1]
    assert c.analogue is None or c.analogue.warning
    assert c.status == "insufficient_evidence"


def test_no_scenarios():
    v = sc.validate_scenarios({"scenarios": None}, None, None)
    assert v.checks == [] and v.notes


def test_deterministic_and_fast():
    px, rep, r = synthetic_px(5000), report(100.0, 80.0, 115.0, 160.0), run()
    a = sc.validate_scenarios(rep, r, px)
    t = time.perf_counter()
    b = sc.validate_scenarios(rep, r, px)
    assert time.perf_counter() - t < 0.1
    assert a == b
