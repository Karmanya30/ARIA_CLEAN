"""Owner: WP2. Model selection on validation only; test is never used to choose."""
from __future__ import annotations

import numpy as np

from .contracts import (BaselineComparison, HorizonModelResult, MetricBlock, PredictionRow)

MIN_N_EFF = 30


def _boot(err_m, err_b, block, n_boot=1000, seed=0, alpha=0.05) -> BaselineComparison:
    """Private moving-block bootstrap fallback used only while metrics.block_bootstrap_ci is a stub.
    CI of mean|err_m| - mean|err_b| (negative = model better)."""
    d = np.abs(np.asarray(err_m, float)) - np.abs(np.asarray(err_b, float))
    n, block = len(d), max(1, min(block, len(d)))
    rng = np.random.default_rng(seed)
    k = -(-n // block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, k))
    means = d[(starts[:, :, None] + np.arange(block)).reshape(n_boot, -1)[:, :n]].mean(1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    mb = float(np.mean(np.abs(err_b)))
    return BaselineComparison(mae_improvement_pct=float(-d.mean() / mb * 100) if mb else None,
                              ci_low=float(lo), ci_high=float(hi), significant=bool(hi < 0))


def validation_result(rows: list[PredictionRow], base_rows: list[PredictionRow], family: str = "ml",
                      seed: int = 0) -> HorizonModelResult:
    """Build the validation-only part of a HorizonModelResult (n, effective_n = n/h for h-overlapping targets,
    MAE, and the block-bootstrap CI vs rw). Uses metrics.block_bootstrap_ci, or the private fallback if still a stub."""
    v = [r for r in rows if r.segment == "validation"]
    b = {r.origin_date: r for r in base_rows if r.segment == "validation"}
    v = [r for r in v if r.origin_date in b]
    h = v[0].horizon
    em = np.array([r.y_true - r.y_pred for r in v])
    eb = np.array([b[r.origin_date].y_true - b[r.origin_date].y_pred for r in v])
    block = max(h, 5)
    try:
        from . import metrics
        cmp = metrics.block_bootstrap_ci(em, eb, block, seed=seed)
    except NotImplementedError:
        cmp = _boot(em, eb, block, seed=seed)
    return HorizonModelResult(horizon=h, model=v[0].model, family=family, vs_baseline=cmp,
                              validation=MetricBlock(n=len(v), effective_n=len(v) / h, mae=float(np.abs(em).mean())))


def select(horizon_models: list[HorizonModelResult], baseline: HorizonModelResult | None,
           timed_out: bool = False) -> tuple[str | None, str]:
    """(selected model name or None, status from contracts.STATUSES).

    A model wins only if the upper bound of its 95% block-bootstrap CI for (MAE_model - MAE_rw) on the VALIDATION
    segment (vs_baseline.ci_high) is < 0 and its validation effective n >= 30. Among winners whose CIs overlap the
    best winner's CI the simplest (lowest complexity_rank; ties -> larger improvement) is chosen. Test metrics are
    never read. `timed_out` only labels the outcome when nothing usable was produced."""
    from .models import ZOO
    cands = [m for m in horizon_models if m.vs_baseline is not None and m.vs_baseline.ci_high is not None
             and m.vs_baseline.ci_low is not None and m.validation.n > 0]
    if baseline is None or baseline.validation.n == 0 or not cands:
        return None, "timeout" if timed_out else ("data_unavailable" if not horizon_models else "failed")
    enough = [m for m in cands if m.validation.effective_n >= MIN_N_EFF]
    if not enough:
        return None, "insufficient_evidence"
    wins = [m for m in enough if m.vs_baseline.ci_high < 0]
    if not wins:
        return None, "no_model_beats_baseline"
    best = max(wins, key=lambda m: m.vs_baseline.mae_improvement_pct or 0.0)
    bl, bh = best.vs_baseline.ci_low, best.vs_baseline.ci_high
    close = [m for m in wins if m.vs_baseline.ci_low <= bh and m.vs_baseline.ci_high >= bl]
    pick = min(close, key=lambda m: (ZOO[m.model].complexity_rank if m.model in ZOO else 99,
                                     -(m.vs_baseline.mae_improvement_pct or 0.0)))
    return pick.model, "ok_beats_baseline"
