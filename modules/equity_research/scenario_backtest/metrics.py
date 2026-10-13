"""Owner: scenario backtest WP3. Scores the frozen forecasts of engine.run_company against what was reported later.

Error convention: level lines (revenue, ebitda, fcf, eps, dps) use e = ln(F/A) (undefined, and counted, when F<=0 or
A<=0); the margin line uses e = (F-A) in percentage points. Rows flagged span_excluded, structural_break or share_basis
and rows with a NaN actual are left out of the headline cells (counted under "excluded"; structural_break is also
scored separately). FCF is indicative only (flag fcf_not_comparable): it is reported but never sliced or recommended on.
Price/value convergence is NOT proof of forecast accuracy.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from modules.equity_research.forecast.metrics import smape
from modules.equity_research.forecast.universe import _boot_median_ci

MIN_COMPANIES = 30      # universe cells with fewer companies are suppressed
MIN_ORIGINS_CI = 5      # per-company CI needs this many observations
N_BOOT, CI = 2000, 0.90
CAPTION = "Price convergence is not proof of forecast accuracy."
BAND_REFERENCE = "68% (reference only: scenario coverage, not a calibration target; the bear/bull cases carry no stated probability, and their spread equals ARIA's own Monte Carlo sigma, roughly +-1 sigma)"
CASES3 = ("bear", "base", "bull")
ALL_CASES = CASES3 + ("weighted", "naive_rw", "naive_cagr", "naive_mr")
NAIVE = ("naive_rw", "naive_cagr", "naive_mr")
HEADLINE = {"dcf": ("revenue", "ebitda", "margin"), "ddm": ("eps", "dps")}
INDICATIVE = ("fcf",)
GROWTH_LINES = {"revenue", "eps"}
EXPECTED_NEAREST = {"bear": .25, "base": .5, "bull": .25}
SKIP_FLAGS = ("span_excluded", "structural_break", "share_basis")
KS = range(1, 9)         # k = 9, 10 can never be validated with this source


# ── helpers ───────────────────────────────────────────────────────────────
def _fin(x):
    return None if x is None or not np.isfinite(x) else float(x)


def _med(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(np.median(x)) if len(x) else None


def _boot(groups: list[np.ndarray], stat: str = "median", n_boot: int = N_BOOT, seed: int = 0):
    """Cluster bootstrap over companies (resample whole companies, pool their values); (est, lo, hi) at 90%, seeded."""
    groups = [np.asarray(g, float)[np.isfinite(g)] for g in groups]
    groups = [g for g in groups if len(g)]
    if not groups:
        return None
    v = np.concatenate(groups)
    gid = np.concatenate([np.full(len(g), i) for i, g in enumerate(groups)])
    order = np.argsort(v, kind="stable")
    v, gid = v[order], gid[order]
    est = float(np.median(v)) if stat == "median" else float(v.mean())
    G = len(groups)
    counts = np.random.default_rng(seed).multinomial(G, np.full(G, 1 / G), size=n_boot)
    out = np.empty(n_boot)
    for s in range(0, n_boot, 100):
        W = counts[s:s + 100][:, gid].astype(float)
        tot = W.sum(1)
        if stat == "median":
            pos = (np.cumsum(W, 1) >= tot[:, None] / 2).argmax(1)
            out[s:s + 100] = v[pos]
        else:
            out[s:s + 100] = (W * v).sum(1) / tot
    a = (1 - CI) / 2
    return est, float(np.quantile(out, a)), float(np.quantile(out, 1 - a))


def _ci(w: pd.DataFrame, col: str, stat: str = "median"):
    """{'est','lo','hi'} or None. One company: seeded origin bootstrap (median only, >= 5 obs); universe: cluster bootstrap."""
    d = w[["symbol", col]].dropna()
    if d.symbol.nunique() == 1:
        r = _boot_median_ci(d[col].tolist()) if stat == "median" else None
    elif d.symbol.nunique() >= MIN_COMPANIES:
        r = _boot([g[col].to_numpy() for _, g in d.groupby("symbol")], stat)
    else:
        r = None
    return None if r is None else {"est": r[0], "lo": r[1], "hi": r[2]}


def _flags(s) -> set:
    return set(s.split(",")) if isinstance(s, str) and s else set()


# ── the scored frame ──────────────────────────────────────────────────────
def scored(f: pd.DataFrame, o: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One row per (symbol, origin, line, k): forecast per case, actual, errors, origin attributes. Plus exclusion counts."""
    cols = ["symbol", "origin_fy", "line", "k", "actual", "flags"]
    d = f[f["line"].notna() & (f["k"] >= 1)].copy()
    excl = {"nan_actual": 0, "span_excluded": 0, "structural_break": 0, "share_basis": 0, "short_history": 0}
    if d.empty:
        return pd.DataFrame(columns=cols + list(ALL_CASES) + ["structural_break", "short_history", "growth_cap", "fcf_indicative", "rev_a", "e_base", "provider"]), excl
    d["flags"] = d["flags"].fillna("")
    d["actual"] = d["actual"].fillna(-np.inf)  # pivot_table drops NaN index keys; restore below
    w = d.pivot_table(index=cols, columns="case", values="forecast", aggfunc="first").reset_index()
    w["actual"] = w["actual"].replace(-np.inf, np.nan)
    for c in ALL_CASES:
        if c not in w:
            w[c] = np.nan
    fl = w["flags"].map(_flags)
    for r in SKIP_FLAGS:
        excl[r] = int(fl.map(lambda s: r in s).sum())
    excl["nan_actual"] = int(w.actual.isna().sum())
    w["structural_break"] = fl.map(lambda s: "structural_break" in s)
    w["short_history"] = fl.map(lambda s: "short_history" in s)  # 2-3 fiscal years at T: own slice, never in headline cells
    excl["short_history"] = int(w.short_history.sum())
    w["growth_cap"] = fl.map(lambda s: "growth_cap" in s)
    w["fcf_indicative"] = w["line"].isin(INDICATIVE)
    w = w[w.actual.notna() & ~fl.map(lambda s: "span_excluded" in s or "share_basis" in s).reindex(w.index)].copy()
    rev = w.loc[w.line == "revenue", ["symbol", "origin_fy", "k", "actual"]].rename(columns={"actual": "rev_a"})
    w = w.merge(rev, on=["symbol", "origin_fy", "k"], how="left")
    o = o.assign(provider=o["provider"] if "provider" in o else "screener.in")  # results written before sb2 have no column
    w = w.merge(o[["symbol", "origin_fy", "sector", "size_bucket", "g1", "model", "provider"]].drop_duplicates(["symbol", "origin_fy"]),
                on=["symbol", "origin_fy"], how="left")
    w["provider"] = w["provider"].fillna("screener.in")
    A = w.actual.to_numpy(float)
    marg = (w.line == "margin").to_numpy()
    for c in ALL_CASES:
        F = w[c].to_numpy(float)
        with np.errstate(all="ignore"):
            e = np.where((F > 0) & (A > 0), np.log(F / A), np.nan)
        w["e_" + c] = np.where(marg, (F - A) * 100, e)
    w["undefined"] = ~marg & ~((w["base"] > 0) & (w.actual > 0))
    # growth diagnostics: forecast CAGR vs realised CAGR from the last actual (= the random-walk forecast), in pp
    with np.errstate(all="ignore"):
        a0, k = w["naive_rw"].to_numpy(float), w["k"].to_numpy(float)
        ok = (a0 > 0) & (A > 0) & (w["base"].to_numpy(float) > 0) & w.line.isin(GROWTH_LINES).to_numpy()
        w["growth_err_pp"] = np.where(ok, ((w["base"] / a0) ** (1 / k) - (A / a0) ** (1 / k)) * 100, np.nan)
    return w, excl


# ── one (line, k) cell ────────────────────────────────────────────────────
def _nearest(w: pd.DataFrame) -> dict | None:
    t = w.dropna(subset=list(CASES3))
    if t.empty:
        return None
    F = t[list(CASES3)].to_numpy(float)
    A = t.actual.to_numpy(float)[:, None]
    use_log = (F > 0).all(1) & (A[:, 0] > 0)
    with np.errstate(all="ignore"):
        dist = np.where(use_log[:, None], np.abs(np.log(F / A)), np.abs(F - A))
    win = np.array(CASES3)[dist.argmin(1)]
    return {"n": len(t), **{c: float((win == c).mean()) for c in CASES3}, "expected": EXPECTED_NEAREST}


def _band(w: pd.DataFrame, ci: bool) -> dict | None:
    t = w.dropna(subset=["bear", "bull"])
    if t.empty:
        return None
    lo, hi = np.minimum(t.bear, t.bull), np.maximum(t.bear, t.bull)
    below, above = t.actual < lo, t.actual > hi
    t = t.assign(inside=(~below & ~above).astype(float))
    with np.errstate(all="ignore"):
        width = np.where((t.bear > 0) & (t.bull > 0), np.log(np.maximum(t.bear, t.bull) / np.minimum(t.bear, t.bull)), np.nan)
    out = {"n": len(t), "below": float(below.mean()), "inside": float(t.inside.mean()), "above": float(above.mean()),
           "median_width_log": _med(width), "reference": BAND_REFERENCE}
    if ci:
        out["inside_ci90"] = _ci(t, "inside", "mean")
    return out


def _skill(w: pd.DataFrame, line: str) -> dict:
    out = {}
    for nv in (("naive_mr", "naive_rw") if line == "margin" else ("naive_rw", "naive_cagr")):
        t = w.dropna(subset=["e_base", "e_" + nv])
        den = float(np.median(np.abs(t["e_" + nv]))) if len(t) else 0
        out[nv] = {"n": len(t), "skill": (1 - float(np.median(np.abs(t.e_base))) / den) if den > 0 else None}
    return out


def _cell(w: pd.DataFrame, line: str, ci: bool = True) -> dict:
    """Metrics of one (line, k) slice. ``w`` holds that slice only."""
    b = w.dropna(subset=["e_base"])
    unit = "pp" if line == "margin" else "log"
    c = {"n_obs": len(w), "n_companies": int(w.symbol.nunique()), "n_undefined": int(w.undefined.sum()), "unit": unit,
         "n_eff": float(len(w) / w.k.iloc[0]) if len(w) else 0.0}
    c["base"] = {"n": len(b), "bias": _med(b.e_base), "median_abs_e": _med(np.abs(b.e_base)),
                 "smape_pct": smape(b.actual, b.base) if len(b) else None,
                 "bias_ci90": _ci(b, "e_base") if ci else None}
    if line in ("ebitda", "fcf"):
        s = ((w["base"] - w.actual) / w.rev_a).replace([np.inf, -np.inf], np.nan)
        c["base"]["median_scaled_by_revenue"] = _med(s)
    c["cases"] = {n: {"n": int(w["e_" + n].notna().sum()), "bias": _med(w["e_" + n]), "median_abs_e": _med(np.abs(w["e_" + n]))}
                  for n in ALL_CASES if w["e_" + n].notna().any()}
    c["band"], c["nearest"] = _band(w, ci), _nearest(w)
    c["skill"] = _skill(w, line)
    return c


def _lines(w: pd.DataFrame, ci: bool = True, universe: bool = False) -> dict:
    out: dict = {}
    for line, wl in w.groupby("line"):
        out[line] = {"indicative": line in INDICATIVE, "k": {}}
        for k, wk in wl.groupby("k"):
            if universe and wk.symbol.nunique() < MIN_COMPANIES:
                out[line]["k"][int(k)] = {"suppressed": True, "n_companies": int(wk.symbol.nunique()),
                                          "reason": f"fewer than {MIN_COMPANIES} companies"}
            else:
                out[line]["k"][int(k)] = _cell(wk, line, ci and line not in INDICATIVE)
    return out


def _growth(w: pd.DataFrame, ci: bool) -> dict:
    g = w[w.growth_err_pp.notna() & (w.base > 0)]
    out = {"note": "forecast CAGR (base) minus realised CAGR, from the last reported year, in pp; revenue (DCF) or EPS (DDM)", "k": {}}
    for k, t in g.groupby("k"):
        out["k"][int(k)] = {"n": len(t), "bias_pp": _med(t.growth_err_pp), "bias_ci90": _ci(t, "growth_err_pp") if ci else None,
                            "growth_cap_share": float(t.growth_cap.mean()),
                            "bias_pp_when_capped": _med(t.growth_err_pp[t.growth_cap]),
                            "bias_pp_when_not_capped": _med(t.growth_err_pp[~t.growth_cap])}
    return out


# ── price vs value ────────────────────────────────────────────────────────
def _price(o: pd.DataFrame, universe: bool = False) -> dict:
    d = o[o.v_base.notna() & (o.p0 > 0) & (o.v_base > 0)].copy()
    out = {"caption": CAPTION, "n_origins": len(d), "k": {}}
    if d.empty:
        return out
    d["gap"] = np.log(d.v_base / d.p0)
    out["valuation_gap_median"], out["valuation_gap_median_abs"] = _med(d.gap), _med(np.abs(d.gap))
    out["implied_return_median"] = {n: _med(d["v_" + n] / d.p0 - 1) for n in ("bear", "base", "bull", "weighted")}
    out["implied_return_note"] = "V_case/P0 - 1, assuming full convergence by horizon k with no value accretion"
    for k in KS:
        t = d[d[f"p_k{k}"] > 0]
        if t.empty:
            continue
        pk = t[f"p_k{k}"]
        lo, hi = np.minimum(t.v_bear, t.v_bull), np.maximum(t.v_bear, t.v_bull)
        has = t.v_bear.notna() & t.v_bull.notna()
        conv = np.abs(np.log(pk / t.v_base)) < np.abs(np.log(t.p0 / t.v_base))
        cell = {"n": len(t), "price_in_bear_bull": float(((pk >= lo) & (pk <= hi))[has].mean()) if has.any() else None,
                "converged_toward_base": float(conv.mean()), "median_total_return": _med(t[f"tr_k{k}"])}
        if universe:
            cs = []
            for fy, y in t.assign(g=t.gap, r=t[f"tr_k{k}"]).dropna(subset=["g", "r"]).groupby("origin_fy"):
                if y.symbol.nunique() >= MIN_COMPANIES:
                    cs.append(y.g.corr(y.r, method="spearman"))
            cs = np.array([x for x in cs if x == x])
            cell["rank_corr_gap_vs_return"] = ({"years": len(cs), "mean": float(cs.mean()),
                                                "t_stat": float(cs.mean() / (cs.std(ddof=1) / math.sqrt(len(cs)))) if len(cs) >= 3 and cs.std(ddof=1) > 0 else None}
                                               if len(cs) else None)
        out["k"][k] = cell
    return out


# ── public API ────────────────────────────────────────────────────────────
def company_summary(f: pd.DataFrame, o: pd.DataFrame) -> dict:
    """summary.json for one company (f, o = engine.run_company output)."""
    w, excl = scored(f, o)
    st = (f.attrs or {}).get("status") or ("ok" if len(o) else "insufficient_history")
    refused = sorted(set(o.loc[o.refused_reason.fillna("") != "", "refused_reason"])) if len(o) else []
    s = {"symbol": (o.symbol.iloc[0] if len(o) else (f.symbol.iloc[0] if len(f) else None)), "status": st,
         "model": (o.model.iloc[0] if len(o) else None), "sector": (o.sector.iloc[0] if len(o) else None),
         "size_bucket": (o.size_bucket.iloc[-1] if len(o) else None), "n_origins": int(len(o)),
         "n_origins_refused": int((o.refused_reason.fillna("") != "").sum()) if len(o) else 0, "refused_reasons": refused,
         "excluded": excl, "max_validated_k": int(w.k.max()) if len(w) else 0,
         "k_note": "k = 9 and 10 can never be validated with this data source (12 fiscal years)", "fcf_note": "FCF is indicative only",
         "ci_note": f"CI only with >= {MIN_ORIGINS_CI} observations", "caption": CAPTION}
    main = w[~w.structural_break & ~w.short_history]
    s["lines"] = _lines(main, universe=False) if len(main) else {}
    sb = w[w.structural_break & ~w.short_history & w.e_base.notna() & (w.line != "fcf")]
    s["structural_break"] = {"n": len(sb), "median_abs_e": _med(np.abs(sb.e_base))}
    s["growth"] = _growth(main, True) if len(main) else {"k": {}}
    short_o = _short_o(o)
    s["price"] = _price(o[~short_o])
    sh = w[w.short_history & ~w.structural_break]
    s["short_history"] = {"n_origins": int(short_o.sum()), "n_rows": len(sh), "note": "origins with 2-3 fiscal years at T; reported apart from the headline cells",
                          "lines": _lines(sh, universe=False) if len(sh) else {}, "growth": _growth(sh, True) if len(sh) else {"k": {}},
                          "price": _price(o[short_o]) if short_o.any() else None}
    return s


def medabs_primary(m: dict | None) -> float | None:
    """Typical size of the base-case miss: median over k = 1..5 of the primary line's median |log error| (revenue, or EPS for banks)."""
    try:
        line = "eps" if m.get("model") == "ddm" else "revenue"
        v = [c["base"]["median_abs_e"] for k, c in m["lines"][line]["k"].items() if int(k) <= 5 and not c.get("suppressed") and c["base"].get("median_abs_e") is not None]
        return float(np.median(v)) if v else None
    except Exception:  # noqa: BLE001
        return None


def _short_o(o: pd.DataFrame) -> pd.Series:
    return o["flags"].fillna("").map(lambda s: "short_history" in _flags(s)) if len(o) else pd.Series([], dtype=bool)


def _slice_stats(w: pd.DataFrame, o_slice: pd.DataFrame | None = None) -> dict:
    """Pooled (k = 1..5) bias / coverage of one slice, headline lines only."""
    n_co = int(w.symbol.nunique())
    if n_co < MIN_COMPANIES:
        return {"suppressed": True, "n_companies": n_co, "reason": f"fewer than {MIN_COMPANIES} companies"}
    w = w[(w.k <= 5) & ~w.line.isin(INDICATIVE)]
    g, m = w[w.growth_err_pp.notna()], w[(w.line == "margin") & w.e_base.notna()]
    b = _band(w[w.line.isin(("revenue", "eps"))], True)
    return {"n_companies": n_co, "growth_bias_pp": {"n": len(g), "n_companies": int(g.symbol.nunique()), "ci": _ci(g, "growth_err_pp")} if len(g) else None,
            "margin_bias_pp": {"n": len(m), "n_companies": int(m.symbol.nunique()), "ci": _ci(m, "e_base")} if len(m) else None,
            "band": {"n": b["n"], "inside": b["inside"], "ci": b["inside_ci90"]} if b else None}


def aggregate(all_f: pd.DataFrame, all_o: pd.DataFrame) -> dict:
    """Universe summary from the concatenated forecasts / origins of every company."""
    w, excl = scored(all_f, all_o)
    out = {"n_companies": int(all_o.symbol.nunique()) if len(all_o) else 0, "n_origins": int(len(all_o)),
           "n_companies_scored": int(w.symbol.nunique()) if len(w) else 0, "min_companies_per_cell": MIN_COMPANIES,
           "ci": f"{int(CI * 100)}% cluster bootstrap over companies, {N_BOOT} resamples, seed 0", "caption": CAPTION,
           "band_reference": BAND_REFERENCE, "excluded": excl,
           "limits": ["k = 9, 10 can never be validated with this source", "overlapping origins share realised years: effective n ~ n_origins / k",
                      "today's listings only (survivorship), restated history, single source (screener.in), today's FI_* settings and sector labels",
                      "FCF is indicative only"]}
    if w.empty:
        short_o = _short_o(all_o)
        return {**out, "lines": {}, "growth": {"k": {}}, "price": _price(all_o[~short_o], True), "by_sector": {}, "by_size": {}, "by_g1": {}, "by_origin_year": {},
                "by_provider": {}, "short_history": {"n_companies": 0, "n_origins": int(short_o.sum()), "lines": {}, "overall": None, "price": None}}
    main = w[~w.structural_break & ~w.short_history]
    out["lines"] = _lines(main, universe=True)
    out["growth"] = _growth(main, True)
    sb = w[w.structural_break & ~w.short_history & w.e_base.notna() & ~w.fcf_indicative]
    out["structural_break"] = {"n": len(sb), "median_abs_e": _med(np.abs(sb.e_base))}
    short_o = _short_o(all_o)
    out["price"] = _price(all_o[~short_o], True)
    sh = w[w.short_history & ~w.structural_break]
    out["short_history"] = {"n_companies": int(sh.symbol.nunique()), "n_origins": int(short_o.sum()),
                            "n_companies_origins": int(all_o.loc[short_o, "symbol"].nunique()) if short_o.any() else 0,
                            "lines": _lines(sh, universe=True) if len(sh) else {}, "overall": _slice_stats(sh[~sh.fcf_indicative]) if len(sh) else None,
                            "price": _price(all_o[short_o], True) if short_o.any() else None}
    head = main[~main.fcf_indicative]
    out["overall"] = _slice_stats(head)
    out["by_provider"] = {str(name): _slice_stats(t) for name, t in head.groupby("provider")}
    g1b = pd.cut(head.g1, [-np.inf, .08, .15, np.inf], labels=["g1<8%", "g1 8-15%", "g1>=15%"]).astype(object)
    for key, col in (("by_sector", head.sector), ("by_size", head.size_bucket), ("by_g1", g1b)):
        out[key] = {str(name): _slice_stats(t) for name, t in head.groupby(col.fillna("")) if name != ""}
    oy = {}
    for fy, t in head[head.k.isin((1, 3))].groupby("origin_fy"):
        oy[fy] = {}
        for (line, k), x in t.groupby(["line", "k"]):
            nc = int(x.symbol.nunique())
            oy[fy][f"{line}_k{k}"] = ({"suppressed": True, "n_companies": nc} if nc < MIN_COMPANIES
                                      else {"n_companies": nc, "bias": _med(x.e_base), "median_abs_e": _med(np.abs(x.e_base))})
    out["by_origin_year"] = oy
    return out


def recommendations(agg: dict, sector: str | None = None) -> list[str]:
    """Rule-based text; only when >= 30 companies and the 90% CI excludes zero (coverage: lies beyond the threshold)."""
    s = (agg.get("by_sector") or {}).get(sector) if sector else agg.get("overall")
    if not s or s.get("suppressed"):
        return []
    where, out = sector or "the whole universe", []

    def txt(d):
        c = d["ci"]
        return f"n={d['n_companies']} companies, 90% CI {c['lo']:+.1f} to {c['hi']:+.1f}"

    g = s.get("growth_bias_pp")
    if g and g["ci"] and g["n_companies"] >= MIN_COMPANIES and abs(g["ci"]["est"]) > 2 and (g["ci"]["lo"] > 0 or g["ci"]["hi"] < 0):
        d = g["ci"]["est"]
        out.append(f"Historically ARIA's base growth {'exceeded' if d > 0 else 'fell short of'} realised growth by {abs(d):.1f} pp a year in {where} ({txt(g)}).")
    m = s.get("margin_bias_pp")
    if m and m["ci"] and m["n_companies"] >= MIN_COMPANIES and abs(m["ci"]["est"]) > 1 and (m["ci"]["lo"] > 0 or m["ci"]["hi"] < 0):
        d = m["ci"]["est"]
        out.append(f"Historically ARIA's base EBITDA margin was {abs(d):.1f} pp {'above' if d > 0 else 'below'} the reported margin in {where} ({txt(m)}).")
    b = s.get("band")
    if b and b["ci"] and s["n_companies"] >= MIN_COMPANIES:
        c = b["ci"]
        if c["hi"] < .40:
            out.append(f"Scenario coverage: the reported figure fell between the bear and bull cases only {100 * b['inside']:.0f}% of the time in {where} (90% CI {100 * c['lo']:.0f}-{100 * c['hi']:.0f}%); the cases are a roughly +-1 sigma scenario range, not a stated-probability interval.")
        elif c["lo"] > .90:
            out.append(f"Scenario coverage: the reported figure fell between the bear and bull cases {100 * b['inside']:.0f}% of the time in {where} (90% CI {100 * c['lo']:.0f}-{100 * c['hi']:.0f}%); the cases were wider than needed.")
    return out
