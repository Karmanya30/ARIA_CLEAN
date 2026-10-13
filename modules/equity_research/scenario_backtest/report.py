"""Report section 'Historical backtest of these scenarios'. Reads the CACHED backtest result only (never computes), never raises.
Every number is produced by code; the language model writes none of them."""
from __future__ import annotations

import copy
import json
import logging
import math
from datetime import datetime, timezone

import pandas as pd

from modules.equity_research.scenario_backtest import data
from modules.equity_research.scenario_backtest.data import CACHE_DIR, fye

log = logging.getLogger(__name__)

SHOW_K = (1, 3, 5)            # horizons listed in the table; the fan chart shows all elapsed ones
CASES = ("bear", "base", "bull")
LINES = {"dcf": ("revenue", "ebitda", "margin"), "ddm": ("eps", "dps")}  # fcf is indicative only, left out of the table
PRIMARY = {"dcf": "revenue", "ddm": "eps"}
MIN_CELL = 30  # universe/sector percentile needs this many companies
REF = 0.68  # labelled reference only: the band carries no stated coverage
STATUS_TEXT = {
    "not_run": "The historical backtest has not been run for this company, so nothing is shown. It runs in the background after a report is generated.",
    "computing": "The historical backtest is being computed. Reload the report shortly.",
    "failed": "The historical backtest failed for this company.",
    "no_screener_page": "No statement history could be found for this company (it may be listed only on BSE), so no past year could be replayed.",
}
LIMITS = ("Past fiscal years are replayed with ARIA's unchanged code on statements as they stand now (restated figures, not as first reported); publication dates are "
          "assumed (annual results 90 days and quarters 45 days after period end). Sector labels and the risk-free rate, equity risk premium and terminal growth are today's "
          "values. Horizons of 9-10 years can never be validated: the statement source has about 12 fiscal years, so only the elapsed part of each path is scored. Origins "
          "overlap and share realised years, and a year like FY21 affects every company, so the effective sample is far smaller than the row count. The in-band share is "
          "compared with 68% only as a reference: this is scenario coverage, not a calibration test, because the bear and bull cases carry no stated probability. Price convergence is not proof of forecast accuracy. "
          "This is a test of past scenarios, not a forecast.")


# ── load (cached files only) ───────────────────────────────────────────────
def _result(symbol: str):
    """(forecasts, origins, summary) from the result files, or None. The files are the contract with jobs.py."""
    d = CACHE_DIR / "results"
    try:
        fp, op, sp = d / f"{symbol}.forecasts.parquet", d / f"{symbol}.origins.parquet", d / f"{symbol}.summary.json"
        summary = json.loads(sp.read_text("utf-8")) if sp.exists() else {}
        f = pd.read_parquet(fp) if fp.exists() else pd.DataFrame()
        if f.empty and not summary:
            return None
        return f, pd.read_parquet(op) if op.exists() else pd.DataFrame(), summary
    except Exception as exc:  # noqa: BLE001
        log.info("backtest result unreadable for %s: %s", symbol, exc)
        return None


def _fin(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _year(col: str) -> int:
    return fye(col).year


def _n_years(symbol: str) -> int | None:
    try:
        _, meta = data.load(symbol)
        return len(meta.get("fiscal_years") or []) or None
    except Exception:  # noqa: BLE001
        return None


# ── attach ─────────────────────────────────────────────────────────────────
def attach(report: dict) -> dict:
    """Copy of the report with report['scenario_backtest'] set. Never raises, never mutates the input."""
    out = copy.copy(report)
    sb: dict = {"status": "not_run", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out["scenario_backtest"] = sb
    try:
        symbol = (report.get("cover") or {}).get("symbol") or (report.get("company") or {}).get("symbol")
        res = _result(symbol) if symbol else None
        if res is None:
            try:
                from modules.equity_research.scenario_backtest import jobs
                sb["status"] = "computing" if jobs.status(symbol) == "computing" else "not_run"
            except Exception:  # noqa: BLE001
                pass
            return out
        f, o, summary = res
        sb.update(_build(symbol, f, o, summary or {}))
    except Exception as exc:  # noqa: BLE001
        log.warning("scenario backtest attach failed: %s", exc)
        sb["status"] = "failed"
    return out


def _stats_from_rows(scored: list, line: str) -> dict:
    """Fallback for results written without a metrics block: figures taken straight from the listed rows."""
    errs = sorted(abs(r["err"]) for r in scored if r["err"] is not None)
    stats = {"line": line, "n": len(scored), "in_band": sum(r["in_band"] for r in scored) / len(scored) if scored else None,
             "median_abs_err": errs[len(errs) // 2] if errs else None, "by_k": {}, "from": "rows"}
    for k in sorted({r["k"] for r in scored}):
        e = sorted(abs(r["err"]) for r in scored if r["k"] == k and r["err"] is not None)
        n = sum(r["k"] == k for r in scored)
        stats["by_k"][str(k)] = {"n": n, "in_band": sum(r["in_band"] for r in scored if r["k"] == k) / n, "median_abs_err": e[len(e) // 2] if e else None}
    return stats


def _pct_err(line: str, e):
    """metrics' median |error| (log for levels, pp for margin) as a percentage / pp figure."""
    e = _fin(e)
    return None if e is None else (e if line == "margin" else math.expm1(e) * 100)


def _stats_from_metrics(m: dict | None, line: str, short_only: bool) -> dict | None:
    """Headline figures from metrics.company_summary (the summary.json 'metrics' block); None when it holds nothing usable."""
    try:
        lines = ((m.get("short_history") or {}).get("lines") if short_only else m.get("lines")) or {}
        cells = {int(k): c for k, c in (lines.get(line) or {}).get("k", {}).items() if isinstance(c, dict) and not c.get("suppressed") and c.get("band")}
    except Exception:  # noqa: BLE001
        return None
    if not cells:
        return None
    by_k, n_tot, inside = {}, 0, 0.0
    for k, c in sorted(cells.items()):
        sk, ne = c.get("skill") or {}, c.get("nearest") or {}
        by_k[str(k)] = {"n": c["n_obs"], "in_band": c["band"]["inside"], "median_abs_err": _pct_err(line, c["base"].get("median_abs_e")),
                        "nearest": {x: ne.get(x) for x in CASES} if ne else None,
                        "skill": {x: (sk.get(x) or {}).get("skill") for x in sk}, "ci": c["base"].get("bias_ci90")}
        n_tot += c["n_obs"]
        inside += c["band"]["inside"] * c["n_obs"]
    first = next(iter(by_k.values()))
    return {"line": line, "n": n_tot, "in_band": inside / n_tot if n_tot else None, "median_abs_err": first["median_abs_err"],
            "first_k": next(iter(by_k)), "by_k": by_k, "from": "metrics"}


def _extra_bias(m: dict | None, short_only: bool) -> dict:
    """Growth bias (pp/yr) and EBITDA-margin bias (pp) by horizon from the metrics block."""
    out: dict = {"growth": {}, "margin": {}}
    try:
        src = (m.get("short_history") or {}) if short_only else m
        out["growth"] = {int(k): _fin(v.get("bias_pp")) for k, v in ((src.get("growth") or {}).get("k") or {}).items()}
        out["margin"] = {int(k): _fin(c["base"].get("bias")) for k, c in (((src.get("lines") or {}).get("margin") or {}).get("k") or {}).items()
                         if isinstance(c, dict) and c.get("base")}
    except Exception:  # noqa: BLE001
        pass
    return out


def _percentiles(symbol: str, m: dict | None) -> dict:
    """Where the company's typical base-case miss (median |log error| of its primary line, k = 1-5) sits among the companies in
    data/scenario_backtest/summary.parquet: share of companies with a LARGER miss. Universe and sector cells need >= 30 companies."""
    try:
        mine = _fin(_medabs(m))
        if mine is None:
            return {}
        df = pd.read_parquet(CACHE_DIR / "summary.parquet", columns=["yahoo_symbol", "m_sector", "m_medabs_e"])
        df = df[df["m_medabs_e"].notna() & (df["yahoo_symbol"] != symbol)]
        out = {}
        for name, d in (("universe", df), ("sector", df[df["m_sector"] == (m or {}).get("sector")])):
            if len(d) + 1 >= MIN_CELL and (name == "universe" or (m or {}).get("sector")):
                out[name] = {"n": len(d) + 1, "better_than": float((d["m_medabs_e"] > mine).mean() * 100), "label": (m or {}).get("sector") if name == "sector" else "backtested"}
        return out
    except Exception:  # noqa: BLE001
        return {}


def _medabs(m: dict | None) -> float | None:
    """Same definition the universe script stores as m_medabs_e: median over k = 1..5 of the primary line's median |error|."""
    from modules.equity_research.scenario_backtest.metrics import medabs_primary
    return medabs_primary(m)


def _source(summary: dict) -> str | None:
    """'screener.in (12 fiscal years)' / 'yfinance fallback (4 fiscal years)' as stored by the job; None for old results."""
    n, prov = summary.get("n_fiscal_years"), summary.get("provider")
    if not prov and summary.get("symbol"):  # results written before the provider was recorded: read the cached statements' metadata
        try:
            meta = data.load(summary["symbol"])[1]
            n, prov = len(meta.get("fiscal_years") or []) or None, meta.get("provider")
        except Exception:  # noqa: BLE001
            pass
    if not prov:
        return None
    if prov == "yfinance":
        return f"yfinance fallback ({n} fiscal years)" if n else "yfinance fallback"
    return f"screener.in ({n} fiscal years)" if n else "screener.in"


def _build(symbol: str, f: pd.DataFrame, o: pd.DataFrame, summary: dict) -> dict:
    st = str(summary.get("status") or ("ok" if len(f) else "insufficient_history"))
    if st in ("failed", "no_screener_page", "computing"):
        return {"status": st, "reasons": [summary["reason"]] if summary.get("reason") else []}
    if st == "insufficient_history" or (f.empty and st != "model_refused"):
        return {"status": "insufficient_history", "n_years": summary.get("n_fiscal_years") or summary.get("n_years") or _n_years(symbol),
                "reason": summary.get("reason"), "source": _source(summary)}
    reasons = sorted({r for r in (o["refused_reason"] if "refused_reason" in o else f.get("refused_reason", [])) if r}) or list(summary.get("reasons") or [])
    if st == "model_refused" or f["forecast"].isna().all():
        reasons = reasons or ([summary["reason"]] if summary.get("reason") else [])
        return {"status": "model_refused", "reasons": reasons}
    model = str(f["model"].iloc[0])
    line = PRIMARY.get(model, "revenue")
    sub = f[f["case"].isin(CASES + ("naive_rw",))]
    wide = sub.pivot_table(index=["origin_fy", "line", "k"], columns="case", values="forecast", aggfunc="first")
    act = sub.groupby(["origin_fy", "line", "k"])["actual"].first()
    rows = []
    short_set = {fy for fy, fl in zip(o["origin_fy"], o["flags"].fillna("")) if "short_history" in fl.split(",")} if len(o) and "flags" in o else set()
    for (fy, ln, k), r in wide.iterrows():
        a = _fin(act.get((fy, ln, k)))
        if a is None or ln not in LINES.get(model, ()) or not all(_fin(r.get(c)) is not None for c in CASES):
            continue
        bear, base, bull = (float(r[c]) for c in CASES)
        err = (base - a) * 100 if ln == "margin" else ((base - a) / a * 100 if a > 0 else None)  # margin: percentage points
        rows.append({"origin": fy, "line": ln, "k": int(k), "bear": bear, "base": base, "bull": bull, "actual": a,
                     "in_band": min(bear, bull) <= a <= max(bear, bull), "err": err, "short": fy in short_set})
    order = list(LINES.get(model, ()))
    rows.sort(key=lambda x: (order.index(x["line"]), _year(x["origin"]), x["k"]))
    # fan: actuals by fiscal year for the primary line, the origin base/bear/bull paths
    hist: dict[int, float] = {}
    paths: dict[str, dict[str, list]] = {}
    pl = f[f["line"] == line]
    for fy, g in pl.groupby("origin_fy"):
        y0 = _year(fy)
        for _, r in g.iterrows():
            a, k = _fin(r["actual"]), int(r["k"])
            if a is not None:
                hist[y0 + k] = a
            if r["case"] == "naive_rw" and _fin(r["forecast"]) is not None:
                hist[y0] = float(r["forecast"])
            if r["case"] in CASES and _fin(r["forecast"]) is not None:
                paths.setdefault(fy, {}).setdefault(r["case"], []).append([y0 + k, float(r["forecast"])])
    fan = {"line": line, "model": model, "hist": sorted(hist.items()),
           "paths": {fy: {c: sorted(v) for c, v in p.items()} for fy, p in sorted(paths.items(), key=lambda kv: _year(kv[0]))}}
    scored = [r for r in rows if r["line"] == line and not r["short"]]
    short_only = not scored  # a young company: nothing but short-history origins, shown (and labelled) as such
    scored = scored or [r for r in rows if r["line"] == line]
    stats = _stats_from_metrics(summary.get("metrics"), line, short_only) or _stats_from_rows(scored, line)
    stats["n_origins"] = len({r["origin"] for r in scored})
    pct = _percentiles(symbol, summary.get("metrics"))
    return {"status": "ok", "model": model, "rows": rows, "fan": fan, "stats": stats, "percentiles": pct, "extra": _extra_bias(summary.get("metrics"), short_only), "reasons": reasons,
            "refused_origins": int(o["refused_reason"].astype(bool).sum()) if len(o) and "refused_reason" in o else 0, "n_origins_total": int(len(o)),
            "source": _source(summary), "n_short_origins": len(short_set), "short_only": short_only}


# ── formatting ─────────────────────────────────────────────────────────────
def _pc(v, d=1, sign=False) -> str:
    return "n/a" if v is None else f"{v:{'+' if sign else ''}.{d}f}%"


def _val(line: str, v) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if line == "margin" else (f"{v:,.2f}" if line in ("eps", "dps") else f"{v:,.0f}")


def _errtxt(line: str, e) -> str:
    return "n/a" if e is None else (f"{e:+.1f} pp" if line == "margin" else f"{e:+.1f}%")


def _status_text(sb: dict) -> str:
    s = sb.get("status")
    if s == "insufficient_history":
        n = sb.get("n_years")
        if sb.get("reason"):
            return f"{sb['reason']}. No origin year could be replayed." + (f" Source: {sb['source']}." if sb.get("source") else "")
        return f"{n if n is not None else 'Too few'} fiscal years available; 3 needed (2 to project from, 1 to score). No origin year could be replayed."
    if s == "model_refused":
        return "Model refused at every origin: " + ("; ".join(sb.get("reasons") or []) or "no reason recorded") + "."
    return STATUS_TEXT.get(s, STATUS_TEXT["not_run"]) + (" " + "; ".join(sb["reasons"]) if s in ("failed", "no_screener_page") and sb.get("reasons") else "")


def _sentence(sb: dict) -> str:
    st = sb["stats"]
    kk = st.get("first_k")
    when = f" {kk} year ahead" if kk == "1" else (f" {kk} years ahead" if kk else "")
    return (f"Across {st['n_origins']} past fiscal years replayed, the {st['line']} later reported fell between the bear and bull cases in {_pc(st['in_band'] * 100 if st['in_band'] is not None else None, 0)} "
            f"of {st['n']} checks (scenario coverage; {REF * 100:.0f}% is shown only as a reference), and the base case missed by a median of {_pc(st['median_abs_err'])}"
            + (" (percentage points)" if st["line"] == "margin" else "") + (f" for the{when} figure" if when else "") + ".")


def _sk(v) -> str:
    return "n/a" if v is None else f"{v:+.2f}"


def _near(n) -> str:
    return "n/a" if not n or n.get("bear") is None else " / ".join(f"{100 * n[c]:.0f}%" for c in CASES)


def _pct_text(pc: dict) -> str:
    """'Typical miss smaller than X% of N companies' lines; only cells with >= 30 companies exist in pc."""
    return "; ".join(f"typical base-case miss was smaller than that of {v['better_than']:.0f}% of {v['n']} " + ("backtested companies" if k == "universe" else f"{v['label']} companies in the sector")
                     for k, v in pc.items() if k in ("sector", "universe"))


# ── SVG ────────────────────────────────────────────────────────────────────
def _svg_fan(fan: dict, title: str) -> str:
    """History (reported), the latest origin's three paths, and earlier origins' base paths against what was reported."""
    from modules.equity_research.intelligence.report_html import _e
    hist, paths = fan.get("hist") or [], fan.get("paths") or {}
    if not hist and not paths:
        return ""
    last = list(paths)[-1] if paths else None
    ys = [v for _, v in hist] + [v for p in paths.values() for pts in p.values() for _, v in pts]
    xs = [x for x, _ in hist] + [x for p in paths.values() for pts in p.values() for x, _ in pts]
    lo, hi, x0, x1 = min(ys), max(ys), min(xs), max(xs)
    span = (hi - lo) or 1.0
    w, h, pl, pb, pt = 560, 260, 62, 30, 16
    X = lambda x: pl + (w - pl - 8) * (x - x0) / ((x1 - x0) or 1)  # noqa: E731
    Y = lambda v: pt + (h - pb - pt) * (1 - (v - lo) / span)  # noqa: E731
    pts = lambda seq: " ".join(f"{X(x):.1f},{Y(v):.1f}" for x, v in seq)  # noqa: E731
    line = fan.get("line", "")
    fmt = lambda v: _val(line, v)  # noqa: E731
    out = []
    for fy, p in paths.items():
        if fy == last:
            continue
        base = p.get("base")
        if base:
            origin_y = _year(fy)
            start = [(origin_y, dict(hist).get(origin_y))] if dict(hist).get(origin_y) is not None else []
            out.append(f'<polyline fill="none" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3 2" points="{pts(start + base)}"/>')
    if last:
        p, origin_y = paths[last], _year(last)
        a0 = dict(hist).get(origin_y)
        if p.get("bear") and p.get("bull"):
            up = p["bull"]; dn = p["bear"][::-1]
            out.append(f'<polygon points="{pts(up)} {pts(dn)}" fill="#7c3aed" fill-opacity=".12"/>')
        for c, col, dash in (("bull", "#16a34a", ""), ("base", "#7c3aed", ""), ("bear", "#dc2626", "")):
            if p.get(c):
                out.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.6" points="{pts(([(origin_y, a0)] if a0 is not None else []) + p[c])}"/>')
    out.append(f'<polyline fill="none" stroke="#1d4ed8" stroke-width="2" points="{pts(hist)}"/>')
    out += [f'<circle cx="{X(x):.1f}" cy="{Y(v):.1f}" r="2.4" fill="#1d4ed8"/>' for x, v in hist]
    out.append(f'<text x="2" y="{pt + 8}" font-size="13" fill="#64748b">{_e(fmt(hi))}</text><text x="2" y="{h - pb}" font-size="13" fill="#64748b">{_e(fmt(lo))}</text>'
               f'<text x="{pl}" y="{h - 8}" font-size="13" fill="#64748b">FY{x0}</text><text x="{w - 8}" y="{h - 8}" font-size="13" text-anchor="end" fill="#64748b">FY{x1}</text>')
    sw = lambda c, d="": f'<span style="display:inline-block;width:16px;border-top:2px {d or "solid"} {c};vertical-align:middle;margin:0 4px 0 10px"></span>'  # noqa: E731
    legend = ('<p class="small muted" style="margin:2px 0 6px">' + sw("#1d4ed8") + "reported" + sw("#16a34a") + "bull" + sw("#7c3aed") + "base" + sw("#dc2626") + "bear (latest origin)"
              + sw("#94a3b8", "dashed") + "earlier origins, base</p>")
    desc = (f"{title}. Blue is the reported {line}; the coloured lines are the bull, base and bear paths made at the latest past origin, FY{_year(last)}; "
            f"dashed grey lines are the base paths made at earlier origins. A table with the same numbers follows." if last else f"{title}. Reported history only.")
    return (f'<div class="chart"><h4>{_e(title)}</h4>{legend}<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_e(desc)}">{"".join(out)}</svg></div>')


# ── HTML ───────────────────────────────────────────────────────────────────
def html_section(report: dict) -> str:
    from modules.equity_research.intelligence.report_html import _e, _table, tag
    sb = report.get("scenario_backtest")
    if not sb:
        return ""
    head = f'<section><h2><span class="n">0</span>Historical backtest of these scenarios {tag("calculated")}</h2>'
    note = ('<p class="small muted">Produced by code, not by the language model. For each past fiscal year, ARIA\'s own bear, base and bull projections were rebuilt using only what '
            'was public then, and compared with what the company later reported. Reported figures are tagged <b>ACTUAL</b>, projections and errors <b>CALCULATED</b>.</p>')
    status = sb.get("status", "not_run")
    if status != "ok":
        cls = "" if status in ("not_run", "computing") else "warn"
        return head + note + f'<div class="callout {cls}" role="status"><b>{_e(status.replace("_", " ").capitalize())}.</b> {_e(_status_text(sb))}</div></section>'
    st, fan, rows, model = sb["stats"], sb["fan"], sb["rows"], sb["model"]
    banner = f'<div class="callout good" role="status"><b>Backtest complete.</b> {_e(_sentence(sb))}</div>'
    extra = f'<p class="small muted">Statements from: {_e(sb["source"])}.</p>' if sb.get("source") else ""
    if sb.get("n_short_origins"):
        extra += (f'<p class="small muted">{sb["n_short_origins"]} origin(s) had only 2-3 fiscal years of history and are marked "short history" in the table; '
                  + ("the summary below is based on them alone." if sb.get("short_only") else "they are left out of the summary below and of the universe headline numbers.") + '</p>')
    if sb.get("refused_origins"):
        extra += f'<p class="small muted">The model declined {sb["refused_origins"]} of {sb["n_origins_total"]} origins: {_e("; ".join(sb.get("reasons") or []))}.</p>'
    m_line = st["line"] == "margin"
    kb = {int(k): v for k, v in (sb.get("extra") or {}).get("growth", {}).items()}
    has_m = st.get("from") == "metrics"
    ks = "".join(f"<tr><td class='l'>{k} yr</td><td>{v['n']}</td><td>{_pc(v['in_band'] * 100, 0)}</td><td>{_pc(v['median_abs_err'])}</td>"
                 + (f"<td>{_near(v.get('nearest'))}</td><td>{_sk((v.get('skill') or {}).get('naive_rw'))}</td><td>{_sk((v.get('skill') or {}).get('naive_cagr'))}</td>"
                    f"<td>{'n/a' if kb.get(int(k)) is None else format(kb[int(k)], '+.1f')}</td>" if has_m else "") + "</tr>"
                 for k, v in st["by_k"].items())
    mh = ('<th scope="col">Nearest case (bear/base/bull)</th><th scope="col">Skill vs last value</th>'
          '<th scope="col">Skill vs trend</th><th scope="col">Growth bias (pp/yr)</th>' if has_m else "")
    summ = (f'<h3>Summary: {_e(st["line"])} {tag("calculated")}</h3><div class="scroll"><table class="tight"><caption class="small muted">Base-case results by horizon for {_e(st["line"])}. '
            f'Rows share realised years, so they are not independent.</caption><thead><tr><th class="l" scope="col">Horizon</th><th scope="col">Checks</th>'
            f'<th scope="col">In band (ref. {REF * 100:.0f}%)</th><th scope="col">Median miss{" (pp)" if m_line else ""}</th>{mh}</tr></thead><tbody>{ks}</tbody></table></div>')
    if has_m:
        summ += ('<p class="small muted">Skill = 1 - (median miss of the base case / median miss of the naive guess); above 0 means ARIA beat it. Growth bias = base-case growth minus realised growth '
                 '(positive = too optimistic). Nearest case = which scenario ended closest to the reported figure (even odds would be 25/50/25). Error figures are typical sizes, with no direction.</p>')
        mg = (sb.get("extra") or {}).get("margin") or {}
        if mg:
            summ += ('<p class="small">EBITDA margin, base minus reported (percentage points): ' + "; ".join(f"{k} yr {v:+.1f}" for k, v in sorted(mg.items()) if v is not None) + '.</p>')
    pc = ""
    if sb.get("percentiles"):
        pc = f"<p class='small'>Compared with other companies backtested: {_e(_pct_text(sb['percentiles']))}.</p>"
    fig = _svg_fan(fan, f"{fan['line'].upper() if fan['line'] in ('eps', 'dps') else fan['line'].capitalize()}: reported history, latest scenario fan and earlier base paths")
    trs = []
    for r in rows:
        if r["k"] not in SHOW_K:
            continue
        ln = r["line"]
        trs.append([_e(ln.upper() if ln in ("eps", "dps") else ln.capitalize()), _e(f"FY{_year(r['origin'])}" + (" (short history)" if r.get("short") else "")), str(r["k"]),
                    _val(ln, r["bear"]), _val(ln, r["base"]), _val(ln, r["bull"]), _val(ln, r["actual"]), "yes" if r["in_band"] else "no", _errtxt(ln, r["err"])])
    unit = "" if model == "ddm" else " (INR crore; margin in %)"
    tbl = (_table(["Line", "Origin", "Years ahead", "Bear", "Base", "Bull", f"Actual {tag('actual')}", "Actual inside band", "Base error"], trs, cls="tight")
           .replace("<table", f'<table aria-describedby="sbt-cap"', 1) if trs else '<p class="na">No year after an origin has been reported yet, so nothing can be compared.</p>')
    cap = (f'<p id="sbt-cap" class="small muted">Each row: the projection for fiscal year origin + years ahead, made at the origin, against the reported figure{_e(unit)}. '
           f'Base error is (base - actual) / actual, in percentage points for margin. Years ahead other than 1, 3 and 5 are scored in the summary but not listed.</p>')
    return (head + note + banner + extra + summ + pc + "<h3>Scenario fan</h3>" + fig + f"<h3>Projection vs reported {tag('calculated')}</h3>" + cap + tbl
            + f'<h3>Limitations</h3><p class="small">{_e(LIMITS)}</p></section>')


# ── Markdown ───────────────────────────────────────────────────────────────
def md_section(report: dict) -> str:
    sb = report.get("scenario_backtest")
    if not sb:
        return ""
    out = ["## Historical backtest of these scenarios", "", "_Produced by code, not by the language model._", ""]
    if sb.get("status") != "ok":
        return "\n".join(out + [f"**{sb.get('status', 'not_run').replace('_', ' ').capitalize()}.** {_status_text(sb)}", "", "### Limitations", "", LIMITS, ""])
    t = lambda cols, rows: "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"  # noqa: E731
    out += [_sentence(sb), ""] + ([f"Compared with other companies backtested: {_pct_text(sb['percentiles'])}.", ""] if sb.get("percentiles") else []) + ([f"Statements from: {sb['source']}.", ""] if sb.get("source") else [])
    if sb.get("n_short_origins"):
        out += [f"{sb['n_short_origins']} origin(s) had only 2-3 fiscal years of history (marked short history); " + ("the summary rests on them alone." if sb.get("short_only") else "they are excluded from the summary."), ""]
    out += [t(["Line", "Origin", "Years ahead", "Bear", "Base", "Bull", "Actual", "In band", "Base error"],
              [[r["line"], f"FY{_year(r['origin'])}" + (" (short history)" if r.get("short") else ""), str(r["k"]), _val(r["line"], r["bear"]), _val(r["line"], r["base"]), _val(r["line"], r["bull"]), _val(r["line"], r["actual"]),
                "yes" if r["in_band"] else "no", _errtxt(r["line"], r["err"])] for r in sb["rows"] if r["k"] in SHOW_K]), "### Limitations", "", LIMITS, ""]
    return "\n".join(out)
