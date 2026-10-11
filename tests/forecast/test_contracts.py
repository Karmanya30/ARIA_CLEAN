import pytest

from modules.equity_research.forecast import contracts as c

NOW = "2026-01-02T00:00:00Z"
MB = c.MetricBlock(n=10, effective_n=8.0, mae=0.01, confusion={"tp": 1, "fp": 2, "tn": 3, "fn": 4})
FO = c.ForecastOutput(symbol="X", created_at=NOW, data_cutoff="2026-01-01", horizon=5, target_date="2026-01-08",
                      model="rw", status="ok_beats_baseline", point_return=0.01)
HMR = c.HorizonModelResult(horizon=5, model="rw", family="baseline", validation=MB, test=MB,
                           vs_baseline=c.BaselineComparison(ci_low=-0.1), regimes={"bull_bear:bull": MB},
                           trade_sim=c.TradeSim())
SAMPLES = [
    c.DataQuality(warnings=["w"]),
    c.DatasetMeta(symbol="X", market="IN", provider="yf", retrieved_at_utc=NOW, first_bar="2005-01-01",
                  last_bar="2026-01-01", n_bars=5000, benchmark_symbol="^NSEI"),
    c.FeatureConfig(), c.ModelSpec(name="rw", family="baseline"),
    c.PredictionRow(origin_date="2025-01-01", target_date="2025-01-08", horizon=5, model="rw", fold=0,
                    segment="test", y_true=0.01, y_pred=0.0, q50=0.0, price_origin=100.0),
    MB, c.BaselineComparison(), c.TradeSim(), HMR,
    c.HorizonResult(horizon=5, results=[HMR], baseline_results=[HMR]),
    FO, c.AnalogueEvidence(definition="d"),
    c.ScenarioCheck(scenario="bull", ml_forecast=FO, analogue=c.AnalogueEvidence(definition="d")),
    c.ScenarioValidation(checks=[c.ScenarioCheck(scenario="base")]),
    c.FundamentalCaseCheck(scenario="base"),
    c.FundamentalCheck(cases=[c.FundamentalCaseCheck(scenario="base")]),
    c.RunResult(run_id="r1", symbol="X", horizons=[c.HorizonResult(horizon=1)], forecasts=[FO]),
]


@pytest.mark.parametrize("m", SAMPLES, ids=lambda m: type(m).__name__)
def test_roundtrip_schema_extra(m):
    assert m.schema_version == "1"
    cls = type(m)
    assert cls.model_validate_json(m.model_dump_json()) == m
    d = m.model_dump()
    d["bogus_field"] = 1
    assert cls.model_validate(d) == m


def test_constants():
    assert (c.FEATURE_VERSION, c.ZOO_VERSION) == ("fv1", "z2")
    assert c.HORIZONS == (1, 5, 21, 63, 126)
    assert c.QUANTILES == (.05, .1, .25, .5, .75, .9, .95)
    assert (c.SCENARIO_HORIZON_DAYS, c.MIN_BARS, c.MIN_BARS_DL, c.VAL_BARS, c.TEST_BARS, c.EMBARGO, c.TRAIN_YEARS) \
        == (252, 1260, 2500, 1008, 504, 5, 15)
    assert len(c.STATUSES) == 9
    assert "cannot be measured retrospectively" in c.FundamentalCheck().retro_accuracy_note
