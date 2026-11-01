"""Query-architecture switch and the routing decision shared by variants B-E.

ARIA_QUERY_ARCHITECTURE:
  baseline (A, default)  today's behaviour, byte for byte: nothing here runs
  semantic_router (B)    A + Semantic Router for questions the deterministic layer could not place
  langgraph (C)          A + LangGraph workflow (decomposition of multi-part questions, per-part verification)
  structured (D)         structured LLM understanding + Semantic Router + LangGraph; replaces the keyword/regex routing
  hybrid (E)             A's deterministic rules first, then structured understanding + Semantic Router + LangGraph
Independent switches for ablations: ARIA_SR_MODE=fallback|override (B), ARIA_INTENT_LLM=0 (turn the LLM off in D/E), ARIA_INTENT_GRAPH=0.
Any failure in a new component returns "no opinion" (None) and the baseline route runs.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass, field

from loguru import logger

from core.intent import semantic
from core.intent.taxonomy import CLARIFY, GENERAL, SMALLTALK

ALIASES = {"baseline": "A", "a": "A", "semantic_router": "B", "b": "B", "langgraph": "C", "c": "C",
           "structured": "D", "d": "D", "hybrid": "E", "e": "E"}

# Thresholds. Defaults are overwritten by evaluation/intent_understanding/calibrate.py output (dev split only) via env or thresholds.json.
DEFAULTS = {"sr_score": 0.30, "sr_margin": 0.05, "llm_intent": 0.75, "llm_context": 0.70, "sr_veto": 0.45}


def architecture() -> str:
    return ALIASES.get(os.getenv("ARIA_QUERY_ARCHITECTURE", "baseline").strip().lower(), "A")


def threshold(name: str) -> float:
    return float(os.getenv(f"ARIA_INTENT_{name.upper()}", DEFAULTS[name]))


@dataclass
class Decision:
    label: str | None = None  # the module to run, or None = no opinion (baseline routing runs)
    clarify: str | None = None  # a question to ask instead of running anything
    source: str = "none"
    sub_queries: list[tuple[str, str]] = field(default_factory=list)  # (text, label) for multi-part questions
    trace: dict = field(default_factory=dict)


forced_label: ContextVar[str | None] = ContextVar("aria_forced_label", default=None)  # set by the graph for one sub-task


def _sr_ok(sem: semantic.SemanticChoice) -> bool:
    return sem.label is not None and sem.score >= threshold("sr_score") and sem.margin >= threshold("sr_margin")


def decide_b(query: str, *, deterministic_confident: bool) -> Decision:
    """B: only questions the rules could not place (they would fall through to the general model) are offered to the semantic router."""
    if deterministic_confident and os.getenv("ARIA_SR_MODE", "fallback") != "override":
        return Decision(trace={"skipped": "deterministic_confident"})
    sem = semantic.classify(query)
    trace = {"sr_label": sem.label, "sr_score": round(sem.score, 3), "sr_margin": round(sem.margin, 3), "sr_ms": sem.latency_ms, "engine": sem.engine}
    if _sr_ok(sem) and sem.label not in (GENERAL,):
        return Decision(label=sem.label, source="semantic_router", trace=trace)
    return Decision(trace=trace)


def decide_structured(query: str, history: list[dict], *, deterministic_label: str | None, understand_fn) -> Decision:
    """D/E: structured understanding, checked against the semantic router. Returns clarify when the two cannot be reconciled safely."""
    trace: dict = {}
    u, diag = understand_fn(query, history)
    trace["llm"] = diag
    standalone = u.standalone_query if u else query
    sem = semantic.classify(standalone)
    trace.update(sr_label=sem.label, sr_score=round(sem.score, 3), sr_margin=round(sem.margin, 3), sr_ms=sem.latency_ms)
    if u is None:  # LLM unavailable: semantic router alone, and only if it is clearly sure; else baseline
        if _sr_ok(sem) and sem.label != GENERAL:
            return Decision(label=sem.label, source="semantic_router_only", trace=trace)
        return Decision(trace=trace)
    trace.update(llm_intent=u.primary_intent, llm_conf=u.confidence.intent, llm_ctx=u.confidence.context_resolution,
                 entities=[e.value for e in u.entities], secondary=list(u.secondary_intents), sub_n=len(u.sub_queries))
    if u.requires_clarification or u.primary_intent == CLARIFY or u.confidence.context_resolution < threshold("llm_context"):
        return Decision(clarify=u.clarification_question or "Which company, fund or task do you mean?", source="llm_clarify", trace=trace)
    if u.confidence.intent < threshold("llm_intent"):
        if _sr_ok(sem) and sem.label == u.primary_intent:  # two independent weak signals that agree
            return Decision(label=u.primary_intent, source="llm+sr_agree", trace=trace)
        return Decision(clarify=u.clarification_question or "Could you tell me a little more about what you need?", source="low_confidence", trace=trace)
    subs = [(s.text, s.intent) for s in u.sub_queries if s.intent not in (CLARIFY,)]
    if len(subs) < 2:
        subs = []
    if sem.label and sem.label != u.primary_intent and sem.score >= threshold("sr_veto") and u.primary_intent not in (SMALLTALK,):
        trace["disagreement"] = True  # both confident and different: ask rather than run the wrong module
        return Decision(clarify=u.clarification_question or "Do you want help with your own money, or information about a company or the market?",
                        source="llm_sr_disagree", trace=trace)
    return Decision(label=u.primary_intent, source="llm", sub_queries=subs, trace=trace)


def log(decision: Decision, query: str) -> None:
    logger.bind(arch=architecture(), source=decision.source, label=decision.label, clarify=bool(decision.clarify), **{
        k: v for k, v in decision.trace.items() if not isinstance(v, dict)}).info("intent_route")
