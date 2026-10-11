"""WP6: the quantitative validation report section. All runs here are SYNTHETIC fixtures, not engine output."""
import copy
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "equity_research"))
from _intel_fixtures import good_llm, make_snapshot  # noqa: E402

from modules.equity_research.forecast import fundamentals, report as fr, scenarios, store  # noqa: E402
from modules.equity_research.forecast.contracts import (  # noqa: E402
    AnalogueEvidence, BaselineComparison, DatasetMeta, ForecastOutput, FundamentalCaseCheck, FundamentalCheck, HorizonModelResult,
    HorizonResult, MetricBlock, RunResult, ScenarioCheck, ScenarioValidation)
from modules.equity_research.intelligence import agents, pipeline as intel  # noqa: E402
from modules.equity_research.intelligence.data import Target  # noqa: E402
from modules.equity_research.intelligence.report import to_markdown  # noqa: E402
from modules.equity_research.intelligence.report_html import KINDS, render_html  # noqa: E402

TITLE = "Quantitative forecast validation"


@pytest.fixture(scope="module")
def rep():
    snap = make_snapshot("operating")
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(intel, "_persist", lambda user_id, report: None)
        mp.setattr(intel, "resolve_target", lambda q: Target("T", "T.NS", "T"))
        mp.setattr(intel, "gather", lambda t: snap)
        mp.setattr(agents, "generate_response", good_llm())
        return intel.run_research("report")["report"]
    finally:
        mp.undo()


def mb(mae, n=300):  # SYNTHETIC
    return MetricBlock(n=n, effective_n=n / 5, mae=mae, rmse=mae * 1.3, dir_acc=0.53, balanced_acc=0.52, coverage_90=0.88, mean_width_90=0.2, pinball=0.011)


def synth_run(status="ok_beats_baseline", **kw):  # SYNTHETIC
    hs = []
    for h in (5, 21):
        base = HorizonModelResult(horizon=h, model="rw", family="baseline", validation=mb(0.05), test=mb(0.05))
        m = HorizonModelResult(horizon=h, model="ridge", family="classical", validation=mb(0.047), test=mb(0.046),
                               vs_baseline=BaselineComparison(mae_improvement_pct=8.0, ci_low=-0.006, ci_high=-0.001, significant=True),
                               regimes={"bull_bear:bull": mb(0.04, 12), "bull_bear:bear": mb(0.05, 200)}, regime_warnings=["bear regime short"])
        hs.append(HorizonResult(horizon=h, status=status, selected_model="ridge", results=[m], baseline_results=[base]))
    fc = [ForecastOutput(symbol="T.NS", created_at="2026-01-01", data_cutoff="2026-01-01", horizon=21, target_date="2026-02-01", model="ridge",
                         point_return=0.0123, lower_return=-0.08, upper_return=0.09, point_price=101.5, lower_price=90.0, upper_price=110.0,
                         oos_validated=True, p_positive=None)]
    ds = DatasetMeta(symbol="T.NS", market="IN", provider="yfinance", retrieved_at_utc="2026-01-01T00:00:00Z", first_bar="2010-01-01", last_bar="2026-01-01",
                     n_bars=4000, currency="INR", exchange="NSE", benchmark_symbol="^NSEI", limitations=["Survivorship bias: x", "No point-in-time fundamentals"])
    return RunResult(run_id="r1", symbol="T.NS", status=status, progress=42, stage="training models", dataset=ds, horizons=hs, **{"forecasts": fc, **kw})


def preds(n=60):  # SYNTHETIC
    return [{"target_date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", "y_true": ((i % 7) - 3) / 100, "y_pred": 0.001 * (i % 5), "q05": -0.06, "q95": 0.06,
             "segment": "test"} for i in range(n)]


def with_qv(rep, run, **kw):
    r = dict(rep)
    r["quant_validation"] = {"run": run.model_dump(), "status": run.status, "scenarios": None, "fundamentals": None, "predictions": {}, **kw}
    return r


def test_no_run_shows_not_run_state_in_every_kind_but_dupont(rep):
    for kind in KINDS:
        html = render_html(rep, kind)
        if kind == "dupont":
            assert TITLE not in html
        else:
            assert TITLE in html and "No quantitative validation has been run for this company yet" in html


def test_section_precedes_verification_and_numbering_holds(rep):
    html = render_html(rep)
    assert html.index(TITLE) < html.index("Verification, sources and methodology")
    nums = [int(n) for n in re.findall(r'<section id="s\d+"><h2><span class="n">(\d+)</span>', html)]
    assert nums == list(range(1, len(nums) + 1))
    assert "Quantitative forecast validation</a>" in html


@pytest.mark.parametrize("status,needle", [
    ("computing", "42%"), ("queued", "Queued"), ("no_model_beats_baseline", "No model beat the simple baseline"),
    ("insufficient_evidence", "too short or the evidence too thin"), ("data_unavailable", "unavailable or too short"),
    ("failed", "boom"), ("timeout", "timed out")])
def test_status_banners(rep, status, needle):
    html = fr.html_section(with_qv(rep, synth_run(status, errors=["boom"] if status == "failed" else [])))
    assert needle in html
    assert "produced by code" in html and "not by the language model" in html


def test_ok_run_leaderboard_forecast_regime_and_disclaimers(rep):
    html = fr.html_section(with_qv(rep, synth_run(), predictions={"5": preds(), "21": preds()}))
    assert html.count("<details open>") == 2 and "Survivorship bias" in html and "^NSEI" in html
    assert "ridge" in html and ">rw" in html and "&#9733;" in html and "+8.0%" in html
    assert "not shown (uncalibrated)" in html  # p_positive is None
    assert "small sample" in html  # n=12 regime
    assert "Historical performance does not guarantee future performance" in html
    assert html.count('role="img"') == 4 and "<caption" in html


def test_no_charts_or_numbers_without_predictions(rep):
    html = fr.html_section(with_qv(rep, synth_run()))
    assert "<svg" not in html and "No predictions stored" in html


def test_empty_forecasts_state(rep):
    html = fr.html_section(with_qv(rep, synth_run("no_model_beats_baseline", forecasts=[])))
    assert "No forecast is offered" in html


def test_scenario_and_fundamental_tables(rep):
    ml = ForecastOutput(symbol="T.NS", created_at="x", data_cutoff="x", horizon=126, target_date="x", model="ridge", point_return=0.05,
                        lower_return=-0.2, upper_return=0.3, oos_validated=False)
    sv = ScenarioValidation(checks=[ScenarioCheck(
        scenario="bull", fundamental_target=150.0, implied_return=0.5, ml_horizon_used=126, ml_forecast=ml,
        analogue=AnalogueEvidence(definition="d", n_analogues=40, effective_n=8.0, freq_at_least_target=0.1, unconditional_freq=0.05),
        hist_vol_252=0.3, hist_max_drawdown=-0.4, evidence_for=["EVID_FOR"], evidence_against=["EVID_AGAINST"], limitations=["LIM"], status="stretched")])
    fc = FundamentalCheck(cases=[FundamentalCaseCheck(scenario="base", reproduced_value=101.0, reported_value=100.0, abs_diff_pct=1.0, ok=True, issues=["ISSUE"])],
                          assumption_flags=["AFLAG"], sensitivity_notes=["SNOTE"])
    html = fr.html_section(with_qv(rep, synth_run(), scenarios=sv.model_dump(), fundamentals=fc.model_dump()))
    for s in ("Bull", "150.00", "+50.0%", "assumed horizon", "at 126d", "not out-of-sample validated", "n=40", "stretched", "EVID_FOR", "EVID_AGAINST", "LIM",
              "ISSUE", "AFLAG", "SNOTE", "101.00", "cannot be measured retrospectively"):
        assert s in html, s


def test_markdown_section_and_export(rep):
    r = with_qv(rep, synth_run())
    md = fr.md_section(r)
    assert md.startswith("## Quantitative forecast validation") and "ridge" in md and "Historical performance does not guarantee" in md
    assert "## Quantitative forecast validation" in to_markdown(r)
    assert "## Quantitative forecast validation" not in to_markdown(rep)


def test_attach_survives_stub_errors_and_does_not_mutate(rep, monkeypatch):
    def boom(*a, **k):
        raise NotImplementedError

    for mod, fn in ((store, "latest_run"), (scenarios, "validate_scenarios"), (fundamentals, "check_fundamentals")):
        monkeypatch.setattr(mod, fn, boom)
    before = copy.deepcopy(rep)
    out = fr.attach(rep)
    assert rep == before and "quant_validation" not in rep
    q = out["quant_validation"]
    assert q["run"] is None and q["status"] == "not_run" and len(q["notes"]) == 2
    html = render_html(out)
    assert "No quantitative validation has been run" in html and "could not be computed" in html


def test_attach_with_run(rep, monkeypatch):
    monkeypatch.setattr(store, "latest_run", lambda s, cache_key=None: synth_run())
    monkeypatch.setattr(store, "predictions", lambda run_id, model, horizon: preds(), raising=False)
    monkeypatch.setattr(scenarios, "validate_scenarios", lambda *a: ScenarioValidation())
    monkeypatch.setattr(fundamentals, "check_fundamentals", lambda *a: FundamentalCheck())
    out = fr.attach(rep)
    assert out["quant_validation"]["status"] == "ok_beats_baseline" and set(out["quant_validation"]["predictions"]) == {"5", "21"}
    assert render_html(out).count("<svg") >= 4
