"""Owner: WP5. Run persistence (SQLite table forecast_runs + predictions parquet per run)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config.paths import DATA_DIR
from shared import user_store as us

from .contracts import PredictionRow, RunResult


def _dt(s: str | None):
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")


def _cols(run: RunResult) -> dict:
    return dict(symbol=run.symbol, market=run.dataset.market if run.dataset else None, status=run.status,
                progress=run.progress, stage=run.stage, cache_key=run.cache_key,
                feature_version=run.feature_version, zoo_version=run.zoo_version,
                training_cutoff=run.training_cutoff, started_at=_dt(run.started_at),
                finished_at=_dt(run.finished_at), error="; ".join(run.errors) or None,
                result_json=run.model_dump_json())


def _to_run(row: dict) -> RunResult:
    run = RunResult.model_validate_json(row["result_json"]) if row.get("result_json") else RunResult(
        run_id=row["id"], symbol=row["symbol"], cache_key=row["cache_key"],
        training_cutoff=row["training_cutoff"], errors=[row["error"]] if row["error"] else [])
    # the row's scalar columns are the live truth (the child updates them without rewriting the JSON)
    run.run_id, run.status, run.progress, run.stage = row["id"], row["status"], row["progress"] or 0, row["stage"] or ""
    run.started_at, run.finished_at = _iso(row["started_at"]) or run.started_at, _iso(row["finished_at"]) or run.finished_at
    if row["error"] and not run.errors:
        run.errors = [*run.errors, row["error"]]
    return run


def save_run(run: RunResult, report_id: str | None = None) -> None:
    fields = _cols(run)
    if report_id:
        fields["report_id"] = report_id
    if us.get_forecast_run(run.run_id):
        us.update_forecast_run(run.run_id, **fields)
    else:
        us.save_forecast_run(run.run_id, **fields)


def update_run(run_id: str, **fields) -> RunResult:
    """Merge fields into the stored run. Status/progress/stage-only updates skip the JSON rewrite."""
    if set(fields) <= {"status", "progress", "stage", "started_at", "finished_at", "error"}:
        cols = {k: (_dt(v) if k.endswith("_at") and isinstance(v, str) else v) for k, v in fields.items()}
        us.update_forecast_run(run_id, **cols)
    else:
        run = get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        save_run(run.model_copy(update=fields))
    run = get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    return run


def get_run(run_id: str) -> RunResult | None:
    row = us.get_forecast_run(run_id)
    return _to_run(row) if row else None


def latest_run(symbol: str, cache_key: str | None = None) -> RunResult | None:
    """Most recent run for symbol (matching cache_key if given)."""
    row = us.latest_forecast_run(symbol, cache_key)
    return _to_run(row) if row else None


def latest_completed(symbol: str, cache_key: str | None = None) -> RunResult | None:
    """Most recent finished run (any non-transient status except failed/timeout)."""
    row = us.latest_forecast_run(symbol, cache_key)
    # walk back only through the newest row: a newer queued/computing/failed row means "not cached"
    return _to_run(row) if row and row["status"] in _DONE else None


_DONE = ("ok_beats_baseline", "no_model_beats_baseline", "insufficient_evidence")


def report_id(run_id: str) -> str | None:
    row = us.get_forecast_run(run_id)
    return row["report_id"] if row else None


def predictions_path(run_id: str) -> Path:
    return DATA_DIR / "forecast_runs" / run_id / "predictions.parquet"


def save_predictions(run_id: str, rows: list[PredictionRow]) -> Path:
    p = predictions_path(run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([r.model_dump() for r in rows]).to_parquet(p, index=False)
    return p


def load_predictions(run_id: str) -> pd.DataFrame:
    return pd.read_parquet(predictions_path(run_id))


def predictions(run_id: str, model: str | None = None, horizon: int | None = None) -> list[dict]:
    """Stored out-of-sample rows of a run (all segments), optionally one model and horizon; [] when none are stored."""
    p = predictions_path(run_id)
    if not p.exists():
        return []
    df = pd.read_parquet(p)
    if model is not None:
        df = df[df["model"] == model]
    if horizon is not None:
        df = df[df["horizon"] == horizon]
    return df.to_dict("records")
