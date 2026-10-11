"""Owner: WP5. Background execution of forecast runs.

One daemon worker thread drains a FIFO queue; each job runs in a spawned child process so a hung
or memory-hungry model can be killed. The child writes progress to the run row; the API reads it.
"""
from __future__ import annotations

import hashlib
import multiprocessing as mp
import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from loguru import logger

from config.paths import DATA_DIR

from . import backtest, data, features, metrics, models, regimes, selection, store
from .contracts import (FEATURE_VERSION, HORIZONS, ZOO_VERSION, FeatureConfig, ForecastOutput, HorizonModelResult,
                        HorizonResult, RunResult)

JOB_TIMEOUT_S = 600
MODEL_CAP_S = 90.0
DL_CAP_S = 150.0
SEED = 42
STALE_TRADING_DAYS = 5  # a cached run is reused until the data is more than this many trading days newer

_queue: queue.Queue[str] = queue.Queue()
_cancelled: set[str] = set()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# -- cache key ----------------------------------------------------------
def _last_bar(symbol: str) -> str:
    """Date of the last completed daily bar: cached parquet if there is one, else a tiny 5-day fetch."""
    try:
        p = DATA_DIR / "forecast_cache" / f"{symbol}.parquet"
        if p.exists():
            return str(pd.read_parquet(p).index.max())[:10]
        import yfinance as yf
        return str(yf.Ticker(symbol).history(period="5d").index.max())[:10]
    except Exception:
        logger.warning(f"last bar for {symbol} unknown; using today")
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _key(symbol: str, cutoff: str) -> str:
    return hashlib.sha1(f"{symbol}|{FEATURE_VERSION}|{ZOO_VERSION}|{HORIZONS}|{cutoff}".encode()).hexdigest()


def _cached(symbol: str, key: str, cutoff: str) -> RunResult | None:
    last = store.latest_completed(symbol)
    if last is None or (last.feature_version, last.zoo_version) != (FEATURE_VERSION, ZOO_VERSION):
        return None
    if last.cache_key == key:
        return last
    try:
        if last.training_cutoff and np.busday_count(last.training_cutoff, cutoff) <= STALE_TRADING_DAYS:
            return last
    except ValueError:
        pass
    return None


# -- public API ---------------------------------------------------------
def submit(symbol: str, report_id: str | None = None, force: bool = False) -> str:
    """Queue a run (reusing a cached one unless force); returns run_id."""
    symbol = symbol.upper()
    cutoff = _last_bar(symbol)
    key = _key(symbol, cutoff)
    if not force:
        hit = _cached(symbol, key, cutoff)
        if hit:
            return hit.run_id
        cur = store.latest_run(symbol, key)
        if cur and cur.status in ("queued", "computing"):
            return cur.run_id
    run_id = uuid.uuid4().hex
    store.save_run(RunResult(run_id=run_id, symbol=symbol, status="queued", cache_key=key, training_cutoff=cutoff),
                   report_id)
    _queue.put(run_id)
    _ensure_worker()
    return run_id


def status(run_id: str) -> RunResult:
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    return run


def cancel(run_id: str) -> None:
    run = status(run_id)
    if run.status in ("queued", "computing"):
        _cancelled.add(run_id)
        if run.status == "queued":
            store.update_run(run_id, status="failed", error="cancelled", finished_at=_now())


# -- worker -------------------------------------------------------------
def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, name="forecast-worker", daemon=True)
            _worker.start()


def _drain() -> None:
    while True:
        run_id = _queue.get()
        try:
            if run_id not in _cancelled:
                _execute(run_id)
            _cancelled.discard(run_id)
        except Exception:
            logger.exception("forecast worker error")
            try:
                store.update_run(run_id, status="failed", error="worker error", finished_at=_now())
            except Exception:
                pass
        finally:
            _queue.task_done()


def _child(run_id: str, symbol: str) -> None:
    _run(symbol, run_id=run_id)


def _start(run_id: str, symbol: str):
    p = mp.get_context("spawn").Process(target=_child, args=(run_id, symbol), daemon=True)
    p.start()
    return p


def _execute(run_id: str) -> None:
    run = status(run_id)
    store.update_run(run_id, status="computing", progress=1, stage="starting", started_at=_now())
    proc = _start(run_id, run.symbol)
    t0 = time.monotonic()
    fail = None
    while proc.is_alive():
        proc.join(0.2)
        if run_id in _cancelled:
            fail = ("failed", "cancelled")
        elif time.monotonic() - t0 > JOB_TIMEOUT_S:
            fail = ("timeout", f"exceeded {JOB_TIMEOUT_S} s")
        if fail:
            proc.terminate()
            proc.join(5)
            break
    now = store.get_run(run_id)
    if fail:
        store.update_run(run_id, status=fail[0], error=fail[1], finished_at=_now())
    elif now and now.status in ("queued", "computing"):
        store.update_run(run_id, status="failed", error=f"worker exited with code {proc.exitcode}", finished_at=_now())


# -- the run itself -----------------------------------------------------
def _series(sym: str | None, loader) -> pd.Series | None:
    if not sym:
        return None
    try:
        s = loader(sym)
        return s["adj_close"] if isinstance(s, pd.DataFrame) else s
    except Exception:
        return None


def _frame(rows) -> pd.DataFrame:
    return pd.DataFrame([r.model_dump() for r in rows])


def _calibrated(test, rows_test: pd.DataFrame) -> bool:
    """Brier skill > 0 vs climatology, ECE <= 0.05, n >= 200."""
    if test.n < 200 or test.brier is None or test.ece is None or rows_test.empty:
        return False
    base = float((rows_test.y_true > 0).mean())
    return test.brier < base * (1 - base) and test.ece <= 0.05


def _forecast(sym, h, name, status_, df, X, y, cfg, rows, test_block, meta, cutoff) -> ForecastOutput:
    warns: list[str] = []
    if status_ != "ok_beats_baseline":
        warns.append("no validated model beats the random-walk baseline; this is the baseline forecast"
                     if name == "rw" else "evidence is insufficient to rely on this forecast")
    ytr = y.dropna()
    fitted = models.fit(name, X.loc[ytr.index], ytr, SEED, cfg)
    point = float(np.asarray(models.predict(fitted, X.iloc[[-1]]))[0])
    res = (rows.y_true - rows.y_pred).to_numpy()
    q = np.quantile(res, [0.05, 0.5, 0.95]) if len(res) else np.zeros(3)
    calibrated = _calibrated(test_block, rows[rows.segment == "test"])
    p_pos = float(((point + res) > 0).mean()) if len(res) and calibrated else None
    px = float(df["close"].iloc[-1])
    target = str(np.busday_offset(np.datetime64(cutoff), h, roll="forward"))
    return ForecastOutput(
        symbol=sym, exchange=meta.exchange, currency=meta.currency, created_at=_now(), data_cutoff=cutoff, horizon=h,
        target_date=target, model=name, point_return=point, median_return=point + float(q[1]),
        lower_return=point + float(q[0]), upper_return=point + float(q[2]), point_price=px * float(np.exp(point)),
        lower_price=px * float(np.exp(point + q[0])), upper_price=px * float(np.exp(point + q[2])),
        p_positive=p_pos, expected_vol=float(np.std(res)) if len(res) else None,
        oos_validated=status_ == "ok_beats_baseline", status=status_, warnings=warns)


def _horizon(sym, h, df, X, cfg, names, lab, prog, errors, all_rows, fam):
    y = features.targets(df, h)
    out: dict[str, tuple[HorizonModelResult, pd.DataFrame]] = {}
    dl_left = DL_CAP_S
    for name in names:
        is_dl = fam.get(name) == "dl"
        cap = dl_left if is_dl else MODEL_CAP_S
        if cap <= 0:
            errors.append(f"h{h} {name}: skipped, deep-learning time budget used up")
            continue
        if is_dl and not models.horizon_ok(name, h):
            continue  # deep learning only runs at the horizons it is budgeted for (models.DL_HORIZONS)
        t0 = time.perf_counter()
        wmeta: dict = {}
        try:
            rows = backtest.walk_forward(X, y, h, name, cfg, max_seconds=cap, px=df["adj_close"], meta=wmeta)
        except Exception as e:
            errors.append(f"h{h} {name}: {type(e).__name__}")
            logger.warning(f"h{h} {name} failed: {type(e).__name__}: {str(e)[:200]}")
            continue
        finally:
            if is_dl:
                dl_left -= time.perf_counter() - t0
        prog(f"h{h} {name}")
        if not rows:  # a timed-out model contributes nothing, not a partial result
            errors.append(f"h{h} {name}: " + (wmeta.get("reason") or "no out-of-sample rows"))
            continue
        all_rows.extend(rows)
        r = _frame(rows)
        val, test = r[r.segment == "validation"], r[r.segment == "test"]
        res = HorizonModelResult(horizon=h, model=name, family=fam.get(name, "ml"),
                                 validation=metrics.metric_block(val, h), test=metrics.metric_block(test, h))
        if lab is not None and not test.empty:
            j = test.assign(_d=pd.to_datetime(test.origin_date)).join(lab, on="_d")
            for dim in lab.columns:
                for label, g in j.groupby(dim):
                    blk = metrics.metric_block(g, h)
                    res.regimes[f"{dim}:{label}"] = blk
                    if blk.n < 30:
                        res.regime_warnings.append(f"{dim}:{label} has only {blk.n} test observations")
        if h == 5 and not test.empty:
            res.trade_sim = metrics.trade_sim(test, df["open"], horizon=h)
        out[name] = (res, r)
        logger.info(f"{sym} h{h} {name}: val_mae={res.validation.mae} test_mae={res.test.mae} "
                    f"cov90={res.test.coverage_90} {time.perf_counter() - t0:.1f}s")
    base = out.get("rw")
    if base is None:
        return HorizonResult(horizon=h, status="insufficient_evidence", notes=["baseline produced no rows"]), out
    bv = base[1][base[1].segment == "validation"][["origin_date", "y_pred"]]
    for name, (res, r) in out.items():
        if name == "rw":
            continue
        m = r[r.segment == "validation"].merge(bv, on="origin_date", suffixes=("", "_b"))
        if len(m):
            e_m, e_b = (m.y_true - m.y_pred).abs(), (m.y_true - m.y_pred_b).abs()
            res.vs_baseline = metrics.block_bootstrap_ci(e_m.to_numpy(), e_b.to_numpy(), max(h, 5), seed=SEED)
            res.vs_baseline.dm_p = metrics.dm_test(e_m.to_numpy(), e_b.to_numpy(), h)[1]
        mt = r[r.segment == "test"].merge(base[1][base[1].segment == "test"][["origin_date", "y_pred"]],
                                          on="origin_date", suffixes=("", "_b"))
        if len(mt) and res.vs_baseline is not None:
            res.vs_baseline.dm_p_test = metrics.dm_test((mt.y_true - mt.y_pred).to_numpy(),
                                                        (mt.y_true - mt.y_pred_b).to_numpy(), h)[1]
    cand = [v[0] for k, v in out.items() if k != "rw"]
    sel, st = selection.select([c for c in cand if c.family != "baseline"], base[0])  # the other baselines are comparators, never 'winners'
    notes = ["vs_baseline compares validation-segment absolute errors; test is held out of selection"]
    if sel:  # a validation win must also hold on the untouched test segment, otherwise it is reported as unconfirmed
        w = next(c for c in cand if c.model == sel)
        if w.test.mae_ret is None or base[0].test.mae_ret is None or w.test.mae_ret >= base[0].test.mae_ret:
            notes.append(f"{sel} beat the random walk on the validation segment but not on the untouched test segment, so the win is not confirmed.")
            sel, st = None, "no_model_beats_baseline"
    return HorizonResult(horizon=h, status=st, selected_model=sel, results=cand, baseline_results=[base[0]],
                         notes=notes), out


def _run(symbol: str, run_id: str | None = None, force: bool = False, horizons: list[int] | None = None,
         models_subset: list[str] | None = None) -> RunResult:
    t0 = time.perf_counter()
    symbol = symbol.upper()
    run_id = run_id or uuid.uuid4().hex
    horizons = horizons or list(HORIZONS)
    run = RunResult(run_id=run_id, symbol=symbol, status="computing", started_at=_now(),
                    device=os.getenv("ARIA_FORECAST_DEVICE", "cpu"), seeds={"global": SEED})
    prev = store.get_run(run_id)
    if prev:
        run.cache_key = prev.cache_key
    store.save_run(run)
    state = {"done": 0, "total": 1}

    def prog(stage: str, pct: int | None = None):
        if pct is None:
            state["done"] += 1
            pct = 10 + int(85 * state["done"] / state["total"])
        try:
            store.update_run(run_id, progress=min(pct, 95), stage=stage)
        except Exception:
            logger.warning("could not write progress")

    def finish(st: str) -> RunResult:
        run.status, run.progress, run.finished_at = st, 100, _now()
        run.wall_seconds = round(time.perf_counter() - t0, 2)
        store.save_run(run)
        logger.info(f"{symbol} run {run_id}: {st} in {run.wall_seconds}s, errors={len(run.errors)}")
        return run

    try:
        np.random.seed(SEED)
        prog("loading data", 3)
        try:
            try:
                df, meta = data.load_history(symbol, force=force)
            except Exception as e:
                if type(e).__name__ == "DataUnavailable":
                    raise
                logger.warning(f"{symbol}: fetch failed ({type(e).__name__}); retrying once")
                df, meta = data.load_history(symbol, force=force)
        except Exception as e:
            run.errors.append(f"data unavailable [{getattr(e, 'reason', 'bad_data')}]: {type(e).__name__}: {str(e)[:200]}")
            return finish("data_unavailable")
        run.dataset, run.training_cutoff = meta, meta.last_bar
        run.cache_key = run.cache_key or _key(symbol, meta.last_bar)
        run.limitations = list(meta.limitations)
        cfg = FeatureConfig()
        run.feature_config = cfg
        prog("building features", 6)
        bench = _series(symbol, data.load_benchmark)
        sector = _series(data.sector_symbol(symbol), lambda s: data.load_history(s)[0])
        X = features.build_features(df, bench, sector, cfg)
        lab = regimes.label_regimes(df, bench)
        fam = {k: v.family for k, v in getattr(models, "ZOO", {}).items()}
        wanted = set(models_subset) if models_subset else set(models.zoo_for(os.getenv("ARIA_FORECAST_MODE", "full")))  # full = every model except deep learning; full_dl adds LSTM/GRU
        names = [n for n in models.available(len(df)) if n in wanted or n == "rw"]
        if "rw" not in names:
            names.insert(0, "rw")
        state["total"] = max(1, len(horizons) * len(names))
        all_rows = []
        for h in horizons:
            hr, out = _horizon(symbol, h, df, X, cfg, names, lab, prog, run.errors, all_rows, fam)
            run.horizons.append(hr)
            run.regimes_summary[str(h)] = {n: v[0].regime_warnings for n, v in out.items() if v[0].regime_warnings}
            name = hr.selected_model or "rw"
            if name in out:
                try:
                    run.forecasts.append(_forecast(symbol, h, name, hr.status, df, X, features.targets(df, h), cfg,
                                                   out[name][1], out[name][0].test, meta, meta.last_bar))
                except Exception as e:
                    run.errors.append(f"h{h} forecast {name}: {type(e).__name__}")
                    logger.warning(f"h{h} forecast failed: {type(e).__name__}: {str(e)[:200]}")
        prog("saving predictions", 96)
        if all_rows:
            store.save_predictions(run_id, all_rows)
        sts = [x.status for x in run.horizons]
        return finish("ok_beats_baseline" if "ok_beats_baseline" in sts else
                      "no_model_beats_baseline" if "no_model_beats_baseline" in sts else "insufficient_evidence")
    except Exception as e:
        logger.exception(f"{symbol} run {run_id} failed")
        run.errors.append(f"{type(e).__name__}: {str(e)[:200]}")
        return finish("failed")


def run_inline(symbol: str, force: bool = False, horizons: list[int] | None = None,
               models: list[str] | None = None) -> RunResult:
    """Synchronous run (tests/CLI). Always computes (no cache lookup); `force` also bypasses the data cache."""
    return _run(symbol, force=force, horizons=horizons, models_subset=models)
