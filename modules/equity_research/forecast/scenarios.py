"""Owner: WP4. Validate bear/base/bull targets against price evidence.

Pure and deterministic. The fundamental scenarios are never used as labels and the ML forecast is never bent to
match them: this module only lines the two up and says, in plain words, where they agree or disagree.
Analogue frequencies are historical frequencies, not probabilities; ``p_positive`` is left unset.
"""
from __future__ import annotations

import math
from bisect import bisect_right, insort

import numpy as np
import pandas as pd

from .contracts import (
    SCENARIO_HORIZON_DAYS, AnalogueEvidence, ForecastOutput, RunResult, ScenarioCheck, ScenarioValidation,
)

H = SCENARIO_HORIZON_DAYS
VOL_WINDOW = 63
MIN_PRIOR_STATES = 252  # terciles need at least a year of earlier states
MIN_EFFECTIVE_N = 10
BASE_BAND = 0.10  # base case: "similar" = forward return within +-10 percentage points of the implied return
DOWNSIDE_BARS = 1260  # five years


def _pct(x: float) -> str:
    return f"{x:+.1%}"


def _prices(px: pd.DataFrame | None) -> np.ndarray | None:
    if px is None or len(px) == 0:
        return None
    col = "adj_close" if "adj_close" in px else ("close" if "close" in px else None)
    if col is None:
        return None
    p = px[col].dropna().to_numpy(dtype=float)
    return p[p > 0] if len(p) else None


def _fwd(p: np.ndarray) -> np.ndarray:
    return p[H:] / p[:-H] - 1  # forward 252-bar simple return of every date whose outcome is known


def _analogue_dates(p: np.ndarray) -> tuple[list[int], str | None]:
    """Dates t (forward return known) whose trailing-252d return tercile and 63d realised-vol tercile equal today's.
    Terciles at t use only states strictly before t (expanding), so nothing from the future leaks in."""
    n = len(p)
    if n < 2 * H + MIN_PRIOR_STATES + 1:
        return [], f"only {n} bars; analogues need about {2 * H + MIN_PRIOR_STATES + 1}"
    ret = np.full(n, np.nan)
    ret[H:] = p[H:] / p[:-H] - 1
    vol = pd.Series(np.log(p)).diff().rolling(VOL_WINDOW).std().to_numpy()
    r_sorted: list[float] = []
    v_sorted: list[float] = []
    bucket: dict[int, tuple[int, int]] = {}
    for t in range(H, n):
        m = len(r_sorted)
        if m >= MIN_PRIOR_STATES:
            b = []
            for s, x in ((r_sorted, ret[t]), (v_sorted, vol[t])):
                lo, hi = s[m // 3], s[(2 * m) // 3]
                b.append(0 if x < lo else (2 if x >= hi else 1))
            bucket[t] = (b[0], b[1])
        insort(r_sorted, ret[t])
        insort(v_sorted, vol[t])
    today = bucket.get(n - 1)
    if today is None:
        return [], "not enough earlier history to form terciles"
    return [t for t, b in bucket.items() if b == today and t <= n - 1 - H], None


def _effective_n(dates: list[int]) -> float:
    """Independent episodes: greedily keep analogue dates at least 252 bars apart (overlapping windows share returns)."""
    kept, last = 0, -H
    for t in dates:
        if t - last >= H:
            kept, last = kept + 1, t
    return float(kept)


def _event(kind: str, fwd: np.ndarray, target: float) -> float:
    hit = fwd >= target if kind == "bull" else (fwd <= target if kind == "bear" else np.abs(fwd - target) <= BASE_BAND)
    return float(np.mean(hit))


def _definition(kind: str) -> str:
    ev = {"bull": "at least the implied return", "bear": "at most the implied return",
          "base": f"within +-{BASE_BAND:.0%} of the implied return"}[kind]
    return (f"Past dates whose trailing-{H}-day return tercile and {VOL_WINDOW}-day realised-volatility tercile match the last bar's "
            f"(terciles from earlier data only, expanding); forward {H}-day simple return known. Frequency = share with a forward return {ev}. "
            "A historical frequency, not a probability.")


def _downside(p: np.ndarray) -> tuple[float | None, float | None]:
    if len(p) < H + 1:
        return None, None
    last = p[-DOWNSIDE_BARS:]
    vol = float(np.std(np.diff(np.log(p[-(H + 1):])), ddof=1) * math.sqrt(252))
    return vol, float(np.min(last / np.maximum.accumulate(last) - 1))


def _ml(run: RunResult | None) -> tuple[ForecastOutput | None, str]:
    """The validated forecast at the longest available horizon (126 days; no 252-day forecast exists)."""
    if run is None:
        return None, "no ML run was supplied"
    if run.status != "ok_beats_baseline":
        return None, f"the ML run status is '{run.status}', so its forecasts are not used"
    ok = {h.horizon: h.selected_model for h in run.horizons if h.status == "ok_beats_baseline" and h.selected_model}
    cands = [f for f in run.forecasts if ok.get(f.horizon) == f.model and f.status == "ok_beats_baseline"
             and f.lower_return is not None and f.upper_return is not None]
    if not cands:
        return None, "no validated forecast with a prediction interval is available"
    return max(cands, key=lambda f: f.horizon), ""


def _check(kind: str, target, ref, ml, ml_why, p, fwd_all, ana, ana_why, eff_n, vol, mdd) -> ScenarioCheck:
    lim = [f"The {H}-day scenario horizon is an assumption: the fundamental model does not state when the target is reached.",
           "Analogue windows overlap (consecutive dates share most of their forward return); effective n counts non-overlapping episodes.",
           "Analogue frequencies are historical frequencies, not probabilities; no probability is shown."]
    c = ScenarioCheck(scenario=kind, fundamental_target=target, reference_price=ref, hist_vol_252=vol, hist_max_drawdown=mdd, limitations=lim)
    lim = c.limitations  # pydantic copies the list
    if not target or not ref or ref <= 0 or target <= 0:
        lim.append("No usable fundamental target or reference price, so nothing could be compared.")
        return c
    r = target / ref - 1
    c.implied_return = r
    for_, against, excl = [], [], []
    # ML, at the nearest available horizon, compared explicitly at that horizon
    if ml is not None:
        h = ml.horizon
        scaled = math.log(1 + r) * h / H
        c.ml_forecast, c.ml_horizon_used = ml, h
        lim.append(f"No {H}-day ML forecast exists; the {h}-day forecast is used and the implied return is pro-rated linearly in log terms "
                   f"(not extrapolated further). Pro-rating is a simplification.")
        txt = (f"implied {_pct(r)} over {H}d is {scaled:+.3f} log over {h}d; the {h}d model interval (5th-95th percentile) is "
               f"{ml.lower_return:+.3f} to {ml.upper_return:+.3f}")
        if ml.lower_return <= scaled <= ml.upper_return:
            for_.append(txt + ": inside it.")
        else:
            against.append(txt + ": outside it.")
            excl.append("ml")
    else:
        lim.append(f"ML evidence unavailable: {ml_why}.")
    if p is None:
        lim.append("No price history supplied: no analogue or downside evidence.")
    else:
        lo, hi = np.percentile(fwd_all, [10, 90]) if len(fwd_all) else (None, None)
        if lo is not None:
            if r > hi:
                against.append(f"implied {_pct(r)} is above the 90th percentile of historical {H}-day returns ({_pct(hi)})")
            elif r < lo:
                against.append(f"implied {_pct(r)} is below the 10th percentile of historical {H}-day returns ({_pct(lo)})")
            else:
                for_.append(f"implied {_pct(r)} is within the 10th-90th percentile range of historical {H}-day returns ({_pct(lo)} to {_pct(hi)})")
        if ana is None:
            lim.append(f"Analogue evidence unavailable: {ana_why}.")
        else:
            a = ana
            c.analogue = a
            if a.effective_n < MIN_EFFECTIVE_N:
                lim.append(a.warning)
            elif a.p10_forward_return is not None:
                if a.p10_forward_return <= r <= a.p90_forward_return:
                    for_.append(f"implied {_pct(r)} is within the analogue forward-return range ({_pct(a.p10_forward_return)} to {_pct(a.p90_forward_return)})")
                else:
                    against.append(f"implied {_pct(r)} is outside the analogue forward-return range ({_pct(a.p10_forward_return)} to {_pct(a.p90_forward_return)})")
                    excl.append("analogue")
                share = a.freq_at_least_target
                (for_ if share >= 0.10 else against).append(
                    f"{share:.0%} of {a.n_analogues} analogue dates ({a.effective_n:.0f} independent episodes) had a forward return "
                    f"{'at least' if kind == 'bull' else ('at most' if kind == 'bear' else 'near')} the implied {_pct(r)} "
                    f"(all dates: {a.unconditional_freq:.0%})")
        if kind == "bear" and mdd is not None:
            (against if r < mdd else for_).append(
                f"bear implied {_pct(r)} is {'deeper' if r < mdd else 'not deeper'} than the worst drawdown of the last 5 years ({_pct(mdd)})")
    c.evidence_for, c.evidence_against = for_, against
    ana_ok = c.analogue is not None and c.analogue.effective_n >= MIN_EFFECTIVE_N
    if not ana_ok and ml is None:
        c.status = "insufficient_evidence"
    elif "ml" in excl and "analogue" in excl:
        c.status = "contradicted"
    elif excl:
        c.status = "stretched"
    else:
        c.status = "consistent"
    return c


def validate_scenarios(report: dict, run: RunResult | None, px: pd.DataFrame | None) -> ScenarioValidation:
    sc = report.get("scenarios")
    if not sc or not sc.get("cases"):
        return ScenarioValidation(notes=["The report has no bear/base/bull scenarios (valuation withheld or not computed)."])
    ref = (report.get("cover") or {}).get("price") or (report.get("company") or {}).get("price")
    p = _prices(px)
    ml, ml_why = _ml(run)
    fwd_all = _fwd(p) if p is not None and len(p) > H else np.array([])
    dates, ana_why = _analogue_dates(p) if p is not None else ([], "no price history")
    if p is not None and not len(fwd_all):
        ana_why = f"fewer than {H + 1} bars"
    vol, mdd = _downside(p) if p is not None else (None, None)
    eff = _effective_n(dates)
    afwd = p[[t + H for t in dates]] / p[dates] - 1 if dates else np.array([])
    vals = {c["key"]: c.get("value") for c in sc["cases"]}
    checks = []
    for kind in ("bear", "base", "bull"):
        target = vals.get(kind)
        ana = None
        if len(afwd) and target and ref and ref > 0:
            r = target / ref - 1
            q10, q90 = np.percentile(afwd, [10, 90])
            ana = AnalogueEvidence(
                definition=_definition(kind), n_analogues=len(afwd), effective_n=eff, freq_at_least_target=_event(kind, afwd, r),
                unconditional_freq=_event(kind, fwd_all, r), median_forward_return=float(np.median(afwd)),
                p10_forward_return=float(q10), p90_forward_return=float(q90),
                warning=(f"Only {eff:.0f} independent analogue episodes (n={len(afwd)}); fewer than {MIN_EFFECTIVE_N} is insufficient evidence."
                         if eff < MIN_EFFECTIVE_N else None))
        elif not len(afwd) and p is not None and ana_why is None:
            ana_why = "no past date matches today's return and volatility regime"
        checks.append(_check(kind, target, ref, ml, ml_why, p, fwd_all, ana, ana_why or "no matching analogue dates", eff, vol, mdd))
    notes = [f"Scenario horizon is assumed to be {H} trading days; prices are adjusted closes; returns are simple (target / price - 1)."]
    return ScenarioValidation(checks=checks, notes=notes)
