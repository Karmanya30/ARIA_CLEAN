"""Owner: WP2. Purged walk-forward evaluation.

Segments: among the origins that have a target, the last TEST_BARS are 'test' and the VAL_BARS before them are
'validation'; anything earlier is training only. Model selection must use ONLY validation rows; reported
numbers come from test rows.

Per fold (refit every 63 origins for tabular models, 504 for DL (DL only at h in 5/21/63)), with `a` = first origin of the fold:
  * training rows: position i with i + h <= a - 1 - EMBARGO (the target of a training row never reaches the
    forecast period), expanding but capped to the last TRAIN_YEARS*252 rows, and at least MIN_TRAIN rows;
  * inner slice: the last 20% of those rows; the model used for calibration is fitted on the earlier rows,
    purged the same way against the inner slice. Hyper-parameters (3 configs, models.TUNE_GRID) are chosen on
    this slice ONLY, and only at refits that fall on a multiple of 252 origins (otherwise the last choice is
    reused); prediction intervals are split-conformal: prediction + empirical QUANTILES of the signed inner-slice
    residuals (works for every model incl. baselines; DL's own quantile heads are not used for intervals);
  * the final model is refit on all training rows and predicts the fold's origins.
Time cap: `max_seconds` is checked before every fold; when exceeded, NO rows are returned (meta["partial"]=True, meta["reason"]="timeout: incomplete evaluation"), so a
timed-out model can never contribute partial rows. Deterministic given `seed`. `meta` (optional dict, filled in place) carries fold
metadata (train bounds, last training target date, tuned params, scaler means) for audit and the leakage tests.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import models
from .contracts import EMBARGO, QUANTILES, TEST_BARS, TRAIN_YEARS, VAL_BARS, FeatureConfig, PredictionRow

MIN_TRAIN = 756
REFIT = {"dl": 504}  # others 63
TUNE_EVERY = 252
_QF = ("q05", "q10", "q25", "q50", "q75", "q90", "q95")


def _d(idx, i):
    v = idx[i]
    return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)


def _predict_at(fitted, X, pos):
    """Predict for positions `pos` (ascending) giving the model up to 59 prior rows of context."""
    c0 = max(0, int(pos[0]) - (models.SEQ_LEN - 1))
    return models.predict(fitted, X.iloc[c0:int(pos[-1]) + 1])[np.asarray(pos) - c0]


def walk_forward(X: pd.DataFrame, y: pd.Series, h: int, model_name: str, cfg: FeatureConfig | None,
                 *, max_seconds: float | None = 90, segments: tuple[int, int] = (VAL_BARS, TEST_BARS),
                 px: pd.Series | None = None, seed: int = 0, params: dict | None = None,
                 meta: dict | None = None) -> list[PredictionRow]:
    """Rows for validation then test origins. `params` fixes the model parameters (disables tuning).
    `px` (price at origin, aligned on the index) fills price_origin, NaN if omitted. See module docstring."""
    meta = meta if meta is not None else {}
    meta.update(folds=[], partial=False, reason=None)
    entry = models.ZOO.get(model_name)
    if entry is None:
        meta["reason"] = "unknown_model"
        return []
    if not models.horizon_ok(model_name, h):
        meta["reason"] = f"horizon {h} not run for deep-learning models (only {models.DL_HORIZONS})"
        return []
    n, yv, idx = len(X), np.asarray(y, float), X.index
    if n < entry.min_bars:
        meta["reason"] = "too_few_bars"
        return []
    ok = np.flatnonzero(np.isfinite(yv))
    nv, nt = segments
    if len(ok) < nv + nt + MIN_TRAIN:
        meta["reason"] = "too_few_bars"
        return []
    segs = (("validation", ok[-nt - nv:-nt]), ("test", ok[-nt:]))
    step = REFIT.get(entry.family, 63)
    grid = models.TUNE_GRID.get(model_name) if params is None else None
    best = dict(params or entry.params)
    base_gap = {"gap": h + EMBARGO}
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0, rows, fold, done = time.monotonic(), [], 0, 0

    for seg, origins in segs:
        for c in range(0, len(origins), step):
            if max_seconds is not None and time.monotonic() - t0 > max_seconds:
                # incomplete evaluation must never reach metrics/selection: drop the rows, keep the count
                meta.update(partial=True, reason="timeout: incomplete evaluation", rows_dropped=len(rows))
                return []
            blk = origins[c:c + step]
            a = int(blk[0])
            tr = ok[ok + h <= a - 1 - EMBARGO][-TRAIN_YEARS * 252:]
            if len(tr) < MIN_TRAIN:
                meta.update(reason="insufficient_training")
                return []
            ni = max(1, int(0.2 * len(tr)))
            inner = tr[-ni:]
            core = tr[:-ni][tr[:-ni] + h <= int(inner[0]) - 1 - EMBARGO]
            Xc, yc = X.iloc[core], pd.Series(yv[core])
            tuned = grid is not None and done % TUNE_EVERY == 0
            cal = None
            if tuned:
                scored = []
                for g in grid:
                    m = models.fit(model_name, Xc, yc, seed, cfg, {**g, **base_gap})
                    scored.append((float(np.mean(np.abs(yv[inner] - _predict_at(m, X, inner)))), g, m))
                _, best, cal = min(scored, key=lambda s: s[0])
            if cal is None:
                cal = models.fit(model_name, Xc, yc, seed, cfg, {**best, **base_gap})
            resid = yv[inner] - _predict_at(cal, X, inner)
            qres = np.quantile(resid, QUANTILES)
            # DL: the calibration net (trained on the earlier 80%) also forecasts, halving the cost of a refit
            final = cal if entry.family == "dl" else models.fit(model_name, X.iloc[tr], pd.Series(yv[tr]), seed, cfg, {**best, **base_gap})
            pred = _predict_at(final, X, blk)
            sc = getattr(final.state, "named_steps", {}).get("scaler")
            meta["folds"].append(dict(
                fold=fold, segment=seg, test_start_pos=a, test_start=_d(idx, a), train_n=len(tr),
                train_first_pos=int(tr[0]), train_last_pos=int(tr[-1]),
                train_last_target_pos=int(tr[-1]) + h, train_last_target_date=_d(idx, int(tr[-1]) + h),
                inner_last_target_pos=int(inner[-1]) + h, core_last_target_pos=int(core[-1]) + h,
                inner_first_pos=int(inner[0]), tuned=tuned, params=dict(best),
                scaler_mean=None if sc is None else sc.mean_.copy()))
            for i, p in zip(blk, pred):
                i = int(i)
                qd = {f: float(p + q) for f, q in zip(_QF, qres)}
                rows.append(PredictionRow(
                    origin_date=_d(idx, i), target_date=_d(idx, i + h), horizon=h, model=model_name,
                    model_version=entry.version, fold=fold, segment=seg, y_true=float(yv[i]), y_pred=float(p),
                    price_origin=float(px.iloc[i]) if px is not None else float("nan"),
                    oos=True, created_at=created, **qd))
            fold += 1
            done += len(blk)
    return rows
