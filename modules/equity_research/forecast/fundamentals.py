"""Owner: WP4. Reproduce and sanity-check the report's fundamental valuation.

Pure and deterministic: no network, no LLM. Each bear/base/bull case is rebuilt from the assumptions the report
recorded for it, with the existing valuation arithmetic (``intelligence.valuation``), and compared with the reported
value. Anything the report did not record is flagged, never filled in.
"""
from __future__ import annotations

import statistics

import pandas as pd

from modules.equity_research.intelligence.valuation import (
    MIN_GORDON_SPREAD, TV_DOMINANCE, DCFInputs, DDMInputs, NotApplicable, ddm, dcf, fade,
)

from .contracts import RETRO_NOTE, FundamentalCaseCheck, FundamentalCheck

TOLERANCE_PCT = 0.5  # |reproduced - reported| / reported, in percent
LINE_TOL = 0.005  # relative tolerance for the recorded forecast lines
SD_LIMIT = 2.0  # assumption more than this many standard deviations from the historical mean is flagged
CASES = ("bear", "base", "bull")


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-12)


def _rebuild_dcf(d: dict, issues: list[str]) -> float | None:
    a, lines, br = d["assumptions"], d["lines"], d["bridge"]
    try:
        n = len(lines["revenue"])
        g0 = lines["growth"][0]
        base_rev = lines["revenue"][0] / (1 + g0)
        da_pct = lines["da"][0] / lines["revenue"][0]
        inp = DCFInputs(base_rev, fade(a["g1"], a["terminal_growth"], n), a["margin"], da_pct, a["capex_pct"], a["nwc_pct"], a["tax"],
                        a["wacc"], a["terminal_growth"], br["net_debt"], br["nci"], br["shares_cr"])
    except (KeyError, TypeError, ZeroDivisionError, IndexError) as exc:
        issues.append(f"unsupported: the case does not record {exc}; value not reproduced")
        return None
    if br["shares_cr"] is None or br["shares_cr"] <= 0:
        issues.append("shares: share count is missing or not positive")
        return None
    try:
        res = dcf(inp)
    except NotApplicable as exc:
        issues.append(f"the valuation arithmetic refuses these assumptions: {exc}")
        return None
    if abs(lines["growth"][0] - a["g1"]) > 1e-9:
        issues.append(f"recorded year-1 growth {lines['growth'][0]:.2%} differs from the assumption {a['g1']:.2%}")
    worst = max((_rel(x, y) for x, y in zip(res.fcf, lines["fcf"]) if abs(y) > 1e-9), default=0.0)
    if worst > LINE_TOL:
        issues.append(f"recorded free-cash-flow lines differ from the assumptions by up to {worst:.1%}")
    # discount periods: year i is discounted i+1 periods at the case WACC
    if any(_rel(f, 1 / (1 + a["wacc"]) ** (i + 1)) > 1e-6 for i, f in enumerate(d.get("discount_factor", []))) or not d.get("discount_factor"):
        issues.append("discount periods: recorded discount factors do not match 1/(1+WACC)^year")
    if a["terminal_growth"] >= a["wacc"]:
        issues.append(f"terminal growth {a['terminal_growth']:.2%} is not below WACC {a['wacc']:.2%}")
    elif a["wacc"] - a["terminal_growth"] < MIN_GORDON_SPREAD:
        issues.append(f"WACC minus terminal growth is only {a['wacc'] - a['terminal_growth']:.2%}")
    if res.tv_share > TV_DOMINANCE:
        issues.append(f"terminal value is {res.tv_share:.0%} of enterprise value (above {TV_DOMINANCE:.0%}): the result rests on long-run assumptions")
    if br.get("tv_share") is not None and abs(br["tv_share"] - res.tv_share) > 0.01:
        issues.append(f"recorded terminal share {br['tv_share']:.1%} differs from the rebuilt {res.tv_share:.1%}")
    if br["net_debt"] is None or br["nci"] is None:
        issues.append("net debt or minority interest is not recorded")
    return res.per_share


def _rebuild_ddm(d: dict, ddm_inputs: dict | None, issues: list[str]) -> float | None:
    a, lines = d["assumptions"], d["lines"]
    roe = (ddm_inputs or {}).get("terminal_roe")
    if roe is None:
        issues.append("unsupported: terminal ROE is not recorded for the dividend model; value not reproduced")
        return None
    try:
        eps0 = lines["eps"][0] / (1 + lines["growth"][0])
        inp = DDMInputs(eps0, a["payout"], fade(a["g1"], a["terminal_growth"], len(lines["eps"])), a["coe"], a["terminal_growth"], roe)
        res = ddm(inp)
    except NotApplicable as exc:
        issues.append(f"the valuation arithmetic refuses these assumptions: {exc}")
        return None
    except (KeyError, TypeError, ZeroDivisionError, IndexError) as exc:
        issues.append(f"unsupported: the case does not record {exc}; value not reproduced")
        return None
    if abs(lines["growth"][0] - a["g1"]) > 1e-9:
        issues.append(f"recorded year-1 growth {lines['growth'][0]:.2%} differs from the assumption {a['g1']:.2%}")
    if any(_rel(f, 1 / (1 + a["coe"]) ** (i + 1)) > 1e-6 for i, f in enumerate(d.get("discount_factor", []))) or not d.get("discount_factor"):
        issues.append("discount periods: recorded discount factors do not match 1/(1+CoE)^year")
    if a["terminal_growth"] >= a["coe"]:
        issues.append(f"terminal growth {a['terminal_growth']:.2%} is not below cost of equity {a['coe']:.2%}")
    tv_share = res.pv_terminal / res.per_share
    if tv_share > TV_DOMINANCE:
        issues.append(f"terminal value is {tv_share:.0%} of the dividend-model value (above {TV_DOMINANCE:.0%})")
    return res.per_share


def _outlier(label: str, scen: str, x: float, hist: list[float], *, is_growth: bool) -> str | None:
    h = [v for v in hist if v is not None]
    if len(h) < 2:
        return None
    mean, sd = statistics.fmean(h), statistics.stdev(h)
    if is_growth and x > max(h) + 1e-9:
        return f"{scen}: {label} {x:.1%} is above the historical maximum {max(h):.1%}"
    if sd > 0 and abs(x - mean) > SD_LIMIT * sd:
        return f"{scen}: {label} {x:.1%} is {abs(x - mean) / sd:.1f} standard deviations from the historical mean {mean:.1%}"
    if sd == 0 and abs(x - mean) > 1e-9 and not is_growth:
        return f"{scen}: {label} {x:.1%} differs from a historical record that never varied ({mean:.1%})"
    return None


def _assumption_flags(sc: dict, model: str) -> list[str]:
    hist = (sc.get("history") or {}).get("rows") or {}
    if not hist:
        return ["No assumption history was recorded in the report, so assumptions were not compared with history."]
    out: list[str] = []
    if model == "DCF":
        checks = [("year-1 revenue growth", "g1", hist.get("rev_growth", []), True), ("EBITDA margin", "margin", hist.get("opm", []), False)]
    else:
        eps = [v for v in hist.get("eps", []) if v]
        yoy = [b / a - 1 for a, b in zip(eps, eps[1:]) if a and a > 0]
        checks = [("year-1 EPS growth", "g1", yoy, True), ("dividend payout", "payout", hist.get("payout", []), False)]
    for c in sc.get("cases", []):
        a = (c.get("detail") or {}).get("assumptions")
        if not a:
            continue
        for label, key, h, is_growth in checks:
            if key in a and a[key] is not None and (msg := _outlier(label, c["key"], a[key], h, is_growth=is_growth)):
                out.append(msg)
    return out


def _sensitivity(report: dict, base_case: dict | None) -> list[str]:
    dcf_block = (report.get("valuation") or {}).get("dcf") or {}
    s, notes = dcf_block.get("sensitivity"), []
    res = (dcf_block.get("result") or {}).get("per_share")
    if s and res and base_case and base_case.get("assumptions"):
        w0, g0 = base_case["assumptions"]["wacc"], base_case["assumptions"]["terminal_growth"]
        ws, gs, grid = s["wacc_values"], s["tg_values"], s["prices"]

        def idx(axis, v):
            return next((k for k, x in enumerate(axis) if abs(x - v) < 1e-9), None)

        def at(i, j):
            return grid[i][j] if i is not None and j is not None else None

        for name, pairs in (("WACC", [(w0 + d, g0, f"{d * 100:+.0f}pp") for d in (-0.01, 0.01)]),
                            ("terminal growth", [(w0, g0 + d, f"{d * 100:+.0f}pp") for d in (-0.01, 0.01)])):
            parts = []
            for w, g, tag in pairs:
                v = at(idx(ws, w), idx(gs, g))
                parts.append(f"{tag}: {v:,.2f} ({v / res - 1:+.1%})" if v else f"{tag}: not available")
            notes.append(f"Target moves for {name} -/+1pp (per share, base {res:,.2f}): " + "; ".join(parts) + ".")
    elif dcf_block:
        notes.append("DCF sensitivity grid is not available in the report.")
    swing = dcf_block.get("margin_swing")
    if swing and res and None not in swing:
        notes.append(f"EBITDA margin -/+2pp (the report's own swing) moves the DCF value to {swing[0]:,.2f} / {swing[1]:,.2f} ({swing[0] / res - 1:+.1%} / {swing[1] / res - 1:+.1%}).")
    return notes


def check_fundamentals(report: dict, px: pd.DataFrame | None) -> FundamentalCheck:
    sc = report.get("scenarios")
    if not sc or not sc.get("cases"):
        return FundamentalCheck(notes=["The report has no bear/base/bull scenarios (valuation withheld or not computed); nothing to reproduce."])
    model = sc.get("model", "DCF")
    price = (report.get("cover") or {}).get("price") or (report.get("company") or {}).get("price")
    ddm_inputs = ((report.get("valuation") or {}).get("ddm") or {}).get("inputs")
    cases, shared = [], {}
    for c in sc["cases"]:
        d, issues, reported = c.get("detail") or {}, [], c.get("value")
        repro = None
        if not d.get("assumptions"):
            issues.append(f"no case detail recorded ({d.get('reason', 'model refused or detail missing')})")
        elif model == "DCF":
            repro = _rebuild_dcf(d, issues)
            br = d["bridge"]
            for k in ("net_debt", "nci", "shares_cr"):
                if shared.setdefault(k, br[k]) != br[k]:
                    issues.append(f"{k} differs between cases")
        else:
            repro = _rebuild_ddm(d, ddm_inputs, issues)
        diff = None
        if repro is not None and reported:
            diff = abs(repro - reported) / abs(reported) * 100
            if diff > TOLERANCE_PCT:
                issues.append(f"rebuilt value {repro:,.2f} differs from the reported {reported:,.2f} by {diff:.2f}% (tolerance {TOLERANCE_PCT}%)")
            if price and not 0.05 < reported / price < 20:
                issues.append(f"units: reported value is {reported / price:.2f}x the share price; check units or currency")
        elif reported is None and not issues:
            issues.append("no reported value for this case")
        ok = None if repro is None or not reported else diff <= TOLERANCE_PCT and not any(i.startswith(("units", "discount", "recorded")) for i in issues)
        cases.append(FundamentalCaseCheck(scenario=c["key"], reproduced_value=repro, reported_value=reported, abs_diff_pct=diff, ok=ok, issues=issues))
    notes = ["Percent differences are |rebuilt - reported| / reported x 100; tolerance 0.5%.",
             "Currency is taken from the report (INR, amounts in Rs Cr, shares in crore); it is not independently verified."]
    if px is not None and len(px):
        comps = (report.get("valuation") or {}).get("comps")
        notes.append("Peer context: the report's peer comparison table is present." if comps else "Peer context: not available.")
    else:
        notes.append("Peer context: not available (no price history supplied).")
    notes.append("Historical valuation multiples: not available (no multiples history in the data provided).")
    base = next((c.get("detail") for c in sc["cases"] if c["key"] == "base"), None)
    return FundamentalCheck(cases=cases, assumption_flags=_assumption_flags(sc, model), sensitivity_notes=_sensitivity(report, base),
                            retro_accuracy_note=RETRO_NOTE, notes=notes)
