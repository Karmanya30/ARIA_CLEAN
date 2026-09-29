"""
Entry point of the intelligence layer: ``run_research(query)``.

    resolve -> gather -> analyze -> value -> audit -> narrate + debate (concurrently) -> audit narrative -> report

Returns ARIA's usual response dict (``domain``, ``company``, ``metric``, ``value``, ``response``,
``confidence``) plus a ``report`` key carrying the full structured report, so everything that
already consumes a Module 4 response -- chat UI, TTS, the Tavus avatar -- keeps working unchanged.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from modules.equity_research.intelligence import agents
from modules.equity_research.intelligence.analysis import analyze
from modules.equity_research.intelligence.audit import audit_narrative, run_audit
from modules.equity_research.intelligence.data import Snapshot, Target, gather, resolve_target
from modules.equity_research.intelligence.facts import Ledger
from modules.equity_research.intelligence.report import build_report, summary_response, to_markdown
from modules.equity_research.intelligence.valuation import value_company

_CONFIDENCE = {"high": "high", "medium": "medium", "low": "low", "very_low": "low"}


def _message(query: str, company: str | None, insight: str, analysis: str, recommendation: str, risk: str) -> dict[str, Any]:
    return {"domain": "equity_research", "query": query, "company": company, "metric": "Equity Research Report", "value": None,
            "confidence": "low", "response": f"Insight: {insight}\nAnalysis: {analysis}\nRecommendation: {recommendation}\nRisk: {risk}"}


def not_found(query: str) -> dict[str, Any]:
    return _message(query, None, "I could not identify which listed company this research request is about.",
                    "I looked for an NSE or BSE listed company in the request and could not resolve one.",
                    "Name the company or its NSE ticker, for example: equity research report on Reliance Industries.",
                    "Research reports cover NSE/BSE-listed companies only; unlisted businesses and brand names have no market data.")


def no_data(query: str, target: Target, warnings: list[str]) -> dict[str, Any]:
    return _message(query, target.slug, f"I could not retrieve market or financial data for {target.slug}.",
                    "Neither the price source nor the statements source returned usable data: " + " ".join(warnings[:3]),
                    "Check the ticker and try again in a moment.", "No report was generated, so there is nothing to rely on here.")


def _persist(user_id: str, report: dict) -> dict | None:
    """Save the report as the next version for this owner. A storage failure must never lose the report the
    user just waited for, so it is logged and the report is still returned (unsaved)."""
    try:
        from shared.user_store import save_research_report

        return save_research_report(user_id, report)
    except Exception:
        logger.exception("could not save the research report; returning it unsaved")
        return None


def report_kind(query: str) -> str:
    """Which view of the report the request asked for. Unspecific requests get the full equity research report."""
    t = query.lower()
    if any(p in t for p in ("research report", "equity research", "initiate coverage", "initiating coverage")):
        return "equity_research"
    if "dupont" in t:
        return "dupont"
    if any(p in t for p in ("financial model", "financial report", "financial analysis")):
        return "financial_model"
    if any(p in t for p in ("valuation", "dcf", "fair value", "intrinsic value", "target price", "price target", "overvalued", "undervalued")):
        return "valuation"
    return "equity_research"


def run_research(query: str, user_id: str = "default", target: Target | None = None, kind: str | None = None) -> dict[str, Any]:
    """Generate a report. ``target`` skips company resolution (used to regenerate a saved report)."""
    target = target or resolve_target(query)
    if target is None:
        return not_found(query)
    snap: Snapshot = gather(target)
    if snap.price is None and not snap.tables:
        return no_data(query, target, snap.warnings)

    ledger = Ledger()
    an = analyze(snap, ledger)
    val = value_company(snap, an, ledger)
    audit = run_audit(snap, ledger, an, val)
    val.withheld_by_audit = audit.withhold_valuation

    # Narrative and debate are independent readers of the same immutable facts.
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_narr = pool.submit(agents.narrate, snap, an, val, ledger)
        f_debate = pool.submit(agents.debate, snap, an, val, ledger)
        narr, deb = f_narr.result(), f_debate.result()

    stats = {**narr.stats, **{k: v for k, v in deb.stats.items() if k != "llm_available"},
             "llm_available": narr.stats.get("llm_available", True) and deb.stats.get("llm_available", True)}
    syn = val.synthesis
    if deb.judge and syn and not audit.withhold_valuation:
        stats.update(quant_rating=syn.rating, judge_call=deb.judge["call"],
                     judge_disagrees={deb.judge["call"], syn.rating} == {"BUY", "SELL"})
    audit_narrative(audit, stats)

    report = build_report(snap, an, val, audit, narr, deb, ledger, kind=kind or report_kind(query))
    report["markdown"] = to_markdown(report)
    meta = _persist(user_id, report)
    logger.info(f"research report for {target.symbol}: {len(ledger)} facts, status={audit.status}, methods={[m.key for m in val.methods]}")
    return {
        "domain": "equity_research",
        "query": query,
        "company": target.slug,
        "metric": "Equity Research Report",
        "value": syn.central if syn and not audit.withhold_valuation else None,
        "response": summary_response(snap, an, val, audit, deb),
        "confidence": _CONFIDENCE.get(syn.tier, "low") if syn and not audit.withhold_valuation else "low",
        "report": report,
        "report_id": meta["id"] if meta else None,
    }
