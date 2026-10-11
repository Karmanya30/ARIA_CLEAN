"""Typed contracts of the Equity Forecast Validation Engine (owner: WP0, frozen).

All dates/times are ISO-8601 strings (dates 'YYYY-MM-DD', timestamps UTC with 'Z' or offset).
Metrics that can be undefined are `float | None`. Unknown input fields are ignored.
Returns are forward LOG returns unless the field name says price.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FEATURE_VERSION = "fv1"
ZOO_VERSION = "z2"  # z2: only real models can be selected, and a validation win must hold on the untouched test segment
HORIZONS = (1, 5, 21, 63, 126)
QUANTILES = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
SCENARIO_HORIZON_DAYS = 252
MIN_BARS = 1260
MIN_BARS_DL = 2500
VAL_BARS = 1008
TEST_BARS = 504
EMBARGO = 5
TRAIN_YEARS = 15

Status = Literal["ok_beats_baseline", "no_model_beats_baseline", "insufficient_evidence",
                 "data_unavailable", "failed", "timeout", "computing", "queued", "not_run"]
STATUSES = ("ok_beats_baseline", "no_model_beats_baseline", "insufficient_evidence",
            "data_unavailable", "failed", "timeout", "computing", "queued", "not_run")
F = float | None


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str = "1"


class DataQuality(_M):
    gaps: int = 0
    duplicates: int = 0
    zero_volume_days: int = 0
    outliers: int = 0
    split_events: int = 0
    dividend_events: int = 0
    split_consistency_ok: bool = True
    warnings: list[str] = []


class DatasetMeta(_M):
    symbol: str
    market: Literal["IN", "US", "OTHER"]
    provider: str
    retrieved_at_utc: str
    first_bar: str
    last_bar: str
    n_bars: int
    currency: str | None = None
    exchange: str | None = None
    timezone: str | None = None
    frequency: str = "1d"
    benchmark_symbol: str | None = None
    benchmark_first_bar: str | None = None
    sector_symbol: str | None = None
    adjusted: bool = True
    price_basis: str = "adjusted close for returns, raw close for display"
    quality: DataQuality = DataQuality()
    limitations: list[str] = []


class FeatureConfig(_M):
    version: str = FEATURE_VERSION
    lags: list[int] = [1, 2, 3, 5, 10, 21]
    vol_windows: list[int] = [5, 21, 63]
    momentum_windows: list[int] = [5, 21, 63, 126, 252]
    ma_windows: list[int] = [10, 20, 50, 200]
    rsi: int = 14
    use_benchmark: bool = True
    use_sector: bool = True


class ModelSpec(_M):
    name: str
    family: Literal["baseline", "classical", "ml", "dl"]
    version: str = ZOO_VERSION
    complexity_rank: int = 0
    params: dict = {}


class PredictionRow(_M):
    origin_date: str
    target_date: str
    horizon: int
    model: str
    model_version: str = ZOO_VERSION
    fold: int
    segment: Literal["validation", "test"]
    y_true: float  # forward log return
    y_pred: float  # predicted forward log return
    q05: F = None
    q10: F = None
    q25: F = None
    q50: F = None
    q75: F = None
    q90: F = None
    q95: F = None
    price_origin: float
    oos: bool = True
    created_at: str | None = None


class MetricBlock(_M):
    n: int = 0
    effective_n: float = 0.0
    mae: F = None
    rmse: F = None
    mae_ret: F = None  # on log returns (the forecast target); mae/rmse above are on prices
    rmse_ret: F = None
    mape: F = None
    smape: F = None
    r2: F = None
    mape_excluded: int = 0
    dir_acc: F = None
    balanced_acc: F = None
    precision: F = None
    recall: F = None
    f1: F = None
    confusion: dict[str, int] = {}  # keys tp, fp, tn, fn
    brier: F = None
    ece: F = None
    coverage_90: F = None
    mean_width_90: F = None
    pinball: F = None
    crps_approx: F = None


class BaselineComparison(_M):
    baseline: Literal["rw"] = "rw"
    mae_improvement_pct: F = None  # positive = model better
    ci_low: F = None  # block-bootstrap CI of (MAE_model - MAE_baseline); negative = better
    ci_high: F = None
    significant: bool = False
    dm_p: F = None  # one-sided Diebold-Mariano p-value (model better than rw), validation segment
    dm_p_test: F = None  # same on the held-out test segment (never used for selection)


class TradeSim(_M):
    hypothetical: bool = True
    cumulative_return: F = None
    annual_return: F = None
    annual_vol: F = None
    sharpe: F = None
    sortino: F = None
    max_drawdown: F = None
    turnover: F = None
    cost_bps: F = None
    benchmark_cumulative_return: F = None
    n_trades: int = 0


class HorizonModelResult(_M):
    horizon: int
    model: str
    family: str
    validation: MetricBlock = MetricBlock()
    test: MetricBlock = MetricBlock()
    vs_baseline: BaselineComparison | None = None
    regimes: dict[str, MetricBlock] = {}  # key "<dimension>:<label>", e.g. "bull_bear:bull"
    regime_warnings: list[str] = []
    trade_sim: TradeSim | None = None


class HorizonResult(_M):
    horizon: int
    status: Status = "not_run"
    selected_model: str | None = None
    results: list[HorizonModelResult] = []
    baseline_results: list[HorizonModelResult] = []
    notes: list[str] = []


class ForecastOutput(_M):
    symbol: str
    exchange: str | None = None
    currency: str | None = None
    created_at: str
    data_cutoff: str
    horizon: int
    target_date: str
    model: str
    model_version: str = ZOO_VERSION
    point_return: F = None  # log return
    median_return: F = None
    lower_return: F = None  # q05
    upper_return: F = None  # q95
    point_price: F = None
    lower_price: F = None
    upper_price: F = None
    p_positive: F = None  # only when calibrated, else None
    expected_vol: F = None
    oos_validated: bool = False
    status: Status = "not_run"
    warnings: list[str] = []


class AnalogueEvidence(_M):
    definition: str
    n_analogues: int = 0
    effective_n: float = 0.0
    freq_at_least_target: F = None
    unconditional_freq: F = None
    median_forward_return: F = None
    p10_forward_return: F = None
    p90_forward_return: F = None
    warning: str | None = None


class ScenarioCheck(_M):
    scenario: Literal["bear", "base", "bull"]
    fundamental_target: F = None
    reference_price: F = None
    implied_return: F = None  # simple return target/ref - 1
    horizon_days: int = SCENARIO_HORIZON_DAYS
    horizon_is_assumption: bool = True
    ml_horizon_used: int | None = None
    ml_forecast: ForecastOutput | None = None
    analogue: AnalogueEvidence | None = None
    hist_vol_252: F = None
    hist_max_drawdown: F = None
    evidence_for: list[str] = []
    evidence_against: list[str] = []
    status: Literal["consistent", "stretched", "contradicted", "insufficient_evidence"] = "insufficient_evidence"
    limitations: list[str] = []


class ScenarioValidation(_M):
    checks: list[ScenarioCheck] = []
    notes: list[str] = []


class FundamentalCaseCheck(_M):
    scenario: str
    reproduced_value: F = None
    reported_value: F = None
    abs_diff_pct: F = None
    ok: bool | None = None
    issues: list[str] = []


RETRO_NOTE = ("ARIA's past forecasts are not available point-in-time; "
              "direct accuracy cannot be measured retrospectively.")


class FundamentalCheck(_M):
    cases: list[FundamentalCaseCheck] = []
    assumption_flags: list[str] = []
    sensitivity_notes: list[str] = []
    retro_accuracy_note: str = RETRO_NOTE
    notes: list[str] = []


class RunResult(_M):
    run_id: str
    symbol: str
    status: Status = "queued"
    progress: int = 0  # 0-100
    stage: str = ""
    cache_key: str | None = None
    feature_version: str = FEATURE_VERSION
    zoo_version: str = ZOO_VERSION
    training_cutoff: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    wall_seconds: F = None
    dataset: DatasetMeta | None = None
    feature_config: FeatureConfig | None = None
    horizons: list[HorizonResult] = []
    forecasts: list[ForecastOutput] = []
    regimes_summary: dict = {}
    limitations: list[str] = []
    errors: list[str] = []
    device: str = "cpu"
    seeds: dict = {}
