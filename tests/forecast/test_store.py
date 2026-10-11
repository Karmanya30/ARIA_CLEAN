"""WP5: run persistence (SQLite table + predictions parquet)."""
import subprocess
import sys
import textwrap

import pytest
from modules.equity_research.forecast import contracts as c
from modules.equity_research.forecast import store
from shared import user_store as us


def _run(**kw):
    base = dict(run_id="r1", symbol="TCS.NS", status="ok_beats_baseline", progress=100, cache_key="k",
                training_cutoff="2026-01-02", started_at="2026-01-03T00:00:00Z", finished_at="2026-01-03T00:01:00Z",
                forecasts=[c.ForecastOutput(symbol="TCS.NS", created_at="2026-01-03T00:00:00Z",
                                            data_cutoff="2026-01-02", horizon=5, target_date="2026-01-09",
                                            model="rw", point_return=0.01)])
    base.update(kw)
    return c.RunResult(**base)


def test_round_trip(tmpdb):
    run = _run()
    store.save_run(run, report_id="rep1")
    got = store.get_run("r1")
    assert got.model_dump() == run.model_dump()
    assert us.get_forecast_run("r1")["report_id"] == "rep1"
    assert store.get_run("nope") is None


def test_update_progress_and_full(tmpdb):
    store.save_run(_run(status="queued", progress=0))
    r = store.update_run("r1", status="computing", progress=40, stage="h5 ridge")
    assert (r.status, r.progress, r.stage) == ("computing", 40, "h5 ridge")
    assert r.forecasts  # the JSON body survives a progress-only update
    r = store.update_run("r1", limitations=["x"])
    assert r.limitations == ["x"] and r.progress == 40
    with pytest.raises(KeyError):
        store.update_run("zzz", limitations=["x"])


def test_latest_and_completed(tmpdb):
    store.save_run(_run(run_id="a", cache_key="k1"))
    store.save_run(_run(run_id="b", cache_key="k2", status="failed"))
    assert store.latest_run("TCS.NS").run_id == "b"
    assert store.latest_run("TCS.NS", "k1").run_id == "a"
    assert store.latest_run("OTHER") is None


def test_latest_completed_ignores_failed_newest(tmpdb):
    store.save_run(_run(run_id="a"))
    store.save_run(_run(run_id="b", status="failed"))
    # a newer failed row means "nothing cached": the caller re-queues
    assert store.latest_completed("TCS.NS") is None


def test_predictions_parquet(tmpdb):
    row = c.PredictionRow(origin_date="2026-01-01", target_date="2026-01-08", horizon=5, model="rw", fold=0,
                          segment="test", y_true=0.01, y_pred=0.0, price_origin=100.0)
    p = store.save_predictions("r1", [row])
    assert p == store.predictions_path("r1") and p.name == "predictions.parquet"
    assert len(store.load_predictions("r1")) == 1


def test_second_process_writes_do_not_lock(tmpdb):
    store.save_run(_run(status="computing", progress=0))
    code = textwrap.dedent("""
        import sys
        from shared import user_store as us
        for i in range(1, 51):
            us.update_forecast_run("r1", progress=i, stage="s%d" % i)
    """)
    env = {**__import__("os").environ, "DB_URL": f"sqlite:///{tmpdb.as_posix()}"}
    proc = subprocess.Popen([sys.executable, "-c", code], env=env)
    seen = 0
    while proc.poll() is None:  # read while the child writes
        seen = max(seen, store.get_run("r1").progress)
    assert proc.wait(timeout=60) == 0
    assert store.get_run("r1").progress == 50
