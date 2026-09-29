"""
Verification gate: runs after valuation and again after the LLM narrative.

Findings carry a severity, modelled on FinRobot's numeric-audit ledger (Apache-2.0,
AI4Finance Foundation; see THIRD_PARTY_NOTICES.md):

    info     advisory, never gates
    review   the report ships flagged "caveated" with a data-quality banner
    blocked  a published number cannot be trusted: the point estimate is withheld
             (the analysis, the range and the reasons still ship)

A failed check is reported, never smoothed over. Each named check appears in
``Audit.checks`` whether it passed or not, so the reader sees what was verified.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date

from modules.equity_research.intelligence.analysis import Analysis
from modules.equity_research.intelligence.comps import LABELS, synthesize
from modules.equity_research.intelligence.data import Snapshot
from modules.equity_research.intelligence.facts import ASSUMPTION, CALCULATED, Ledger, fmt
from modules.equity_research.intelligence.valuation import (
    DCFInputs, DDMInputs, Valuation, dcf, ddm, monte_carlo,
)

_RANK = {"info": 0, "review": 1, "blocked": 2}
CHECKS = (
    ("required_inputs", "Required inputs are available"),
    ("units_scale", "Units and scale are consistent"),
    ("period_consistency", "Periods and statement basis are consistent"),
    ("missing_values", "Missing values are disclosed, not filled"),
    ("reproducibility", "Calculated values reproduce from their published inputs"),
    ("assumptions", "Assumptions are explicit and their origin stated"),
    ("sources", "Every figure has a source"),
    ("contradictions", "Independent sources agree"),
    ("method_agreement", "Valuation methods corroborate each other"),
    ("narrative", "Narrative figures trace to calculated facts"),
)
_REL_TOL = 1e-9
_EPS_TOL = 0.15  # screener vs Yahoo trailing EPS
_EBITDA_TOL = 0.35  # screener TTM operating profit vs Yahoo-implied EBITDA
_STALE_MONTHS = 18


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str  # info | review | blocked
    message: str
    facts: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"check": self.check, "severity": self.severity, "message": self.message, "facts": list(self.facts)}


@dataclass
class Audit:
    findings: list[Finding] = field(default_factory=list)

    def add(self, check: str, severity: str, message: str, *facts) -> None:
        self.findings.append(Finding(check, severity, message, tuple(f.id for f in facts if f)))

    @property
    def withhold_valuation(self) -> bool:
        return any(f.severity == "blocked" for f in self.findings)

    @property
    def status(self) -> str:
        return "caveated" if any(_RANK[f.severity] >= 1 for f in self.findings) else "publishable"

    @property
    def checks(self) -> list[dict]:
        out = []
        for key, title in CHECKS:
            mine = [f for f in self.findings if f.check == key]
            worst = max(mine, key=lambda f: _RANK[f.severity]).severity if mine else "pass"
            out.append({"name": key, "title": title, "status": worst, "findings": [f.message for f in mine]})
        return out

    def to_dict(self) -> dict:
        return {"status": self.status, "withhold_valuation": self.withhold_valuation,
                "findings": [f.to_dict() for f in self.findings], "checks": self.checks}


def _months_between(latest_col: str, as_of: str) -> float | None:
    try:
        month, year = latest_col.split()
        m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(month) + 1
        end, now = date(int(year), m, 28), date.fromisoformat(as_of)
        return (now.year - end.year) * 12 + now.month - end.month
    except (ValueError, IndexError):
        return None


def _roundtrip(obj):
    """What a reader gets from the published JSON: the audit recomputes from THAT, not from live objects."""
    return json.loads(json.dumps(asdict(obj)))


def run_audit(snap: Snapshot, ledger: Ledger, an: Analysis, val: Valuation) -> Audit:
    audit = Audit()
    F, info = an.facts, snap.info

    # 1. required inputs
    if not snap.price:
        audit.add("required_inputs", "review", "No share price was available, so nothing could be valued against the market.")
    if not snap.shares:
        audit.add("required_inputs", "review", "Share count unavailable: per-share values could not be computed.")
    if not an.latest:
        audit.add("required_inputs", "review", "No annual financial statements were retrieved: statement analysis and intrinsic valuation were skipped.")
    if val.synthesis is None:
        audit.add("required_inputs", "review", "No valuation method could be computed, so there is no fair value: " + "; ".join(f"{k}: {v}" for k, v in val.skipped.items()))
    for w in snap.warnings:
        audit.add("required_inputs", "review", w)

    # 2. units and scale
    price, shares, mcap = snap.price, snap.shares, snap.market_cap_cr
    if price and shares and mcap and abs(price * shares / 1e7 / mcap - 1) > 0.05:
        audit.add("units_scale", "review", f"Price x shares ({price * shares / 1e7:,.0f} Cr) differs from the reported market cap ({mcap:,.0f} Cr) by more than 5%.", F.get("market_cap"))
    if price:
        for m in val.methods:
            if not 0.05 <= m.mid / price <= 20:
                audit.add("units_scale", "blocked", f"{m.label} value {fmt(m.mid, '₹')} is {m.mid / price:.2f}x the share price: a unit or scale error is more likely than a real valuation.")

    # 3. periods and basis
    if snap.view == "standalone":
        audit.add("period_consistency", "review", "Statements are standalone while market data is consolidated: per-share figures may not line up.")
    age = _months_between(an.latest, snap.as_of) if an.latest else None
    if age is not None and age > _STALE_MONTHS:
        audit.add("period_consistency", "review", f"The latest annual statement ({an.latest}) is {age} months old.")
    if val.dcf_inputs and an.ttm.get("revenue"):
        audit.add("period_consistency", "info", "The DCF base revenue is trailing-twelve-months; margins and ratios are 3-year fiscal-year medians (stated on each assumption).")

    # 4. missing values
    if ledger.missing:
        shown = "; ".join(f"{k} ({v})" for k, v in list(ledger.missing.items())[:6])
        audit.add("missing_values", "info", f"{len(ledger.missing)} figure(s) could not be obtained and are shown as n/a, not estimated: {shown}.")

    # 5. reproducibility: recompute from the JSON a reader sees
    try:
        if val.dcf_inputs and val.dcf_result:
            d = _roundtrip(val.dcf_inputs)
            d["growth"] = tuple(d["growth"])
            again = dcf(DCFInputs(**d)).per_share
            if abs(again - val.dcf_result.per_share) > _REL_TOL * max(1.0, abs(again)):
                audit.add("reproducibility", "blocked", f"The DCF does not reproduce from its published inputs ({again:.6f} vs {val.dcf_result.per_share:.6f}).", val.facts.get("dcf_value"))
        if val.ddm_inputs and val.ddm_result:
            d = _roundtrip(val.ddm_inputs)
            d["growth"] = tuple(d["growth"])
            again = ddm(DDMInputs(**d)).per_share
            if abs(again - val.ddm_result.per_share) > _REL_TOL * max(1.0, abs(again)):
                audit.add("reproducibility", "blocked", "The DDM does not reproduce from its published inputs.", val.facts.get("ddm_value"))
        if val.monte_carlo and val.dcf_inputs and price:
            d = _roundtrip(val.dcf_inputs)
            d["growth"] = tuple(d["growth"])
            again_mc = monte_carlo(DCFInputs(**d), price)
            if not again_mc or abs(again_mc["p50"] - val.monte_carlo["p50"]) > _REL_TOL * max(1.0, abs(again_mc["p50"])):
                audit.add("reproducibility", "blocked", "The Monte Carlo distribution does not reproduce from its published inputs and seed.")
        if val.synthesis and price:
            again = synthesize(list(val.synthesis.methods), price, street=val.synthesis.street)
            if again.central != val.synthesis.central or again.rating != val.synthesis.rating:
                audit.add("reproducibility", "blocked", "The fair-value synthesis does not reproduce from the method values.")
    except Exception as exc:  # a recompute that crashes is itself a failed check
        audit.add("reproducibility", "blocked", f"Reproducibility check failed to run: {exc}")

    # 6. assumptions explicit
    macro = [f for f in ledger if f.source.startswith("ARIA configuration")]
    if macro:
        audit.add("assumptions", "info", "Risk-free rate, equity risk premium and terminal growth are configured assumptions (" +
                  ", ".join(f"{f.label} {f.text}" for f in macro) + "), not live market data; results move with them.", *macro)
    unexplained = [f for f in ledger if f.kind in (ASSUMPTION, CALCULATED) and not f.method and not f.inputs]
    if unexplained:
        audit.add("assumptions", "review", f"{len(unexplained)} calculated/assumed figure(s) lack a stated method: " + ", ".join(f.label for f in unexplained[:5]) + ".")
    if "beta" in val.facts and val.facts["beta"].kind == ASSUMPTION:
        audit.add("assumptions", "info", "Beta could not be estimated from prices; a market beta of 1.0 was assumed.", val.facts["beta"])

    # 7. sources
    sourceless = [f for f in ledger if not f.source]
    if sourceless:
        audit.add("sources", "blocked", f"{len(sourceless)} figure(s) have no source: " + ", ".join(f.label for f in sourceless[:5]) + ".")

    # 8. contradictions between independent sources
    eps_y, eps_s = info.get("trailingEps"), F.get("eps_ttm")
    if isinstance(eps_y, (int, float)) and eps_s and eps_y > 0 and abs(eps_s.value / eps_y - 1) > _EPS_TOL:
        audit.add("contradictions", "review", f"Trailing EPS differs between sources: screener.in {eps_s.text} vs Yahoo Finance {fmt(eps_y, '₹')}. Peer-P/E values use Yahoo's.", eps_s)
    ev, mult, op_ttm = info.get("enterpriseValue"), info.get("enterpriseToEbitda"), an.ttm.get("ebitda")
    if not snap.is_financial and isinstance(ev, (int, float)) and isinstance(mult, (int, float)) and mult > 0 and op_ttm:
        implied = ev / mult / 1e7
        if abs(implied / op_ttm - 1) > _EBITDA_TOL:
            audit.add("contradictions", "review", f"EBITDA differs between sources: screener.in TTM operating profit ₹{op_ttm:,.0f} Cr vs ₹{implied:,.0f} Cr implied by Yahoo's EV/EBITDA. The EV/EBITDA method uses Yahoo's definition.")
    debt_y, debt_s = info.get("totalDebt"), an.series.get("borrowings", {}).get(an.latest) if an.latest else None
    if not snap.is_financial and isinstance(debt_y, (int, float)) and debt_s and abs(debt_y / 1e7 / debt_s - 1) > 0.4:
        audit.add("contradictions", "info", f"Total debt differs between sources (Yahoo ₹{debt_y / 1e7:,.0f} Cr incl. leases vs screener.in borrowings ₹{debt_s:,.0f} Cr); Yahoo's is used for net debt.")
    if val.comps:
        for k, dropped in val.comps["excluded"].items():
            if dropped:
                audit.add("contradictions", "info", f"Peer {LABELS[k]} excluded for: " + "; ".join(f"{d['symbol']} {d['value']:.1f}x ({d['reason']})" for d in dropped[:4]) + ".")
        low_n = [k for k, n in val.comps["counts"].items() if 0 < n < 5]
        if low_n:
            audit.add("contradictions", "info", "Thin peer sample (fewer than 5 usable peers) for: " + ", ".join(LABELS[k] for k in low_n) + ".")

    # 9. method agreement
    syn = val.synthesis
    if syn:
        if syn.withheld:
            audit.add("method_agreement", "review", "The point estimate is withheld; see the valuation notes for why.")
        elif syn.spread and syn.spread > 1.5:
            audit.add("method_agreement", "info", f"Valuation methods differ {syn.spread:.1f}x; the central estimate is the median and confidence is {syn.tier}.")
        if F.get("target_low") and F.get("target_high") and syn.central is not None:
            lo, hi = F["target_low"].value, F["target_high"].value
            if not lo <= syn.central <= hi:
                audit.add("method_agreement", "info", f"Street context: our fair value {fmt(syn.central, '₹')} lies outside the analyst target range {fmt(lo, '₹')}-{fmt(hi, '₹')} ({int(F['analysts'].value) if 'analysts' in F else 'n/a'} analysts); an out-of-consensus view, not an error.", F["target_low"], F["target_high"])
    return audit


def audit_narrative(audit: Audit, stats: dict) -> None:
    """Fold the LLM-layer results into the audit. ``stats`` comes from agents.narrate/debate."""
    if not stats.get("llm_available", True):
        audit.add("narrative", "info", "The language model was unavailable: narrative sections are template text built directly from the calculated facts.")
    if stats.get("dropped_sentences"):
        n = stats["dropped_sentences"]
        audit.add("narrative", "review" if n > 2 else "info", f"{n} sentence(s) written by the model were removed because they contained figures that trace to no calculated fact.")
    if stats.get("rejected_arguments"):
        audit.add("narrative", "info", f"{stats['rejected_arguments']} debate argument(s) were rejected for citing unknown evidence or stating their own numbers.")
    if stats.get("fallback_sections"):
        audit.add("narrative", "info", "Template text replaced the model's draft for: " + ", ".join(stats["fallback_sections"]) + ".")
    if stats.get("judge_disagrees"):
        audit.add("narrative", "review", f"The bull/bear judge leans {stats['judge_call']} while the valuation implies {stats['quant_rating']}: the qualitative and quantitative reads diverge.")
