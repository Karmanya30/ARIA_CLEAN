"""Equity Forecast Validation Engine: sweep the whole NSE + BSE universe.

    python -X utf8 scripts/validate_universe.py --mode light [--limit N] [--exchange NSE|BSE|ALL] [--workers K]
                                                [--resume|--no-resume] [--priority nifty500-first|none]
                                                [--symbols-file F] [--timeout 300] [--refresh-universe]
    python -X utf8 scripts/validate_universe.py --status        # monitor a running/finished sweep
    python -X utf8 scripts/validate_universe.py --report-only   # rebuild summary.parquet + UNIVERSE_REPORT.md

Resumable: state lives in data/forecast_universe/sweep_state.json. No deep learning is used (CPU only).
--exchange BSE means BSE-only companies (a company on both exchanges is run once, on NSE).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from multiprocessing.connection import wait
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HORIZONS = [5, 21, 63]
MAX_STALE_DAYS = 30
FRESH_BDAYS = 5  # a completed run whose data cutoff is within this many business days is not redone on resume
DATA_FRESH_DAYS = 7  # data-unavailable verdicts are kept this long on resume
STATE_NAME = "sweep_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- worker (child process) -----------------------------------------------------------------------------------
def _reason(run) -> str | None:
    e = run.errors[0] if run.errors else ""
    if run.status == "data_unavailable" and "[" in e:
        return e.split("[", 1)[1].split("]", 1)[0]
    return e[:120] or None


def _work(sym: str, mode: str):
    from modules.equity_research.forecast import jobs, models

    t0 = time.perf_counter()
    try:
        run = jobs.run_inline(sym, models=models.zoo_for(mode), horizons=HORIZONS)
        return {"status": run.status, "reason": _reason(run), "run_id": run.run_id, "cache_key": run.cache_key,
                "seconds": round(time.perf_counter() - t0, 1)}
    except BaseException as e:  # never let one symbol end the worker
        return {"status": "failed", "reason": f"{type(e).__name__}: {str(e)[:100]}",
                "seconds": round(time.perf_counter() - t0, 1)}


def _worker(conn, mode: str) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C is handled by the parent
    import warnings

    from loguru import logger

    warnings.filterwarnings("ignore")  # sklearn feature-name chatter x thousands of fits
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    from modules.equity_research.forecast import data

    data.MAX_STALE_DAYS = MAX_STALE_DAYS
    while True:
        try:
            sym = conn.recv()
        except EOFError:
            return
        if sym is None:
            return
        conn.send(_work(sym, mode))


# -- state ----------------------------------------------------------------------------------------------------
def state_path() -> Path:
    from modules.equity_research.forecast.universe import UNIVERSE_DIR

    return UNIVERSE_DIR / STATE_NAME


def load_state(path: Path | None = None) -> dict:
    p = path or state_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"meta": {}, "symbols": {}}


def save_state(state: dict, path: Path | None = None) -> None:
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, p)


def already_done(sym: str, state: dict, mode: str) -> bool:
    """Resume rule: skip a symbol with a completed run (current engine versions, data cutoff within FRESH_BDAYS
    business days) from the same mode, or a data-unavailable verdict younger than DATA_FRESH_DAYS days.
    Failed and timed-out symbols are retried."""
    import numpy as np

    from modules.equity_research.forecast import jobs, store
    from modules.equity_research.forecast.contracts import FEATURE_VERSION, ZOO_VERSION

    rec = state["symbols"].get(sym)
    if rec and rec.get("mode") not in (None, mode):
        return False
    if rec and rec["status"] == "data_unavailable":
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(rec["ts"])).days
        return age < DATA_FRESH_DAYS
    if rec and rec["status"] not in ("ok_beats_baseline", "no_model_beats_baseline", "insufficient_evidence"):
        return False
    last = store.latest_completed(sym)
    if last is None or (last.feature_version, last.zoo_version) != (FEATURE_VERSION, ZOO_VERSION):
        return False
    try:
        return (last.cache_key == jobs._key(sym, last.training_cutoff)
                and np.busday_count(last.training_cutoff, str(np.datetime64("today"))) <= FRESH_BDAYS)
    except Exception:
        return False


# -- ordering -------------------------------------------------------------------------------------------------
def order(entries: list, priority: str) -> list:
    """Nifty 500 first, then by BSE traded value (liquidity proxy; NSE-only names have none and follow), then rest."""
    if priority != "nifty500-first":
        return list(entries)
    return sorted(entries, key=lambda e: (not e.nifty500, -(e.traded_value or 0.0), e.symbol))


def select(entries: list, exchange: str, limit: int | None, symbols: list[str] | None) -> list:
    if symbols:
        by = {e.yahoo_symbol: e for e in entries}
        from modules.equity_research.forecast.universe import UniverseEntry

        entries = [by.get(s) or UniverseEntry(symbol=s.split(".")[0], yahoo_symbol=s,
                                              exchange="BSE" if s.endswith(".BO") else "NSE", name=s)
                   for s in symbols]
    elif exchange != "ALL":
        entries = [e for e in entries if e.exchange == exchange]
    return entries[:limit] if limit else entries


# -- progress -------------------------------------------------------------------------------------------------
def fmt_eta(s: float) -> str:
    return f"{int(s // 3600)}h{int(s % 3600 // 60):02d}m"


def progress_line(done: int, total: int, t0: float, counts: Counter, secs: list[float]) -> str:
    el = time.time() - t0
    eta = el / done * (total - done) if done else 0
    rates = " ".join(f"{k}={100 * v / done:.0f}%" for k, v in counts.most_common())
    return (f"[{_now()}] {done}/{total} done, elapsed {fmt_eta(el)}, ETA {fmt_eta(eta)}, "
            f"mean {sum(secs) / max(len(secs), 1):.1f}s/symbol/worker | {dict(counts)} | {rates}")


# -- the sweep ------------------------------------------------------------------------------------------------
class Sweep:
    def __init__(self, todo: list, mode: str, workers: int, timeout: float, state: dict, skipped: int = 0,
                 worker=None):
        self.worker = worker or _worker
        self.todo, self.mode, self.timeout, self.state = list(todo), mode, timeout, state
        self.nworkers = max(1, min(workers, len(todo) or 1))
        self.skipped = skipped
        self.stop = False
        self.ctx = mp.get_context("spawn")
        self.slots: list[dict | None] = []

    def _spawn(self) -> dict:
        parent, child = self.ctx.Pipe()
        p = self.ctx.Process(target=self.worker, args=(child, self.mode), daemon=True)
        p.start()
        child.close()
        return {"proc": p, "conn": parent, "sym": None, "t": 0.0}

    def _kill(self, w: dict) -> None:
        try:
            w["proc"].kill()
            w["proc"].join(5)
        except Exception:
            pass
        try:
            w["conn"].close()
        except Exception:
            pass

    def _record(self, e, res: dict, counts: Counter, secs: list[float]) -> None:
        self.state["symbols"][e.yahoo_symbol] = {**res, "mode": self.mode, "ts": _now(), "exchange": e.exchange}
        counts[res["status"] if res["status"] != "data_unavailable" else (res.get("reason") or "bad_data")] += 1
        secs.append(res["seconds"])

    def run(self) -> Counter:
        from modules.equity_research.forecast import store

        total, t0 = len(self.todo), time.time()
        counts: Counter = Counter()
        secs: list[float] = []
        queue = list(reversed(self.todo))
        by_sym = {e.yahoo_symbol: e for e in self.todo}
        self.slots = [self._spawn() for _ in range(self.nworkers)]
        done = 0
        meta = self.state["meta"]
        meta.update(total=total + self.skipped, run_started=_now(), run_todo=total, mode=self.mode, pid=os.getpid(),
                    skipped_complete=self.skipped, running=True)
        old = signal.signal(signal.SIGINT, lambda *_: setattr(self, "stop", True))
        last_flush = 0
        try:
            while True:
                if self.stop and not any(w["sym"] for w in self.slots):
                    break
                for w in self.slots:
                    if w["sym"] is None and queue and not self.stop:
                        w["sym"], w["t"] = queue.pop().yahoo_symbol, time.time()
                        w["conn"].send(w["sym"])
                busy = [w for w in self.slots if w["sym"]]
                if not busy:
                    break
                ready = set(wait([w["conn"] for w in busy], timeout=1.0))
                for i, w in enumerate(self.slots):
                    if not w["sym"]:
                        continue
                    e, res = by_sym[w["sym"]], None
                    if w["conn"] in ready:
                        try:
                            res = w["conn"].recv()
                        except (EOFError, OSError):
                            res = {"status": "failed", "reason": "worker process died", "seconds": time.time() - w["t"]}
                            self._kill(w)
                            self.slots[i] = dict(self._spawn())
                    elif time.time() - w["t"] > self.timeout:
                        res = {"status": "timeout", "reason": f"exceeded {self.timeout:.0f}s", "seconds": self.timeout}
                        self._kill(w)
                        self.slots[i] = self._spawn()
                        try:  # the killed child left its run row 'computing'
                            row = store.latest_run(e.yahoo_symbol)
                            if row and row.status == "computing":
                                store.update_run(row.run_id, status="timeout", error=res["reason"])
                        except Exception:
                            pass
                    if res is None:
                        continue
                    w = self.slots[i]
                    w["sym"] = None
                    self._record(e, res, counts, secs)
                    done += 1
                    if done % 20 == 0:
                        print(progress_line(done, total, t0, counts, secs), flush=True)
                    if time.time() - last_flush > 15:
                        self.flush(done, total, counts, t0)
                        last_flush = time.time()
        finally:
            signal.signal(signal.SIGINT, old)
            for w in self.slots:
                try:
                    w["conn"].send(None)
                except Exception:
                    pass
                self._kill(w)
            meta["running"] = False
            self.flush(done, total, counts, t0)
        if done % 20:
            print(progress_line(done, total, t0, counts, secs), flush=True)
        return counts

    def flush(self, done: int, total: int, counts: Counter, t0: float) -> None:
        self.state["meta"].update(run_done=done, run_elapsed_s=round(time.time() - t0), updated=_now(),
                                  run_counts=dict(counts))
        save_state(self.state)


def run_sweep(entries: list, mode: str, workers: int, timeout: float, resume: bool, state: dict | None = None) -> Counter:
    state = state if state is not None else (load_state() if resume else {"meta": {}, "symbols": {}})
    todo = [e for e in entries if not (resume and already_done(e.yahoo_symbol, state, mode))]
    skipped = len(entries) - len(todo)
    print(f"sweep: {len(entries)} symbols, {skipped} already complete, {len(todo)} to run, "
          f"{min(workers, max(len(todo), 1))} workers, mode={mode}", flush=True)
    state["meta"]["universe_selected"] = [e.yahoo_symbol for e in entries]
    if not todo:
        save_state(state)
        return Counter()
    return Sweep(todo, mode, workers, timeout, state, skipped).run()


# -- summary + status -----------------------------------------------------------------------------------------
def write_outputs(entries: list, n_universe: int, state: dict | None = None):
    from modules.equity_research.forecast import store
    from modules.equity_research.forecast.universe import UNIVERSE_DIR, build_summary, write_report

    state = state or load_state()
    df = build_summary(entries, state["symbols"], store.latest_run)
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(UNIVERSE_DIR / "summary.parquet", index=False)
    meta = state.get("meta", {})
    note = (f"Generated {_now()} UTC. Mode `{meta.get('mode')}` (no deep learning), horizons {HORIZONS}. "
            f"Rows cover the {len(df)} symbols attempted so far.")
    write_report(df, n_universe, UNIVERSE_DIR / "UNIVERSE_REPORT.md", note)
    return df


def status() -> int:
    s = load_state()
    m, syms = s.get("meta", {}), s.get("symbols", {})
    if not syms:
        print("no sweep state yet")
        return 1
    c = Counter(v["status"] if v["status"] != "data_unavailable" else v.get("reason") or "bad_data"
                for v in syms.values())
    total, todo, run_done = m.get("total", len(syms)), m.get("run_todo", 0), m.get("run_done", 0)
    el = m.get("run_elapsed_s") or 0
    eta = fmt_eta(el / run_done * (todo - run_done)) if run_done and m.get("running") else "-"
    print(f"sweep mode={m.get('mode')} pid={m.get('pid')} running={m.get('running')} updated={m.get('updated')}")
    print(f"done {len(syms)}/{total}  (this run {run_done}/{todo}, elapsed {fmt_eta(el)}, ETA {eta})")
    print("by outcome: " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["light", "full"], default="light")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--exchange", choices=["NSE", "BSE", "ALL"], default="ALL")
    ap.add_argument("--workers", type=int, default=min(8, (os.cpu_count() or 2) // 2))
    ap.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--priority", default="nifty500-first", choices=["nifty500-first", "none"])
    ap.add_argument("--symbols-file")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        return status()
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "3")  # 6 workers x 3 threads fits 22 logical CPUs
    from modules.equity_research.forecast import universe

    full = universe.discover_universe(refresh=a.refresh_universe)
    n_nse = sum(e.exchange == "NSE" for e in full)
    n_both = sum(e.also_on == "BSE" for e in full)
    print(f"universe: {len(full)} companies (NSE-primary {n_nse}, of which also on BSE {n_both}; BSE-only {len(full) - n_nse})",
          flush=True)
    syms = [s.strip() for s in Path(a.symbols_file).read_text().split() if s.strip()] if a.symbols_file else None
    entries = select(order(full, a.priority), a.exchange, a.limit, syms)
    if not a.report_only:
        run_sweep(entries, a.mode, a.workers, a.timeout, a.resume)
    state = load_state()
    sel = [e for e in full if e.yahoo_symbol in state["symbols"]] or entries
    df = write_outputs(sel, len(full), state)
    print(f"summary: {len(df)} rows -> {universe.UNIVERSE_DIR / 'summary.parquet'}; report -> "
          f"{universe.UNIVERSE_DIR / 'UNIVERSE_REPORT.md'}")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
