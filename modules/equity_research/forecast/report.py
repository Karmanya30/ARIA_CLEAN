"""Owner: WP6. Attach quant validation to reports and render it (HTML section, markdown section).

Every figure shown is read from RunResult / ScenarioValidation / FundamentalCheck / stored prediction rows;
nothing is defaulted. Missing data renders as "n/a" or as an explicit empty state, never as an invented number.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from html import escape

from . import fundamentals, scenarios, store
from .contracts import (EMBARGO, STATUSES, TEST_BARS, VAL_BARS, FundamentalCheck, HorizonModelResult, HorizonResult,
                        MetricBlock, RunResult, ScenarioValidation)

log = logging.getLogger(__name__)
CHART_HORIZONS = (5, 21)
OPEN_HORIZONS = (5, 21)
SMALL_N = 30  # display rule: regime slices with fewer observations are flagged as unreliable
MAX_ROWS = 1000
_LABEL = {
    "ok_beats_baseline": "Complete", "no_model_beats_baseline": "Complete: no model beat the baseline",
    "insufficient_evidence": "Insufficient evidence", "data_unavailable": "Data unavailable", "failed": "Failed",
    "timeout": "Timed out", "computing": "Computing", "queued": "Queued", "not_run": "Not run",
}


def _status_of(run: RunResult | None) -> str:
    return run.status if run is not None and run.status in STATUSES else "not_run"


def _cached_prices(symbol: str):
    """Cached price parquet only; never touches the network."""
    try:
        import pandas as pd
        from . import data
        p = data._path(symbol)
        return pd.read_parquet(p) if p.exists() else None
    except Exception:
        return None


def _predictions(run: RunResult) -> dict[str, list[dict]]:
    """Stored prediction rows of each selected model at the chart horizons, keyed by horizon. Empty if no store helper/rows."""
    fn = getattr(store, "predictions", None)
    out: dict[str, list[dict]] = {}
    if fn is None:
        return out
    for h in run.horizons:
        # the selected model if one beat the baseline; otherwise the best challenger by VALIDATION error (so the chart shows what the models actually did), else the baseline
        shown = h.selected_model or next(iter(sorted((m for m in h.results if m.validation.mae_ret is not None), key=lambda m: m.validation.mae_ret)), None)
        shown = h.selected_model or (shown.model if shown else (h.baseline_results[0].model if h.baseline_results else None))
        if h.horizon in CHART_HORIZONS and shown:
            try:
                rows = [r if isinstance(r, dict) else r.model_dump() for r in (fn(run.run_id, model=shown, horizon=h.horizon) or [])]
            except Exception as exc:  # noqa: BLE001
                log.info("predictions unavailable for h=%s: %s", h.horizon, exc)
                continue
            rows = [r for r in rows if r.get("y_true") is not None and r.get("y_pred") is not None and r.get("segment") == "test"]
            if rows:
                out[str(h.horizon)] = sorted(rows, key=lambda r: r["target_date"])[-MAX_ROWS:]
    return out


def attach(report: dict) -> dict:
    """Return a copy of report with report['quant_validation'] set. Never raises, never mutates the input or the saved report."""
    out = copy.copy(report)
    qv: dict = {"run": None, "status": "not_run", "scenarios": None, "fundamentals": None, "predictions": {}, "notes": [],
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out["quant_validation"] = qv
    try:
        symbol = (report.get("cover") or {}).get("symbol") or (report.get("company") or {}).get("symbol")
        run = None
        try:
            run = store.latest_run(symbol) if symbol else None
        except Exception as exc:  # noqa: BLE001  (stub NotImplementedError, missing db...)
            log.info("no run for %s: %s", symbol, exc)
        qv["status"], qv["run"] = _status_of(run), (run.model_dump() if run else None)
        px = _cached_prices(symbol) if symbol else None
        for key, fn, args in (("scenarios", scenarios.validate_scenarios, (report, run, px)),
                              ("fundamentals", fundamentals.check_fundamentals, (report, px))):
            try:
                qv[key] = fn(*args).model_dump()
            except Exception as exc:  # noqa: BLE001
                log.info("%s check failed: %s", key, exc)
                qv["notes"].append(f"The {key} check could not be computed.")
        if run is not None:
            qv["predictions"] = _predictions(run)
    except Exception as exc:  # noqa: BLE001
        log.warning("quant validation attach failed: %s", exc)
    return out


# ── shared parsing ─────────────────────────────────────────────────────────
def _parse(report: dict):
    qv = report.get("quant_validation") or {}
    def load(cls, key):
        try:
            return cls.model_validate(qv[key]) if qv.get(key) else None
        except Exception:  # noqa: BLE001
            return None
    run = load(RunResult, "run")
    return qv, run, _status_of(run) if run else (qv.get("status") if qv.get("status") in STATUSES else "not_run"), \
        load(ScenarioValidation, "scenarios"), load(FundamentalCheck, "fundamentals")


def _pc(v, d=1, sign=False) -> str:
    return "n/a" if v is None else f"{v * 100:{'+' if sign else ''}.{d}f}%"


def _pp(v, d=2) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f}"


def _num(v, d=2) -> str:
    return "n/a" if v is None else f"{v:,.{d}f}"


def _price(v, cur) -> str:
    return "n/a" if v is None else f"{cur + ' ' if cur else ''}{v:,.2f}"


def _selected(run: RunResult, h: HorizonResult) -> HorizonModelResult | None:
    return next((m for m in h.results if m.model == h.selected_model), None)


def _status_text(run: RunResult | None, status: str) -> str:
    if status == "not_run":
        return "No quantitative validation has been run for this company yet."
    if run is None:
        return _LABEL[status]
    if status in ("computing", "queued"):
        return f"{_LABEL[status]}: {run.progress}%" + (f", {run.stage}" if run.stage else "")
    if status == "no_model_beats_baseline":
        return ("No model beat the simple baseline (a random walk with no predictable return) out of sample. "
                "ARIA therefore does not offer a statistical forecast for this company; the fundamental targets below stand on their own.")
    if status == "insufficient_evidence":
        return "The history is too short or the evidence too thin to say whether any model beats the baseline. No forecast is offered."
    if status == "data_unavailable":
        return "Price history was unavailable or too short, so nothing could be validated."
    if status in ("failed", "timeout"):
        return f"The validation run {'timed out' if status == 'timeout' else 'failed'}." + (" Reason: " + "; ".join(run.errors) if run.errors else "")
    return "Validation complete. Read each horizon below: a model is only shown as useful where it beat the baseline out of sample."


# ── HTML ───────────────────────────────────────────────────────────────────
def _svg_series(rows: list[dict], title: str) -> str:
    """Actual vs predicted forward return by target date, with the 90% interval band."""
    from modules.equity_research.intelligence.report_html import _e
    n = len(rows)
    ys = [v for r in rows for v in (r["y_true"], r["y_pred"], r.get("q05"), r.get("q95")) if v is not None]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    w, h, pl, pb, pt = 520, 200, 38, 22, 10
    x = lambda i: pl + (w - pl - 6) * i / max(n - 1, 1)  # noqa: E731
    y = lambda v: pt + (h - pb - pt) * (1 - (v - lo) / span)  # noqa: E731
    band = [r for r in enumerate(rows) if r[1].get("q05") is not None and r[1].get("q95") is not None]
    parts = []
    if band:
        up = " ".join(f"{x(i):.1f},{y(r['q95']):.1f}" for i, r in band)
        dn = " ".join(f"{x(i):.1f},{y(r['q05']):.1f}" for i, r in reversed(band))
        parts.append(f'<polygon points="{up} {dn}" fill="#7c3aed" fill-opacity=".14"/>')
    parts.append(f'<polyline fill="none" stroke="#7c3aed" stroke-width="1.2" points="{" ".join(f"{x(i):.1f},{y(r["y_pred"]):.1f}" for i, r in enumerate(rows))}"/>')
    parts += [f'<circle cx="{x(i):.1f}" cy="{y(r["y_true"]):.1f}" r="1.6" fill="#1d4ed8"/>' for i, r in enumerate(rows)]
    parts.append(f'<line x1="{pl}" x2="{w}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#cbd5e1"/>' if lo < 0 < hi else "")
    parts.append(f'<text x="2" y="{pt + 8}" font-size="9" fill="#64748b">{_e(_pc(hi, 0))}</text><text x="2" y="{h - pb}" font-size="9" fill="#64748b">{_e(_pc(lo, 0))}</text>'
                 f'<text x="{pl}" y="{h - 6}" font-size="9" fill="#64748b">{_e(rows[0]["target_date"])}</text>'
                 f'<text x="{w - 6}" y="{h - 6}" font-size="9" text-anchor="end" fill="#64748b">{_e(rows[-1]["target_date"])}</text>')
    return (f'<div class="chart"><h4>{_e(title)}</h4><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_e(title)}: blue dots are actual returns, '
            f'purple line the predicted return, shaded band the 90% prediction interval. Summary table below.">{"".join(parts)}</svg></div>')


def _svg_hist(rows: list[dict], title: str) -> str:
    from modules.equity_research.intelligence.report_html import _e
    errs = [r["y_true"] - r["y_pred"] for r in rows]
    lo, hi, k = min(errs), max(errs), 20
    span = (hi - lo) or 1.0
    cnt = [0] * k
    for e in errs:
        cnt[min(int((e - lo) / span * k), k - 1)] += 1
    w, h, pb = 520, 160, 22
    top = max(cnt)
    bw = (w - 10) / k
    bars = "".join(f'<rect x="{5 + i * bw:.1f}" y="{(h - pb) * (1 - c / top) + 4:.1f}" width="{bw - 1:.1f}" height="{(h - pb) * c / top:.1f}" fill="#1d4ed8"/>' for i, c in enumerate(cnt))
    lab = (f'<text x="5" y="{h - 6}" font-size="9" fill="#64748b">{_e(_pc(lo, 1, True))}</text>'
           f'<text x="{w - 5}" y="{h - 6}" font-size="9" text-anchor="end" fill="#64748b">{_e(_pc(hi, 1, True))}</text>')
    return (f'<div class="chart"><h4>{_e(title)}</h4><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_e(title)}: histogram of actual minus predicted '
            f'return from {_e(_pc(lo, 1, True))} to {_e(_pc(hi, 1, True))}, {len(errs)} test observations. Summary table below.">{bars}{lab}</svg></div>')


def _charts(qv: dict, run: RunResult) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table, tag
    preds = qv.get("predictions") or {}
    out = ""
    for h in run.horizons:
        rows = preds.get(str(h.horizon))
        if h.horizon not in CHART_HORIZONS or not h.selected_model or not rows:
            continue
        errs = [r["y_true"] - r["y_pred"] for r in rows]
        inside = [r for r in rows if r.get("q05") is not None and r.get("q95") is not None]
        cov = sum(r["q05"] <= r["y_true"] <= r["q95"] for r in inside) / len(inside) if inside else None
        tbl = _table(["Test predictions", "Value"], [
            ["Observations", str(len(rows))], ["Period (target dates)", f'{_e(rows[0]["target_date"])} to {_e(rows[-1]["target_date"])}'],
            ["Mean error (actual - predicted)", _e(_pc(sum(errs) / len(errs), 2, True))], ["Mean absolute error", _e(_pc(sum(map(abs, errs)) / len(errs), 2))],
            ["Share of actuals inside the 90% interval", _e(_pc(cov, 1))]], cls="tight")
        shown = rows[0].get("model") or h.selected_model
        why = "selected model" if h.selected_model else "no model beat the baseline: the best challenger by validation error is shown for transparency"
        out += (f'<h3>{h.horizon}-day horizon: {_e(shown)} {tag("calculated")}</h3><p class="small muted">{_e(why)}.</p><div class="charts">'
                f'{_svg_series(rows, f"Actual vs predicted {h.horizon}-day return, test segment")}{_svg_hist(rows, f"Prediction error, {h.horizon}-day horizon")}</div>'
                f'<details><summary>Data table for these charts</summary>{tbl}</details>')
    return out or '<p class="na">No predictions stored, so no prediction charts are drawn.</p>'


def _leaderboard(run: RunResult) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table
    out = ""
    head = ["Model", "Family", "Return MAE val / test (% pts)", "Return RMSE test (% pts)", "Price MAE test", "Dir. acc.", "Bal. acc.", "Cov. 90%", "Width 90% (% pts)", "Pinball",
            "MAE vs baseline [95% CI, % pts]", "n / eff. n", "Status"]
    for h in sorted(run.horizons, key=lambda x: x.horizon):
        rows = []
        for m in h.baseline_results + h.results:
            vb, t, base = m.vs_baseline, m.test, m in h.baseline_results
            if base:
                imp, st = "reference", "baseline"
            elif vb is None or vb.mae_improvement_pct is None:
                imp, st = "n/a", "no comparison"
            else:
                ci = f" [{_pp(vb.ci_low)}, {_pp(vb.ci_high)}]" if vb.ci_low is not None and vb.ci_high is not None else ""
                imp = f"{vb.mae_improvement_pct:+.1f}%{ci}" + (" &#9733;" if vb.significant else "")
                st = "beats baseline (significant)" if vb.significant and vb.mae_improvement_pct > 0 else "not significant"
            sel = " (selected)" if m.model == h.selected_model else ""
            rows.append([f"{_e(m.model)}{sel}", _e(m.family), f"{_pp(m.validation.mae_ret)} / {_pp(t.mae_ret)}", _pp(t.rmse_ret), _num(t.mae, 2), _pc(t.dir_acc), _pc(t.balanced_acc),
                         _pc(t.coverage_90), _pp(t.mean_width_90), _num(t.pinball, 4), imp, f"{t.n} / {_num(t.effective_n, 1)}", _e(st)])
        body = (_table(head, rows, cls="tight wide").replace(
            "<thead>", f'<caption class="sr">Model leaderboard, {h.horizon}-day horizon</caption><thead>', 1) if rows else '<p class="na">No models were evaluated at this horizon.</p>')
        notes = "".join(f"<li>{_e(n)}</li>" for n in h.notes)
        out += (f'<details{" open" if h.horizon in OPEN_HORIZONS else ""}><summary><b>{h.horizon}-day horizon</b>: {_e(_LABEL.get(h.status, h.status))}'
                f'{", selected " + _e(h.selected_model) if h.selected_model else ""}</summary>{body}{"<ul class=small>" + notes + "</ul>" if notes else ""}</details>')
    return out or '<p class="na">No horizons were evaluated.</p>'


def _forecasts(run: RunResult) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table
    if not run.forecasts:
        return '<p class="na">No forecast is offered: no model beat the baseline at any horizon, or the run did not finish.</p>'
    rows = [[f"{f.horizon}d", _pc(f.point_return, 2, True), _pc(f.median_return, 2, True), _price(f.point_price, f.currency or (run.dataset.currency if run.dataset else None)),
             f"{_pc(f.lower_return, 2, True)} / {_pc(f.upper_return, 2, True)}",
             f"{_price(f.lower_price, f.currency)} / {_price(f.upper_price, f.currency)}", _e(f"{f.model} {f.model_version}"), _e(f.target_date),
             "yes" if f.oos_validated else "no", _pc(f.p_positive, 0) if f.p_positive is not None else "not shown (uncalibrated)", _e("; ".join(f.warnings)) or "none"]
            for f in sorted(run.forecasts, key=lambda f: f.horizon)]
    return (_table(["Horizon", "Point return", "Median return", "Point price", "90% range (return)", "90% range (price)", "Model", "Target date",
                    "Out-of-sample validated", "P(positive)", "Warnings"], rows, text=(10,), cls="tight wide")
            + '<p class="small muted">Returns are log returns. A forecast marked "out-of-sample validated: no" did not pass the walk-forward test and should not be relied on.</p>')


def _scen_table(sv: ScenarioValidation | None, cur: str | None) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table, tag
    if sv is None:
        return '<p class="na">Scenario validation could not be computed.</p>'
    if not sv.checks:
        return '<p class="na">No scenario targets were available to validate.</p>'
    rows, det = [], ""
    for c in sv.checks:
        f, a = c.ml_forecast, c.analogue
        ml = "no validated forecast" if f is None else (f"{_pc(f.point_return, 1, True)} ({_pc(f.lower_return, 1, True)} to {_pc(f.upper_return, 1, True)}) at {c.ml_horizon_used}d"
                                                         + ("" if f.oos_validated else ", not out-of-sample validated"))
        an = "none" if a is None else (f"n={a.n_analogues}, eff. n={_num(a.effective_n, 1)}, hit frequency {_pc(a.freq_at_least_target)} vs {_pc(a.unconditional_freq)} unconditional"
                                       + (f" ({_e(a.warning)})" if a.warning else ""))
        imp = _pc(c.implied_return, 1, True) + (f" over {c.horizon_days}d (assumed horizon)" if c.horizon_is_assumption else f" over {c.horizon_days}d")
        rows.append([c.scenario.title(), _price(c.fundamental_target, cur), imp, _e(ml), an, _pc(c.hist_vol_252, 1), _pc(c.hist_max_drawdown, 1),
                     f'<span class="chip">{_e(c.status.replace("_", " "))}</span>'])
        det += (f'<details><summary>{c.scenario.title()}: evidence and limitations</summary><p class="small"><b>For:</b></p><ul>'
                + "".join(f"<li>{_e(x)}</li>" for x in c.evidence_for) + '</ul><p class="small"><b>Against:</b></p><ul>' + "".join(f"<li>{_e(x)}</li>" for x in c.evidence_against)
                + '</ul><p class="small"><b>Limitations:</b></p><ul>' + "".join(f"<li>{_e(x)}</li>" for x in c.limitations) + "</ul></details>")
    notes = "".join(f"<li>{_e(n)}</li>" for n in sv.notes)
    return (f'<h3>Scenario validation {tag("calculated")}</h3>' + _table(["Scenario", "Fundamental target", "Implied return", "ML forecast (matched horizon)", "Analogue evidence",
                                                                      "Hist. vol (252d)", "Hist. max drawdown", "Verdict"], rows, text=(3, 4), cls="tight wide")
            + det + (f'<ul class="small">{notes}</ul>' if notes else ""))


def _fund_table(fc: FundamentalCheck | None) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table, tag
    if fc is None:
        return '<p class="na">Fundamental checks could not be computed.</p>'
    rows = [[_e(c.scenario), _num(c.reproduced_value), _num(c.reported_value), _num(c.abs_diff_pct, 2) + ("%" if c.abs_diff_pct is not None else ""),
             {True: "match", False: "differs", None: "not checked"}[c.ok], _e("; ".join(c.issues)) or "none"] for c in fc.cases]
    ul = lambda xs: "<ul class=small>" + "".join(f"<li>{_e(x)}</li>" for x in xs) + "</ul>" if xs else ""  # noqa: E731
    return (f'<h3>Fundamental checks {tag("calculated")}</h3>'
            + (_table(["Case", "Reproduced value", "Reported value", "Difference", "Result", "Issues"], rows, text=(5,), cls="tight") if rows else '<p class="na">No cases were re-computed.</p>')
            + (f"<p class='small'><b>Assumption flags</b></p>{ul(fc.assumption_flags)}" if fc.assumption_flags else "")
            + (f"<p class='small'><b>Sensitivity</b></p>{ul(fc.sensitivity_notes)}" if fc.sensitivity_notes else "") + ul(fc.notes)
            + f'<p class="callout small">{_e(fc.retro_accuracy_note)}</p>')


def _regimes(run: RunResult) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table
    rows, warns = [], []
    for h in sorted(run.horizons, key=lambda x: x.horizon):
        m = _selected(run, h)
        if m is None:
            continue
        for k, b in sorted(m.regimes.items()):
            small = b.n < SMALL_N
            rows.append([f"{h.horizon}d", _e(k.replace(":", " = ")), str(b.n), _pp(b.mae_ret), _pc(b.dir_acc), _pc(b.coverage_90), f"small sample (n&lt;{SMALL_N}), unreliable" if small else "ok"])
        warns += [f"{h.horizon}d: {w}" for w in m.regime_warnings]
    if not rows:
        return '<p class="na">No regime breakdown is available.</p>'
    return _table(["Horizon", "Regime", "n", "MAE (% pts)", "Dir. acc.", "Cov. 90%", "Sample"], rows, cls="tight") + (
        "<ul class=small>" + "".join(f"<li>{_e(w)}</li>" for w in warns) + "</ul>" if warns else "")


def _coverage(run: RunResult) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table
    d = run.dataset
    if d is None:
        return '<p class="na">No dataset was recorded for this run.</p>'
    q = d.quality
    wins = "".join(f"<li>{_e(w)}</li>" for w in q.warnings) or "<li>none</li>"
    rows = [["Source", _e(d.provider)], ["First / last bar", f"{_e(d.first_bar)} to {_e(d.last_bar)}"], ["Bars", str(d.n_bars)],
            ["Currency / exchange", f'{_e(d.currency or "n/a")} / {_e(d.exchange or "n/a")}'],
            ["Benchmark", _e(d.benchmark_symbol or "none") + (f" (from {_e(d.benchmark_first_bar)})" if d.benchmark_first_bar else "")],
            ["Price basis", _e(d.price_basis)], ["Training cutoff", _e(run.training_cutoff or "n/a")],
            ["Validation / test windows", f"last {VAL_BARS} bars before the test segment / final {TEST_BARS} bars, kept untouched; embargo {EMBARGO} bars"],
            ["Data quality", f"gaps {q.gaps}, duplicates {q.duplicates}, zero-volume days {q.zero_volume_days}, outliers {q.outliers}, splits {q.split_events}, dividends {q.dividend_events}"]]
    lim = list(dict.fromkeys(list(d.limitations) + list(run.limitations)))
    return (_table(["Item", "Value"], rows, text=(1,), cls="tight") + f"<p class='small'><b>Data-quality warnings</b></p><ul class='small'>{wins}</ul>"
            + "<p class='small'><b>Limitations</b></p><ul class='small'>" + "".join(f"<li>{_e(x)}</li>" for x in lim) + "</ul>")


_RISK_TEXT = ("Model uncertainty: even a model that beat the baseline explains only a small part of future returns, and intervals can be wrong in the tails. "
              "Data limits: prices come from a single vendor, are revised after the fact, exclude delisted companies (survivorship bias) and no fundamentals were available point-in-time. "
              "Regime sensitivity: results can differ sharply between bull and bear, high- and low-volatility periods, and small regime samples are flagged. "
              "Leakage controls: walk-forward evaluation, an embargo between train and test, and a test segment never used to choose or tune a model. "
              "Horizon: accuracy falls with the forecast horizon. Any trading simulation is hypothetical, ignores most real-world frictions and is not a recommendation. "
              "Historical performance does not guarantee future performance.")


def html_section(report: dict) -> str:
    from modules.equity_research.intelligence.report_html import _e, tag
    qv, run, status, sv, fc = _parse(report)
    head = f'<section><h2><span class="n">0</span>Quantitative forecast validation {tag("calculated")}</h2>'
    note = ('<p class="small muted">These numbers are produced by code from market data (walk-forward backtests), not by the language model. '
            'They test whether statistical models can forecast this stock better than a naive baseline, and whether the report\'s scenarios are consistent with price history.</p>')
    cls = {"ok_beats_baseline": "good", "computing": "", "queued": "", "not_run": ""}.get(status, "warn")
    banner = f'<div class="callout {cls}" role="status"><b>{_e(_LABEL[status])}.</b> {_e(_status_text(run, status))}</div>'
    extra = "".join(f"<li>{_e(n)}</li>" for n in qv.get("notes") or [])
    body = ""
    cur = run.dataset.currency if run and run.dataset else None
    if run is not None and status not in ("queued", "not_run", "data_unavailable") and (run.horizons or run.dataset):
        body += (f'<h3>Data coverage {tag("actual")}</h3>{_coverage(run)}<h3>Model leaderboard {tag("calculated")}</h3>'
                 f'<p class="small muted">Baselines sit in the same table. Improvement is the change in out-of-sample MAE versus the random-walk baseline (positive = better); '
                 f'&#9733; marks a 95% block-bootstrap interval that excludes zero. Directional accuracy compares the sign of the forecast with the sign of the realised return; '
                 f'a model that always forecasts a rise, or a zero forecast (the random walk), scores the share of rising or non-rising periods in the test window, so read it against that base rate, not against 50%.</p>{_leaderboard(run)}'
                 f'<h3>Prediction charts {tag("calculated")}</h3>{_charts(qv, run)}<h3>Forecasts {tag("estimate")}</h3>{_forecasts(run)}')
    elif run is not None and run.dataset:
        body += f'<h3>Data coverage {tag("actual")}</h3>{_coverage(run)}'
    if sv is not None or qv.get("notes"):
        body += _scen_table(sv, cur)
    if fc is not None or qv.get("notes"):
        body += _fund_table(fc)
    if run is not None and status not in ("queued", "not_run", "data_unavailable") and run.horizons:
        body += f'<h3>Regimes {tag("calculated")}</h3>{_regimes(run)}'
    return (head + note + banner + (f"<ul class='small'>{extra}</ul>" if extra else "") + body
            + f'<h3>Risks and limitations</h3><p class="small">{_e(_RISK_TEXT)}</p></section>')


# ── Markdown ───────────────────────────────────────────────────────────────
def md_section(report: dict) -> str:
    qv, run, status, sv, fc = _parse(report)
    t = lambda cols, rows: "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"  # noqa: E731
    out = ["## Quantitative forecast validation", "", "_Produced by code (walk-forward backtests), not by the language model._", "",
           f"**{_LABEL[status]}.** {_status_text(run, status)}", ""]
    out += [f"- {n}" for n in qv.get("notes") or []]
    if run is not None:
        for h in sorted(run.horizons, key=lambda x: x.horizon):
            def vs(m, h=h):
                b = m.vs_baseline
                if m in h.baseline_results:
                    return "reference"
                return "n/a" if b is None or b.mae_improvement_pct is None else f"{b.mae_improvement_pct:+.1f}%" + (" *" if b.significant else "")
            rows = [[m.model, m.family, _pp(m.validation.mae_ret), _pp(m.test.mae_ret), _pc(m.test.dir_acc), _pc(m.test.coverage_90), vs(m)]
                    for m in h.baseline_results + h.results]
            out += [f"### {h.horizon}-day horizon: {_LABEL.get(h.status, h.status)}", t(["Model", "Family", "MAE val (% pts)", "MAE test (% pts)", "Dir. acc.", "Cov. 90%", "vs baseline"], rows) if rows else "No models evaluated.", ""]
        if run.forecasts:
            out += ["### Forecasts", t(["Horizon", "Point return", "90% range", "Model", "Target date", "Out-of-sample validated"],
                                       [[f"{f.horizon}d", _pc(f.point_return, 2, True), f"{_pc(f.lower_return, 2, True)} to {_pc(f.upper_return, 2, True)}", f.model, f.target_date,
                                         "yes" if f.oos_validated else "no"] for f in sorted(run.forecasts, key=lambda f: f.horizon)]), ""]
    if sv and sv.checks:
        out += ["### Scenario validation", t(["Scenario", "Target", "Implied return (12m assumption)", "ML forecast", "Verdict"],
                [[c.scenario, _num(c.fundamental_target), _pc(c.implied_return, 1, True),
                  "none" if c.ml_forecast is None else f"{_pc(c.ml_forecast.point_return, 1, True)} at {c.ml_horizon_used}d", c.status.replace("_", " ")] for c in sv.checks]), ""]
    if fc:
        out += ["### Fundamental checks", t(["Case", "Reproduced", "Reported", "Diff %", "Issues"],
                [[c.scenario, _num(c.reproduced_value), _num(c.reported_value), _num(c.abs_diff_pct), "; ".join(c.issues) or "none"] for c in fc.cases]) if fc.cases else "No cases re-computed.",
                "", f"_{fc.retro_accuracy_note}_", ""]
    return "\n".join(out + ["### Risks and limitations", "", _RISK_TEXT, ""])
