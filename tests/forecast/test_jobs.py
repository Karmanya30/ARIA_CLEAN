"""WP5: job queue, cancel/timeout, and run_inline against tiny deterministic fakes."""
import queue
import time

import numpy as np
import pandas as pd
import pytest

from modules.equity_research.forecast import backtest, data, features, jobs, metrics, models, regimes, selection, store
from modules.equity_research.forecast import contracts as c

N = 1400
IDX = pd.bdate_range("2020-01-01", periods=N)


def _df():
    rng = np.random.default_rng(0)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, N)))
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "adj_close": px, "volume": 1.0,
                         "dividends": 0.0, "splits": 0.0}, index=IDX)


def _meta(sym):
    return c.DatasetMeta(symbol=sym, market="IN", provider="fake", retrieved_at_utc="2026-01-01T00:00:00Z",
                         first_bar=str(IDX[0].date()), last_bar=str(IDX[-1].date()), n_bars=N, currency="INR")


@pytest.fixture
def fakes(tmpdb, monkeypatch):
    def walk(X, y, h, name, cfg, *, max_seconds=None, **kw):
        if name == "boom":
            raise RuntimeError("model blew up")
        yy = y.dropna().iloc[-500:]
        pred = 0.0 if name == "rw" else 0.001
        return [c.PredictionRow(origin_date=str(d.date()), target_date=str(d.date()), horizon=h, model=name, fold=0,
                                segment="validation" if i < 250 else "test", y_true=float(v), y_pred=pred,
                                price_origin=100.0) for i, (d, v) in enumerate(yy.items())]

    monkeypatch.setattr(data, "load_history", lambda s, force=False: (_df(), _meta(s)))
    monkeypatch.setattr(data, "load_benchmark", lambda s: _df()["adj_close"])
    monkeypatch.setattr(data, "sector_symbol", lambda s: None)
    monkeypatch.setattr(features, "build_features",
                        lambda px, b, s, cfg=None: pd.DataFrame({"f": np.arange(len(px))}, index=px.index))
    monkeypatch.setattr(features, "targets", lambda px, h: np.log(px["adj_close"].shift(-h) / px["adj_close"]))
    monkeypatch.setattr(regimes, "label_regimes", lambda px, b: pd.DataFrame({"bull_bear": "bull"}, index=px.index))
    monkeypatch.setattr(models, "ZOO", {})
    monkeypatch.setattr(models, "available", lambda n: ["rw", "fake", "boom"])
    monkeypatch.setattr(models, "zoo_for", lambda mode: ["rw", "fake", "boom"])
    monkeypatch.setattr(models, "fit", lambda name, X, y, seed, cfg: name)
    monkeypatch.setattr(models, "predict", lambda f, X: np.full(len(X), 0.0 if f == "rw" else 0.002))
    monkeypatch.setattr(backtest, "walk_forward", walk)
    monkeypatch.setattr(metrics, "metric_block",
                        lambda r, h=None: c.MetricBlock(n=len(r), effective_n=len(r) / 5,
                                                mae=float((r.y_true - r.y_pred).abs().mean()),
                                                mae_ret=0.0 if (r.y_pred != 0).any() else 1.0))  # the fake model beats the zero-forecast baseline on every segment
    monkeypatch.setattr(metrics, "block_bootstrap_ci",
                        lambda a, b, block, **kw: c.BaselineComparison(ci_low=-0.1, ci_high=0.1))
    monkeypatch.setattr(metrics, "trade_sim", lambda r, op=None, horizon=5, cost_bps=10.0: c.TradeSim())
    monkeypatch.setattr(selection, "select",
                        lambda ms, base: (ms[0].model, "ok_beats_baseline") if ms else (None, "insufficient_evidence"))


def test_run_inline_complete(fakes):
    run = jobs.run_inline("TCS.NS", horizons=[1, 5])
    assert run.status == "ok_beats_baseline" and run.progress == 100 and run.wall_seconds is not None
    assert run.cache_key and run.training_cutoff == str(IDX[-1].date()) and run.seeds
    assert [h.horizon for h in run.horizons] == [1, 5]
    h5 = run.horizons[1]
    assert h5.selected_model == "fake" and h5.baseline_results[0].model == "rw"
    assert h5.results[0].trade_sim is not None and h5.results[0].vs_baseline is not None
    assert "bull_bear:bull" in h5.results[0].regimes
    assert any("boom" in e and "RuntimeError" in e for e in run.errors)  # failure recorded, no message text
    assert "model blew up" not in " ".join(run.errors)
    f = run.forecasts[0]
    assert f.model == "fake" and f.lower_price < f.point_price < f.upper_price and f.p_positive is None
    assert f.target_date > f.data_cutoff and f.oos_validated
    assert store.load_predictions(run.run_id).model.isin(["rw", "fake"]).all()
    assert store.get_run(run.run_id).model_dump() == run.model_dump()


def test_run_inline_models_subset_and_data_unavailable(fakes, monkeypatch):
    run = jobs.run_inline("X", horizons=[1], models=["rw"])
    assert run.horizons[0].results == [] and run.horizons[0].status == "insufficient_evidence"
    calls = []

    def bad(s, force=False):
        calls.append(1)
        raise ConnectionError("net")

    monkeypatch.setattr(data, "load_history", bad)
    run = jobs.run_inline("X")
    assert run.status == "data_unavailable" and len(calls) == 2  # fetch retried once
    assert run.errors


# ---- queue behaviour -----------------------------------------------------
class FakeProc:
    """Stands in for the spawned child: alive for `life` seconds, then writes a finished row."""
    started: list = []
    active = 0
    peak = 0
    life = 0.3

    def __init__(self, run_id, symbol, exit_ok=True):
        self.run_id, self.symbol, self.exit_ok = run_id, symbol, exit_ok
        self.end = time.monotonic() + FakeProc.life
        self.terminated = False
        self.done = False
        self.exitcode = None
        FakeProc.started.append(symbol)
        FakeProc.active += 1
        FakeProc.peak = max(FakeProc.peak, FakeProc.active)

    def _finish(self):
        if not self.done:
            self.done = True
            FakeProc.active -= 1
            if self.exit_ok and not self.terminated:
                store.update_run(self.run_id, status="ok_beats_baseline", progress=100)
            self.exitcode = 0 if self.exit_ok else 1

    def is_alive(self):
        if self.terminated or time.monotonic() >= self.end:
            self._finish()
        return not self.done

    def join(self, timeout=None):
        time.sleep(min(timeout or 0.05, 0.05))

    def terminate(self):
        self.terminated = True
        self._finish()


@pytest.fixture
def queued(tmpdb, monkeypatch):
    FakeProc.started, FakeProc.active, FakeProc.peak, FakeProc.life = [], 0, 0, 0.3
    monkeypatch.setattr(jobs, "_last_bar", lambda s: "2026-01-02")
    monkeypatch.setattr(jobs, "_start", lambda rid, sym: FakeProc(rid, sym))
    jobs._cancelled.clear()
    yield
    jobs._queue.join()  # leave no job running into the next test


def wait(pred, t=10.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_cached_run_is_reused_force_requeues(queued, monkeypatch):
    monkeypatch.setattr(jobs, "_ensure_worker", lambda: None)  # keep rows queued, inspect the queue
    monkeypatch.setattr(jobs, "_queue", queue.Queue())  # a worker from an earlier test must not steal them
    a = jobs.submit("TCS.NS", "rep")
    assert jobs.status(a).status == "queued" and jobs._queue.qsize() == 1
    assert jobs.submit("TCS.NS") == a  # in flight with the same key: not queued twice
    assert jobs._queue.qsize() == 1
    store.update_run(a, status="ok_beats_baseline")
    assert jobs.submit("TCS.NS") == a and jobs._queue.qsize() == 1  # cached, no work
    monkeypatch.setattr(jobs, "_last_bar", lambda s: "2026-01-07")  # 3 trading days newer: still cached
    assert jobs.submit("TCS.NS") == a
    monkeypatch.setattr(jobs, "_last_bar", lambda s: "2026-02-02")  # a month newer: retrain
    b = jobs.submit("TCS.NS")
    assert b != a and jobs._queue.qsize() == 2
    monkeypatch.setattr(jobs, "_last_bar", lambda s: "2026-01-02")
    store.update_run(b, status="ok_beats_baseline")
    assert jobs.submit("TCS.NS", force=True) not in (a, b) and jobs._queue.qsize() == 3
    while not jobs._queue.empty():  # the fixture joins the queue on teardown
        jobs._queue.get_nowait()
        jobs._queue.task_done()


def test_fifo_one_at_a_time(queued):
    ids = [jobs.submit(s) for s in ("A", "B", "C")]
    assert wait(lambda: all(jobs.status(i).status == "ok_beats_baseline" for i in ids))
    assert FakeProc.started == ["A", "B", "C"] and FakeProc.peak == 1


def test_cancel_running_and_queued(queued):
    FakeProc.life = 30
    a, b = jobs.submit("A"), jobs.submit("B")
    assert wait(lambda: jobs.status(a).status == "computing")
    jobs.cancel(b)  # still queued: dies without ever starting
    assert jobs.status(b).status == "failed" and jobs.status(b).errors == ["cancelled"]
    jobs.cancel(a)
    assert wait(lambda: jobs.status(a).status == "failed")
    assert jobs.status(a).errors == ["cancelled"] and FakeProc.started == ["A"] and FakeProc.active == 0


def test_timeout_and_dead_child(queued, monkeypatch):
    FakeProc.life = 30
    monkeypatch.setattr(jobs, "JOB_TIMEOUT_S", 0.4)
    a = jobs.submit("A")
    assert wait(lambda: jobs.status(a).status == "timeout")
    assert "exceeded" in jobs.status(a).errors[0] and FakeProc.active == 0
    monkeypatch.setattr(jobs, "_start", lambda rid, sym: FakeProc(rid, sym, exit_ok=False))
    FakeProc.life = 0.05
    b = jobs.submit("B")
    assert wait(lambda: jobs.status(b).status == "failed")
    assert "code 1" in jobs.status(b).errors[0]


def test_status_unknown_raises(tmpdb):
    with pytest.raises(KeyError):
        jobs.status("nope")


def test_a_validation_win_not_confirmed_on_test_is_not_reported_as_a_win(fakes, monkeypatch):
    monkeypatch.setattr(metrics, "metric_block", lambda r, h=None: c.MetricBlock(n=len(r), effective_n=len(r) / 5, mae_ret=1.0))
    run = jobs.run_inline("TCS.NS", horizons=[5])
    h5 = run.horizons[0]
    assert h5.status == "no_model_beats_baseline" and h5.selected_model is None
    assert any("not confirmed" in n for n in h5.notes)
