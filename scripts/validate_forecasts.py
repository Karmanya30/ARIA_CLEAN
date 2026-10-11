"""Run the forecast validation engine from the command line.

    python scripts/validate_forecasts.py --symbols TCS.NS AAPL [--device cuda] [--force]
                                         [--models rw,ar,ridge,xgb] [--horizons 5,21]
Exit code is non-zero when any run failed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILED = ("failed", "timeout", "data_unavailable")


def _f(x, nd=4):
    return "-" if x is None else f"{x:.{nd}f}"


def report(run) -> None:
    from modules.equity_research.forecast import store

    print(f"\n=== {run.symbol}  status={run.status}  wall={_f(run.wall_seconds, 1)}s  device={run.device} ===")
    d = run.dataset
    if d:
        q = d.quality
        print(f"data: {d.first_bar}..{d.last_bar} ({d.n_bars} bars, {d.provider}); gaps={q.gaps} dup={q.duplicates} "
              f"zero_vol={q.zero_volume_days} outliers={q.outliers} splits={q.split_events} "
              f"split_consistent={q.split_consistency_ok}; warnings={q.warnings}")
    for h in run.horizons:
        print(f"\nhorizon {h.horizon}d: {h.status}  selected={h.selected_model}")
        print(f"  {'model':<12}{'MAE':>9}{'RMSE':>9}{'dirAcc':>8}{'cov90':>8}{'vs_rw%':>8}  {'CI(dMAE)':<22}{'n':>6}{'eff_n':>8}")
        for r in h.baseline_results + h.results:
            t, vs = r.test, r.vs_baseline
            ci = f"[{_f(vs.ci_low, 5)},{_f(vs.ci_high, 5)}]" if vs else "-"
            print(f"  {r.model:<12}{_f(t.mae, 5):>9}{_f(t.rmse, 5):>9}{_f(t.dir_acc, 3):>8}{_f(t.coverage_90, 3):>8}"
                  f"{_f(vs.mae_improvement_pct, 2) if vs else '-':>8}  {ci:<22}{t.n:>6}{t.effective_n:>8.0f}")
        for r in h.results:
            for w in r.regime_warnings:
                print(f"  regime warning ({r.model}): {w}")
    for f in run.forecasts:
        print(f"forecast {f.horizon}d by {f.model}: {_f(f.lower_price, 2)} / {_f(f.point_price, 2)} / "
              f"{_f(f.upper_price, 2)} {f.currency or ''} (p_up={_f(f.p_positive, 2)}) {f.warnings}")
    for e in run.errors:
        print(f"error: {e}")
    print(f"predictions: {store.predictions_path(run.run_id)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--device", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--models", default=None, help="comma list, e.g. rw,ar,ridge,xgb")
    ap.add_argument("--horizons", default=None, help="comma list, e.g. 5,21")
    a = ap.parse_args(argv)
    if a.device:
        os.environ["ARIA_FORECAST_DEVICE"] = a.device
    from modules.equity_research.forecast import jobs

    models = a.models.split(",") if a.models else None
    horizons = [int(x) for x in a.horizons.split(",")] if a.horizons else None
    bad = 0
    for sym in a.symbols:
        t0 = time.perf_counter()
        run = jobs.run_inline(sym, force=a.force, horizons=horizons, models=models)
        report(run)
        print(f"({time.perf_counter() - t0:.1f}s)")
        bad += run.status in FAILED
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
