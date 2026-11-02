"""Query-architecture switch and the routing decision shared by variants B-E.

ARIA_QUERY_ARCHITECTURE:
  baseline (A, default)  today's behaviour, byte for byte: nothing here runs
  semantic_router (B)    A + Semantic Router for questions the deterministic layer could not place
  langgraph (C)          A + LangGraph workflow (decomposition of multi-part questions, per-part verification)
  structured (D)         structured LLM understanding + Semantic Router + LangGraph; replaces the keyword/regex routing
  hybrid (E)             A's deterministic rules first, then structured understanding + Semantic Router + LangGraph
  adaptive (H, "E2")     rules first; the model is consulted only for the kinds of question where it helped (see needs_model), and it may only
                         overrule the rules where that helped (see guard): company data, out-of-scope and small talk stay with the rules
Independent switches for ablations: ARIA_SR_MODE=fallback|override (B), ARIA_INTENT_LLM=0 (turn the LLM off in D/E), ARIA_INTENT_GRAPH=0.
Any failure in a new component returns "no opinion" (None) and the baseline route runs.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field

from loguru import logger

from core.intent import semantic
from core.intent.taxonomy import CLARIFY, GENERAL, SMALLTALK

ALIASES = {"baseline": "A", "a": "A", "semantic_router": "B", "b": "B", "langgraph": "C", "c": "C",
           "structured": "D", "d": "D", "hybrid": "E", "e": "E", "adaptive": "H", "e2": "H", "h": "H"}

# Thresholds. Defaults are overwritten by evaluation/intent_understanding/calibrate.py output (dev split only) via env or thresholds.json.
DEFAULTS = {"sr_score": 0.30, "sr_margin": 0.05, "llm_intent": 0.75, "llm_context": 0.70, "sr_veto": 0.45}


def architecture() -> str:
    return ALIASES.get(os.getenv("ARIA_QUERY_ARCHITECTURE", "baseline").strip().lower(), "A")


# Dev-split optima per variant (evaluation/intent_understanding/calibrate.py); only the router veto moved from the starting values.
BY_ARCH = {"D": {"sr_veto": 0.7}, "E": {"sr_veto": 0.55}, "H": {"sr_veto": 0.55}}


def threshold(name: str) -> float:
    """Environment override, else the variant's calibrated value, else the default."""
    return float(os.getenv(f"ARIA_INTENT_{name.upper()}", BY_ARCH.get(architecture(), {}).get(name, DEFAULTS[name])))


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


# ---- H ("E2"): adaptive hybrid -------------------------------------------------------------------------------------------------
# Designed from dev-split behaviour of D versus the rules: D was better on concept questions, follow-ups, multi-part and calculation
# questions, and worse on company data, out-of-scope requests and small talk. H therefore (1) asks the model only for the first kind and
# (2) lets the model overrule the rules only where that kind of change helped.
_CONCEPT = re.compile(r"^\s*(what('?s| is| are| does)|define|explain|how (does|do|is)|difference between|why (do|does|is)|teach me|meaning of|samjhao)\b|\bkya (hai|hota)", re.I)
_MULTI = re.compile(r"\?.*\?|;|\bthen\b|\b(?:and|also)\s+(?:what|how|is|are|calculate|tell|explain|show|price|the)\b", re.I)
_FOLLOW = re.compile(r"^\s*(and|also|what about|how about|why|its|it|that|this|give me an example|example)\b", re.I)
_DEICTIC = re.compile(r"\b(it|its|that|this|those|these|one|them|other)\b", re.I)


def needs_model(query: str, history: list[dict], rule_label: str | None, ticker: str | None) -> tuple[bool, str]:
    """(consult the model?, why). Cheap and local: no tokens."""
    if rule_label is None:
        return True, "rules_unplaced"
    if _MULTI.search(query):
        return True, "multi_part"
    if history and (len(query.split()) <= 6 or _FOLLOW.match(query)):
        return True, "follow_up"
    if _CONCEPT.search(query) and not ticker and rule_label != "tutor":
        return True, "concept_not_tutor"
    sem = semantic.classify(query)
    if sem.label and sem.label != rule_label and sem.score >= threshold("sr_veto"):
        return True, "router_disagrees"
    return False, "rules_confident"


def guard(rule_label: str | None, ticker: str | None, query: str, d: Decision) -> Decision:
    """Keep the model's decision only where it is allowed to overrule the rules; otherwise the rules' route runs (Decision with no label)."""
    rules = Decision(source="rules_guard", trace={**d.trace, "guarded": True})
    if len(d.sub_queries) >= 2:
        return d  # splitting a multi-part question is where the model was clearly better
    if d.clarify:
        # a question back only when the rules had nothing, or when a referent is plainly missing; otherwise answer as the rules would
        return d if rule_label is None and (_DEICTIC.search(query) or len(query.split()) <= 3) else rules
    if not d.label:
        return d
    if rule_label is None:
        if d.label == SMALLTALK and d.trace.get("sr_label") != SMALLTALK:
            return rules  # small talk needs two signals: the model alone called "recommend a good movie" small talk
        if d.label in ("equity_research", "company_intelligence") and not ticker:
            from modules.qa import lookup
            if lookup.is_data_question(query):
                return rules  # "revenue of <small company>" belongs to the data-lookup stage of the normal chain
        return d
    if rule_label in ("data_lookup", "company_intelligence", "general", "smalltalk"):
        return rules  # company facts and out-of-scope requests: the rules were right more often than the model
    if rule_label == "equity_research":
        if d.label == "equity_research" or (d.label == "tutor" and _CONCEPT.search(query) and not ticker):
            return d
        return rules
    return d  # finance / market / tutor / clarify: the model's reading was better than the keyword rules


def log(decision: Decision, query: str) -> None:
    logger.bind(arch=architecture(), source=decision.source, label=decision.label, clarify=bool(decision.clarify), **{
        k: v for k, v in decision.trace.items() if not isinstance(v, dict)}).info("intent_route")
