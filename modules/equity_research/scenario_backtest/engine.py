"""Owner: scenario backtest WP2. Rebuild ARIA's bear/base/bull cases as of a past fiscal year-end T using ONLY data public
by then (T + 90 days), by running ARIA's own unchanged analyze / value_company / scenario_detail code on a truncated
Snapshot, then line the cases up with what the company reported later. valuation.py is never touched.

Known leaks / simplifications (also listed in the report): sector/industry labels are today's (used only for the
bank / non-bank split and the peer group name); FI_* settings (risk-free, ERP, terminal growth) are today's; with the
TTM column removed the revenue base is FY_T, so projection year i is FY T+i (the code's own fallback path).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
from loguru import logger

from modules.equity_research.intelligence import valuation as V
from modules.equity_research.intelligence.analysis import analyze, cagr
from modules.equity_research.intelligence.data import Snapshot, Target, _aligned_weekly_returns, _peer_group, row
from modules.equity_research.intelligence.facts import Ledger

from . import ENGINE_VERSION, data
from .data import fye

AVAIL_LAG_DAYS = 90
Q_LAG_DAYS = 45
BETA_WEEKS = 260
HORIZONS = 10
PRICE_KS = 8
CASES = {"bear": -1, "base": 0, "bull": 1}
ROW_COLUMNS = ["symbol", "origin_fy", "avail_date", "model", "refused_reason", "line", "k", "case", "forecast", "actual", "flags"]
ORIGIN_COLUMNS = (["symbol", "origin_fy", "avail_date", "p0", "v_bear", "v_base", "v_bull", "v_weighted", "g1", "margin", "wacc_or_coe",
                   "tg", "sector", "size_bucket"] + [f"p_k{k}" for k in range(1, PRICE_KS + 1)] + [f"tr_k{k}" for k in range(1, PRICE_KS + 1)]
                  + ["model", "refused_reason", "mcap_cr", "flags", "provider", "n_years"])  # last six: additions to the spec's list
DCF_LINES = ("revenue", "ebitda", "margin", "fcf")
DDM_LINES = ("eps", "dps")


class NoOrigin(Exception):
    """This fiscal year cannot be an origin (no price yet, too little history...)."""


def avail_date(fy_col: str) -> date:
    return fye(fy_col) + timedelta(days=AVAIL_LAG_DAYS)


# ── point-in-time snapshot ────────────────────────────────────────────────
def _first_on_or_after(px: pd.DataFrame, d: date) -> tuple[pd.Timestamp, float, float] | None:
    i = px.index.searchsorted(pd.Timestamp(d))
    if i >= len(px):
        return None
    return px.index[i], float(px["close"].iloc[i]), float(px["adj_close"].iloc[i])


def _asof(px: pd.DataFrame, d: date) -> tuple[float, float] | None:
    """(close, adj_close) on the last trading day on or before d; None when d is past the last bar or before the first."""
    ts = pd.Timestamp(d)
    if px.empty or ts > px.index[-1] or ts < px.index[0]:
        return None
    r = px.loc[:ts].iloc[-1]
    return float(r["close"]), float(r["adj_close"])


def _weekly(s: pd.Series) -> list[tuple[str, float]]:
    w = s.resample("W-FRI").last().dropna()
    return [(i.strftime("%Y-%m-%d"), float(v)) for i, v in w.items()]


def as_of_snapshot(tables: dict, meta: dict, px: pd.DataFrame, nifty: pd.Series, fy_col: str) -> Snapshot:
    """Snapshot of what was public at fiscal year-end ``fy_col`` + AVAIL_LAG_DAYS. Raises NoOrigin if no price exists."""
    T = fye(fy_col)
    A = T + timedelta(days=AVAIL_LAG_DAYS)
    cut: dict[str, dict] = {}
    for t in data.FY_TABLES:
        tb = tables.get(t)
        if not tb:
            continue
        cols = [c for c in tb["cols"] if (d := data._parse(c)) and d <= T]
        cut[t] = {"cols": cols, "rows": {r: {c: v.get(c) for c in cols} for r, v in tb["rows"].items()}}
    q = tables.get("quarterly")
    if q:
        cols = [c for c in q["cols"] if (d := data._parse(c)) and d + timedelta(days=Q_LAG_DAYS) <= A]
        cut["quarterly"] = {"cols": cols, "rows": {r: {c: v.get(c) for c in cols} for r, v in q["rows"].items()}}
    pl = cut.get("pl", {"cols": [], "rows": {}})
    np_, eps = row(pl, "Net Profit").get(fy_col), row(pl, "EPS in Rs").get(fy_col)
    hit = _first_on_or_after(px, A)
    if hit is None:
        raise NoOrigin(f"no_price: price history ends {px.index[-1].date()}, before the availability date {A}")
    day, price, _ = hit
    if px.index[0] > pd.Timestamp(A):
        raise NoOrigin(f"no_price: first price bar {px.index[0].date()} is after the availability date {A}")  # IPO after A_T
    if day - pd.Timestamp(A) > pd.Timedelta(days=10):
        raise NoOrigin(f"no_price: no bar within 10 days of the availability date {A} (next {day.date()})")  # suspension
    info: dict = {"currentPrice": price, "sector": meta.get("sector"), "industry": meta.get("industry"), "longName": meta.get("symbol")}
    if np_ and eps and np_ > 0 and eps > 0:
        shares = np_ / eps * 1e7
        info.update(sharesOutstanding=shares, marketCap=price * shares)
    borrow = row(cut.get("bs", {}), "Borrowings", "Borrowing").get(fy_col)
    if borrow is not None:
        info["totalDebt"] = borrow * 1e7  # no cash field: net debt falls back to borrowings (the code's conservative path)
    hist = px.loc[: pd.Timestamp(A), "adj_close"].iloc[-(BETA_WEEKS * 7 + 7):]
    stock_w, index_w = _weekly(hist)[-(BETA_WEEKS + 1):], _weekly(nifty.loc[: pd.Timestamp(A)])
    s_ret, i_ret = _aligned_weekly_returns(stock_w, index_w)
    sym = meta.get("symbol", "X.NS")
    return Snapshot(
        target=Target(sym.rsplit(".", 1)[0], sym, sym), as_of=A.isoformat(), view=meta.get("view", "consolidated"), tables=cut,
        info=info, is_financial=bool(meta.get("is_financial")), stock_returns=s_ret[-BETA_WEEKS:], index_returns=i_ret[-BETA_WEEKS:],
        closes=[c for _, c in stock_w], peers=[], peer_group=_peer_group(meta.get("sector"), meta.get("industry")))


# ── one origin ────────────────────────────────────────────────────────────
def _num(x) -> float:
    return float(x) if isinstance(x, (int, float)) and math.isfinite(x) else math.nan


def _actual_series(tables: dict, bank: bool) -> dict[str, dict[str, float]]:
    """Reported lines by fiscal-year column, from the FULL clean tables (the outcome side; never seen by the model)."""
    pl, cf = tables["pl"], tables.get("cf", {"rows": {}})
    rev = row(pl, "Sales", "Revenue")
    out: dict[str, dict] = {}
    if bank:
        eps, pay = row(pl, "EPS in Rs"), row(pl, "Dividend Payout %")
        out["eps"] = {c: eps.get(c) for c in pl["cols"]}
        out["dps"] = {c: (eps[c] * pay[c] / 100 if eps.get(c) is not None and pay.get(c) is not None else None) for c in pl["cols"]}
        return out
    op = row(pl, "Operating Profit")
    out["revenue"] = {c: rev.get(c) for c in pl["cols"]}
    out["ebitda"] = {c: op.get(c) for c in pl["cols"]}
    out["margin"] = {c: (op[c] / rev[c] if op.get(c) is not None and rev.get(c) else None) for c in pl["cols"]}
    fcf = row(cf, "Free Cash Flow")
    out["fcf"] = {c: fcf.get(c) for c in pl["cols"]}
    return out


def _span_hit(spans: list[dict], lo: date, hi: date) -> bool:
    return any(s["end"] > lo and s["start"] < hi for s in spans)


def run_origin(symbol: str, tables: dict, meta: dict, px: pd.DataFrame, nifty: pd.Series, fy_col: str, *,
               full: dict | None = None, exclusions: dict | None = None) -> tuple[list[dict], dict]:
    """(forecast rows, origins row) for one origin. ``tables`` is the cleaned set; ``full`` defaults to it (outcomes)."""
    full = full or tables
    exclusions = exclusions or {"company": [], "spans": [], "flags": {}}
    meta = {**meta, "symbol": symbol}
    snap = as_of_snapshot(tables, meta, px, nifty, fy_col)
    T, A = fye(fy_col), avail_date(fy_col)
    bank, model = snap.is_financial, ("ddm" if snap.is_financial else "dcf")
    base_row = {"symbol": symbol, "origin_fy": fy_col, "avail_date": A.isoformat(), "model": model}
    n_hist = sum(1 for c in full["pl"]["cols"] if (d := data._parse(c)) and d <= T and row(full["pl"], "Sales", "Revenue").get(c) is not None)
    flags_o = ["short_history"] if n_hist < data.MIN_YEARS else []  # fewer years than a 3y CAGR needs: reported in its own slice
    rows: list[dict] = []
    origin = {c: math.nan for c in ORIGIN_COLUMNS}
    day, p0, adj0 = _first_on_or_after(px, A)
    origin.update(symbol=symbol, origin_fy=fy_col, avail_date=A.isoformat(), p0=p0, model=model, refused_reason="",
                  sector=_peer_group(meta.get("sector"), meta.get("industry")) or meta.get("sector") or "", flags=",".join(flags_o),
                  provider=meta.get("provider", "screener.in"), n_years=n_hist,
                  mcap_cr=(snap.market_cap_cr if snap.market_cap_cr else math.nan))
    mc = origin["mcap_cr"]
    origin["size_bucket"] = "" if mc != mc else ("small" if mc < 5_000 else "mid" if mc < 50_000 else "large")
    for k in range(1, PRICE_KS + 1):  # realised prices: the outcome side, never fed to the model
        later = _asof(px, A + timedelta(days=365 * k))
        if later:
            origin[f"p_k{k}"], origin[f"tr_k{k}"] = later[0], later[1] / adj0 - 1

    def refuse(reason: str, case: str | None = None):
        rows.append({**base_row, "refused_reason": reason, "line": None, "k": 0, "case": case, "forecast": math.nan, "actual": math.nan, "flags": ",".join(flags_o)})
        if case is None:
            origin["refused_reason"] = reason

    an = analyze(snap, Ledger())
    val = V.value_company(snap, an, Ledger())
    inp = val.ddm_inputs if bank else val.dcf_inputs
    if inp is None:
        refuse(val.skipped.get("ddm" if bank else "dcf") or next(iter(val.skipped.values()), "model produced no value"))
        return rows, origin
    detail = {name: (V.ddm_scenario_detail if bank else V.scenario_detail)(inp, d) for name, d in CASES.items()}
    if "reason" in detail["base"]:
        refuse(detail["base"]["reason"])
        return rows, origin
    for name in ("bear", "bull"):
        if "reason" in detail[name]:
            refuse(detail[name]["reason"], name)
            detail.pop(name)
    per_share = {n: d["bridge"]["per_share"] for n, d in detail.items()}
    w = V.SCENARIO_WEIGHTS
    v_weighted = sum(w[n] * per_share[n] for n in w) if all(n in per_share for n in w) else math.nan
    a = detail["base"]["assumptions"]
    origin.update(v_bear=per_share.get("bear", math.nan), v_base=per_share["base"], v_bull=per_share.get("bull", math.nan), v_weighted=v_weighted,
                  g1=a["g1"], margin=a.get("margin", math.nan), wacc_or_coe=a.get("coe", a.get("wacc")), tg=a["terminal_growth"])

    g1 = inp.growth[0]
    if bank and abs(g1 - 0.20) < 1e-12:
        flags_o.append("growth_cap")
    if not bank and abs(g1 - V.GROWTH_CAP) < 1e-12:
        flags_o.append("growth_cap")
    if abs(g1 - inp.terminal_growth) < 1e-12:
        flags_o.append("growth_floor")
    origin["flags"] = ",".join(flags_o)

    actual = _actual_series(full, bank)
    cols = [c for c in full["pl"]["cols"] if (d := data._parse(c)) and d <= T]
    fy_by_date = {data._parse(c): c for c in full["pl"]["cols"] if data._parse(c)}
    spans = exclusions.get("spans", [])

    def naive(line: str, k: int) -> dict[str, float]:
        hist = [actual[line].get(c) for c in cols]
        last = hist[-1] if hist else None
        out: dict[str, float] = {}
        if last is None:
            return out
        out["naive_rw"] = last
        if line == "margin":
            vals = [h for h in hist if h is not None]
            out["naive_mr"] = float(np.mean(vals))
        elif (g := cagr(hist, 3)) is not None:
            out["naive_cagr"] = last * (1 + g) ** k
        return out

    lines = DDM_LINES if bank else DCF_LINES
    for line in lines:
        for k in range(1, HORIZONS + 1):
            target = date(T.year + k, T.month, 1)
            col = next((c for d, c in fy_by_date.items() if (d.year, d.month) == (target.year, target.month)), None)
            flags_k = ["fcf_not_comparable"] if line == "fcf" else []
            act = _num(actual[line].get(col)) if col else math.nan
            if col and _span_hit(spans, T, fye(col)):
                act = math.nan
                flags_k.append("span_excluded")
            if col:
                rs = set()
                for c in [c for c in full["pl"]["cols"] if T < fye(c) <= fye(col)]:
                    rs.update(r for r in exclusions.get("flags", {}).get(c, []) if r != "share_basis" or line in DDM_LINES)
                flags_k += sorted(rs)
            flags = ",".join(flags_o + flags_k)
            series = {n: d["lines"][line][k - 1] for n, d in detail.items()}
            series.update(({"weighted": sum(w[n] * series[n] for n in w)} if all(n in series for n in w) else {}))
            series.update(naive(line, k))
            for case, f in series.items():
                rows.append({**base_row, "refused_reason": "", "line": line, "k": k, "case": case, "forecast": _num(f),
                             "actual": act, "flags": flags})
    return rows, origin


# ── one company ───────────────────────────────────────────────────────────
def short_ok(n_years: int) -> bool:
    return n_years <= data.SHORT_MAX_COMPANY_YEARS


def origin_years(clean: dict, exclusions: dict) -> list[str]:
    """Fiscal-year columns that can be an origin: at least one reported year after T and no excluded span in the five
    years up to T. Full origins have >= 4 years up to T; companies with <= SHORT_MAX_COMPANY_YEARS fiscal years also get
    short-history origins with 2-3 years (the least valuation.py can run on; tagged 'short_history')."""
    cols = [c for c in clean["pl"]["cols"] if row(clean["pl"], "Sales", "Revenue").get(c) is not None]
    first = (data.SHORT_MIN_YEARS if short_ok(len(cols)) else data.MIN_YEARS) - 1
    out = []
    for i, c in enumerate(cols):
        if i < first or i == len(cols) - 1:
            continue
        T = fye(c)
        if not _span_hit(exclusions["spans"], date(T.year - 5, T.month, 1), T):
            out.append(c)
    return out


def run_company(symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(forecasts_df, origins_df) for every feasible origin. Statements come from the cache (fetched once when absent:
    screener.in, then the yfinance fallback). Both frames carry attrs: status ('ok'|'insufficient_history'|'model_refused'),
    reason (why insufficient, with exact year counts), provider, n_years, issues, exclusions, origin_skips."""
    if data.cached(symbol):
        tables, meta = data.load(symbol)
    else:
        tables, meta = data.fetch_tables(symbol.rsplit(".", 1)[0], symbol=symbol)
    clean, issues, excl = data.quality(tables, meta)
    if excl["company"] and meta.get("provider", "screener.in") == "screener.in" and not meta.get("fallback_tried"):
        tables, meta = data.supplement(symbol, tables, meta)  # screener.in has <3 fiscal years: try the yfinance statements once
        clean, issues, excl = data.quality(tables, meta)
    allrows, origins, skips = [], [], {}
    status, reason, price_symbol = "ok", "", None
    n_years = excl.get("n_years", 0)
    if excl["company"] or "pl" not in clean:
        status = "insufficient_history"
        reason = next((i["detail"] for i in issues if i["reason"] == "too_few_years"), "no profit and loss data")
    else:
        px, nifty = data.prices(symbol, meta), fdata_nifty()
        price_symbol = px.attrs.get("price_symbol")
        for c in origin_years(clean, excl):
            try:
                r, o = run_origin(symbol, clean, meta, px, nifty, c, exclusions=excl)
            except NoOrigin as e:
                skips[c] = str(e)
                continue
            except Exception as e:  # one broken year must not sink the company
                logger.warning(f"{symbol} {c}: {type(e).__name__}: {e}")
                skips[c] = f"error: {type(e).__name__}: {e}"
                continue
            allrows += r
            origins.append(o)
        if not origins:
            status = "insufficient_history"
            why = sorted(set(skips.values()))[:2]
            reason = (f"{n_years} fiscal years available; no origin could be built: " + "; ".join(why)) if why else                 f"{n_years} fiscal years available; no origin has a later reported year inside a clean span"
        elif all(o["refused_reason"] for o in origins):
            status = "model_refused"
    f = pd.DataFrame(allrows, columns=ROW_COLUMNS)
    o = pd.DataFrame(origins, columns=ORIGIN_COLUMNS)
    for df in (f, o):
        df.attrs.update(status=status, reason=reason, issues=issues, exclusions=excl, origin_skips=skips, engine=ENGINE_VERSION,
                        provider=meta.get("provider", "screener.in"), view=meta.get("view"), n_years=n_years, price_symbol=price_symbol)
    return f, o


def fdata_nifty() -> pd.Series:
    return data.nifty()
