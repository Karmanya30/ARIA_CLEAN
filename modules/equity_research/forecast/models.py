"""Owner: WP2. Model zoo.

Every model predicts the forward h-bar LOG return from a feature row. fit() only ever sees the rows the
caller hands it (the walk-forward passes purged training rows), and ALL preprocessing (imputation, scaling,
Spearman top-k selection, early-stopping split) is fitted inside fit(), never on future or test data.

Column conventions the classical/baseline models rely on (the feature builder must provide them):
  * lag columns `lag_<k>` / `ret_lag_<k>`: the 1-bar log return k-1 bars before the origin (lag_1 = the return
    ending at the origin). `ar` and `garch` use them; if absent `ar` degrades to hist_mean and garch to no vol.
  * `ma_gap_21` (or `ma_gap_20`): log(close / MA21). `ma` predicts log(MA21/close) = -ma_gap, i.e. full
    reversion of the gap to the 21-bar moving average; with no such column it predicts 0 (= rw).
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.stats import rankdata
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .contracts import MIN_BARS, MIN_BARS_DL, QUANTILES, ZOO_VERSION, FeatureConfig, ModelSpec

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None
try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover - guarded: model skipped and recorded in SKIPPED
    lgb = None

SEQ_LEN = 60
N_JOBS = max(1, (os.cpu_count() or 2) - 2)


class ZooEntry(ModelSpec):
    """ModelSpec plus callables: fit(X, y, seed, cfg, params=None)->obj, predict(obj, X)->ndarray (n,)."""
    fit: Callable[..., Any] | None = None
    predict: Callable[..., Any] | None = None
    min_bars: int = 0


ZOO: dict[str, ZooEntry] = {}  # populated below; includes baseline 'rw' (zero log return)
SKIPPED: dict[str, str] = {}   # model name -> reason it is not in ZOO (e.g. lightgbm not installed)

# 3 configs per tuned model, tuned only on the walk-forward's inner slice; middle entry = default.
TUNE_GRID: dict[str, list[dict]] = {
    "ridge": [{"alpha": 10.0}, {"alpha": 300.0}, {"alpha": 10000.0}],
    "rf": [{"min_samples_leaf": 10}, {"min_samples_leaf": 30}, {"min_samples_leaf": 100}],
    "xgb": [{"reg_lambda": 1.0}, {"reg_lambda": 30.0}, {"reg_lambda": 300.0}],
    "lgbm": [{"min_child_samples": 20}, {"min_child_samples": 50}, {"min_child_samples": 200}],
}
DL_DEFAULT = {"hidden": 32, "epochs": 20, "patience": 4, "batch": 512, "lr": 1e-3}
DL_HORIZONS = (5, 21, 63)  # DL is too slow/noisy for h=1 and h=126; walk_forward skips them with a recorded reason


@dataclass
class Fitted:
    name: str
    state: Any


# ---------------------------------------------------------------- baselines
def _fit_rw(X, y, seed, cfg, params=None): return {}
def _pred_rw(s, X): return np.zeros(len(X))
def _fit_mean(X, y, seed, cfg, params=None): return {"mu": float(np.nanmean(y))}
def _pred_const(s, X): return np.full(len(X), s["mu"])
def _fit_drift(X, y, seed, cfg, params=None): return {"mu": float(np.nanmean(np.asarray(y, float)[-252:]))}


def _fit_ma(X, y, seed, cfg, params=None):
    return {"col": next((c for c in ("ma_gap_21", "ma_gap_20") if c in X.columns), None)}


def _pred_ma(s, X):
    if s["col"] is None:
        return np.zeros(len(X))
    return -np.nan_to_num(X[s["col"]].to_numpy(float))


# ---------------------------------------------------------------- classical
def _lag_cols(X, max_lag=None):
    found = []
    for c in X.columns:
        m = re.fullmatch(r"(?:ret_)?lag_?(\d+)", str(c), re.I)
        if m and (max_lag is None or int(m.group(1)) <= max_lag):
            found.append((int(m.group(1)), c))
    return [c for _, c in sorted(found)]


def _fit_ar(X, y, seed, cfg, params=None):
    """OLS on the lag-return columns; order p (nested first-p lags, p<=10) chosen by AIC on the training window."""
    cols = _lag_cols(X, 10)
    yv = np.asarray(y, float)
    L = X[cols].to_numpy(float) if cols else np.empty((len(X), 0))
    ok = np.isfinite(yv) & np.isfinite(L).all(axis=1)
    L, yv = L[ok], yv[ok]
    best = (np.inf, 0, np.array([yv.mean()]))
    for p in range(len(cols) + 1):
        D = np.column_stack([np.ones(len(yv)), L[:, :p]])
        b = np.linalg.lstsq(D, yv, rcond=None)[0]
        rss = float(((yv - D @ b) ** 2).sum())
        aic = len(yv) * np.log(rss / len(yv) + 1e-300) + 2 * (p + 1)
        if aic < best[0]:
            best = (aic, p, b)
    return {"cols": cols[:best[1]], "b": best[2], "order": best[1]}


def _pred_ar(s, X):
    if not s["cols"]:
        return np.full(len(X), s["b"][0])
    return s["b"][0] + np.nan_to_num(X[s["cols"]].to_numpy(float)) @ s["b"][1:]


def garch_fit(r) -> dict:
    """Gaussian GARCH(1,1) MLE on mean-removed returns: s2_t = omega + alpha e_{t-1}^2 + beta s2_{t-1}.
    Returns omega, alpha, beta (original return units) and `s2_next`, the one-step-ahead variance."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    e = 100.0 * (r - r.mean())  # percent scale conditions the optimiser
    e2, v0 = e * e, e.var()

    def filt(p):
        w, a, b = p
        u = w + a * np.concatenate(([v0], e2[:-1]))
        return lfilter([1.0], [1.0, -b], u, zi=[b * v0])[0]

    def nll(p):
        if p[1] + p[2] >= 0.9995:
            return 1e10
        s2 = filt(p)
        return 0.5 * float(np.sum(np.log(s2) + e2 / s2))

    res = minimize(nll, [0.05 * v0, 0.08, 0.85], method="L-BFGS-B",
                   bounds=[(1e-6, 10 * v0), (1e-4, 0.5), (1e-4, 0.999)])
    w, a, b = res.x
    s2_next = w + a * e2[-1] + b * filt(res.x)[-1]
    return {"omega": w / 1e4, "alpha": a, "beta": b, "s2_next": s2_next / 1e4}


def garch_vol_forecast(fitted, h: int) -> float | None:
    """h-bar log-return volatility (sqrt of summed daily variance forecasts) from the end of the training window."""
    g = (fitted.state if hasattr(fitted, "state") else fitted).get("garch")
    if not g:
        return None
    pers, v, tot = g["alpha"] + g["beta"], g["s2_next"], 0.0
    for _ in range(h):
        tot += v
        v = g["omega"] + pers * v
    return float(np.sqrt(tot))


def _fit_garch(X, y, seed, cfg, params=None):
    cols = _lag_cols(X, 1)
    return {"mu": float(np.nanmean(y)), "garch": garch_fit(X[cols[0]].to_numpy(float)) if cols else None}


# ---------------------------------------------------------------- tabular ML (all preprocessing inside the training window)
class SpearmanTopK(BaseEstimator, TransformerMixin):
    """Keep the k columns with the largest |Spearman rho| with y (fitted on the training window only)."""

    def __init__(self, k: int = 20):
        self.k = k

    def fit(self, X, y):
        X = np.asarray(X, float)
        rx = rankdata(X, axis=0)
        ry = rankdata(np.asarray(y, float))
        rx, ry = rx - rx.mean(0), ry - ry.mean()
        rho = np.abs(rx.T @ ry / (np.sqrt((rx ** 2).sum(0) * (ry ** 2).sum()) + 1e-12))
        self.keep_ = np.sort(np.argsort(-rho)[:max(1, min(self.k, X.shape[1]))])
        return self

    def transform(self, X):
        return np.asarray(X, float)[:, self.keep_]


def _make_est(name, seed, p):
    if name == "ridge":
        return Ridge(alpha=p["alpha"])
    if name == "rf":
        return RandomForestRegressor(n_estimators=p.get("n_estimators", 200), max_depth=6, n_jobs=-2,
                                     random_state=seed, min_samples_leaf=p["min_samples_leaf"])
    if name == "xgb":
        return xgb.XGBRegressor(tree_method="hist", max_depth=4, learning_rate=0.05,
                                n_estimators=p.get("n_estimators", 300), early_stopping_rounds=30,
                                reg_lambda=p["reg_lambda"], random_state=seed, n_jobs=N_JOBS)
    return lgb.LGBMRegressor(num_leaves=15, max_depth=4, learning_rate=0.05, n_estimators=p.get("n_estimators", 300),
                             min_child_samples=p["min_child_samples"], random_state=seed, n_jobs=N_JOBS,
                             deterministic=True, force_row_wise=True, verbose=-1)


def _fit_ml(name, X, y, seed, cfg, params=None):
    """sklearn Pipeline(imputer -> scaler -> SpearmanTopK -> estimator). xgb/lgbm early-stop on the chronological
    15% tail of the given window (after a purge gap of params['gap'] rows)."""
    p = {**TUNE_GRID[name][1], **(params or {})}
    yv, Xv = np.asarray(y, float), X.to_numpy(float)
    n = len(yv)
    pre = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()),
                    ("topk", SpearmanTopK(k=max(1, min(20, n // 50))))]).fit(Xv, yv)
    Z, est = pre.transform(Xv), _make_est(name, seed, p)
    tail0 = int(0.85 * n)
    cut = tail0 - int(p.get("gap", 0))
    if name in ("xgb", "lgbm") and cut >= 100:
        ev = [(Z[tail0:], yv[tail0:])]
        if name == "xgb":
            est.fit(Z[:cut], yv[:cut], eval_set=ev, verbose=False)
        else:
            est.fit(Z[:cut], yv[:cut], eval_set=ev, callbacks=[lgb.early_stopping(30, verbose=False)])
    else:
        if name == "xgb":
            est.set_params(early_stopping_rounds=None)
        est.fit(Z, yv)
    return Pipeline(pre.steps + [("est", est)])


def _pred_ml(pipe, X): return np.asarray(pipe.predict(X.to_numpy(float)), float)


# ---------------------------------------------------------------- deep learning (PyTorch)
def _device():
    import torch
    cuda = os.environ.get("ARIA_FORECAST_DEVICE") == "cuda" and torch.cuda.is_available()
    return torch.device("cuda" if cuda else "cpu")


def _fit_dl(kind, X, y, seed, cfg, params=None):
    """One recurrent net per refit with one head per quantile in QUANTILES (pinball loss); point = median head.
    Sequence = the last SEQ_LEN feature rows ending at the origin (left-padded with the first row)."""
    import torch
    from torch import nn
    p = {**DL_DEFAULT, **(params or {})}
    torch.set_num_threads(max(1, (os.cpu_count() or 8) - 4))
    torch.manual_seed(seed)
    dev, rng = _device(), np.random.default_rng(seed)
    Xv = X.to_numpy(float)
    imp = SimpleImputer(strategy="median").fit(Xv)
    sc = StandardScaler().fit(imp.transform(Xv))
    Z = np.clip(sc.transform(imp.transform(Xv)), -10, 10).astype(np.float32)
    yv = np.asarray(y, float)
    ys = float(yv.std()) or 1.0
    yt = torch.tensor(yv / ys, dtype=torch.float32, device=dev)
    Zt, n, Fdim = torch.tensor(Z, device=dev), len(yv), Z.shape[1]
    qs = torch.tensor(QUANTILES, dtype=torch.float32, device=dev)

    class Net(nn.Module):
        def __init__(s):
            super().__init__()
            s.rnn = (nn.LSTM if kind == "lstm" else nn.GRU)(Fdim, p["hidden"], 1, batch_first=True)
            s.head = nn.Linear(p["hidden"], len(QUANTILES))

        def forward(s, x):
            return s.head(s.rnn(x)[0][:, -1])

    net = Net().to(dev)
    off = torch.arange(-SEQ_LEN + 1, 1, device=dev)

    def loss_fn(idx):
        d = yt[idx][:, None] - net(Zt[(idx[:, None] + off).clamp(min=0)])
        return torch.maximum(qs * d, (qs - 1) * d).mean()

    tail0 = int(0.85 * n)
    cut = tail0 - int(p.get("gap", 0))
    early = cut >= 200
    tr = np.arange(cut if early else n)
    va = torch.arange(tail0, n, device=dev)
    opt = torch.optim.Adam(net.parameters(), lr=p["lr"])
    best, best_state, bad = np.inf, copy.deepcopy(net.state_dict()), 0
    for _ in range(int(p["epochs"])):
        net.train()
        perm = rng.permutation(tr)
        for i in range(0, len(perm), p["batch"]):
            opt.zero_grad()
            loss_fn(torch.tensor(perm[i:i + p["batch"]], device=dev)).backward()
            opt.step()
        if not early:
            continue
        net.eval()
        with torch.no_grad():
            v = float(np.mean([float(loss_fn(va[i:i + 256])) for i in range(0, len(va), 256)]))
        if v < best - 1e-6:
            best, best_state, bad = v, copy.deepcopy(net.state_dict()), 0
        else:
            bad += 1
            if bad >= p["patience"]:
                break
    if early:
        net.load_state_dict(best_state)
    net.eval()
    return {"net": net, "imp": imp, "sc": sc, "ys": ys, "dev": dev}


def predict_quantiles(fitted, X) -> np.ndarray:
    """DL only: (n, len(QUANTILES)) forecasts of the forward log return. X must include up to SEQ_LEN-1 prior rows."""
    import torch
    s = fitted.state if hasattr(fitted, "state") else fitted
    Z = np.clip(s["sc"].transform(s["imp"].transform(X.to_numpy(float))), -10, 10).astype(np.float32)
    Zt = torch.tensor(Z, device=s["dev"])
    off = torch.arange(-SEQ_LEN + 1, 1, device=s["dev"])
    out = []
    with torch.no_grad():
        for i in range(0, len(Z), 1024):
            idx = torch.arange(i, min(i + 1024, len(Z)), device=s["dev"])
            out.append(s["net"](Zt[(idx[:, None] + off).clamp(min=0)]).cpu().numpy())
    return np.concatenate(out) * s["ys"]


def _pred_dl(s, X): return predict_quantiles(s, X)[:, QUANTILES.index(0.5)]


# ---------------------------------------------------------------- registry
def _reg(name, family, rank, fit_fn, pred_fn, ver, min_bars=MIN_BARS, params=None):
    ZOO[name] = ZooEntry(name=name, family=family, complexity_rank=rank, version=f"{ZOO_VERSION}.{ver}",
                         fit=fit_fn, predict=pred_fn, min_bars=min_bars, params=params or {})


_reg("rw", "baseline", 0, _fit_rw, _pred_rw, "rw1")
_reg("hist_mean", "baseline", 0, _fit_mean, _pred_const, "hm1")
_reg("drift", "baseline", 0, _fit_drift, _pred_const, "dr1")
_reg("ma", "baseline", 0, _fit_ma, _pred_ma, "ma1")
_reg("ar", "classical", 1, _fit_ar, _pred_ar, "ar1")
_reg("garch", "classical", 1, _fit_garch, _pred_const, "g1")  # point = training mean; volatility: garch_vol_forecast
_reg("ridge", "ml", 2, lambda *a, **k: _fit_ml("ridge", *a, **k), _pred_ml, "ri1", params=TUNE_GRID["ridge"][1])
_reg("rf", "ml", 3, lambda *a, **k: _fit_ml("rf", *a, **k), _pred_ml, "rf1", params=TUNE_GRID["rf"][1])
if xgb is not None:
    _reg("xgb", "ml", 4, lambda *a, **k: _fit_ml("xgb", *a, **k), _pred_ml, "xg1", params=TUNE_GRID["xgb"][1])
else:
    SKIPPED["xgb"] = "xgboost not installed"
if lgb is not None:
    _reg("lgbm", "ml", 4, lambda *a, **k: _fit_ml("lgbm", *a, **k), _pred_ml, "lg1", params=TUNE_GRID["lgbm"][1])
else:
    SKIPPED["lgbm"] = "lightgbm not installed"
for _k in ("lstm", "gru"):
    _reg(_k, "dl", 5, lambda *a, _k=_k, **k: _fit_dl(_k, *a, **k), _pred_dl, _k + "1", MIN_BARS_DL, DL_DEFAULT)


def fit(name: str, X: pd.DataFrame, y: pd.Series, seed: int, cfg: FeatureConfig | None,
        params: dict | None = None) -> Fitted:
    """Fit on exactly the rows given (the caller owns purging). `params` overrides the model defaults."""
    return Fitted(name, ZOO[name].fit(X, y, seed, cfg, params=params))


def predict(fitted: Fitted, X: pd.DataFrame) -> np.ndarray:
    """Point predictions of forward log return, shape (n,)."""
    return np.asarray(ZOO[fitted.name].predict(fitted.state, X), float)


LIGHT_ZOO = ("rw", "hist_mean", "drift", "ma", "ar", "garch", "ridge", "lgbm")


def zoo_for(mode: str) -> list[str]:
    """Model names for a run mode: 'light' (universe sweeps), 'full' (everything except DL), 'full_dl' (everything).
    Names missing from ZOO (e.g. lightgbm not installed) are dropped."""
    if mode not in ("light", "full", "full_dl"):
        raise ValueError(f"unknown zoo mode {mode!r}")
    return [k for k, v in ZOO.items() if (k in LIGHT_ZOO if mode == "light" else mode == "full_dl" or v.family != "dl")]


def horizon_ok(name: str, h: int) -> bool:
    """False for DL models at horizons outside DL_HORIZONS."""
    return ZOO[name].family != "dl" or h in DL_HORIZONS


def available(n_bars: int) -> list[str]:
    """Model names usable for a history of n_bars (DL needs MIN_BARS_DL)."""
    return [k for k, v in ZOO.items() if n_bars >= v.min_bars]
