"""LangGraph workflow for multi-part questions (variants C, D, E).

Used only where a graph earns its place: a question with several independent parts is split, each part is run by the EXISTING ARIA
pipeline passed in as `handler` (nothing is re-implemented), each part is verified on its own evidence, and the parts are merged into
one answer without any extra model call (so the merge cannot add facts).

    plan -> execute (loops over the parts) -> verify -> synthesise

Parts run one after another IN THE CALLING THREAD by default: ARIA holds a per-conversation re-entrant lock for the whole turn
(core/session.py), so a worker thread that touches the session (every real pipeline does) would wait for the lock that the waiting
turn holds, i.e. deadlock (found while benchmarking). `parallel=True` fans the parts out with LangGraph `Send` for handlers that are
thread-safe (tests, stateless lookups); making session state thread-safe is the prerequisite for parallel production use.

State is a typed dict; every node appends to `trace` (observability). Retries are bounded (1) and only for a handler exception.
A failing part is reported honestly in the answer instead of being dropped or papered over.
"""
from __future__ import annotations

import operator
import re
import time
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger

from core.intent.taxonomy import CLARIFY, EQUITY, FINANCE, GENERAL, INTEL, LOOKUP, MARKET, SMALLTALK, TUTOR

_EVIDENCE = ("context", "report", "report_id", "company")  # what a part brings for the UI card
TITLES = {FINANCE: "Your finances", TUTOR: "Learning", MARKET: "Market", EQUITY: "Company", INTEL: "Company intelligence",
          LOOKUP: "Data", GENERAL: "Answer", SMALLTALK: "Hello"}
Handler = Callable[[str, str | None], dict[str, Any]]  # (sub-query text, label or None) -> a normal ARIA response dict


class GraphState(TypedDict, total=False):
    query: str
    plan: list[tuple[str, str | None]]
    results: Annotated[list[dict], operator.add]
    trace: Annotated[list[dict], operator.add]
    response: dict
    cursor: int


def _node_trace(node: str, started: float, **extra) -> list[dict]:
    return [{"node": node, "ms": round((time.perf_counter() - started) * 1000, 1), **extra}]


def build(handler: Handler, parallel: bool = False):
    def plan(state: GraphState) -> dict:
        t = time.perf_counter()
        return {"trace": _node_trace("plan", t, parts=len(state["plan"]))}

    def fan_out(state: GraphState):
        return [Send("execute", {"query": q, "label": lab, "index": i}) for i, (q, lab) in enumerate(state["plan"])]

    def run_part(item: dict) -> dict:
        t = time.perf_counter()
        err = None
        resp: dict | None = None
        for attempt in range(2):  # one bounded retry, only for an exception
            try:
                resp = handler(item["query"], item["label"])
                break
            except Exception as exc:  # noqa: BLE001 - a failing part must not take the others down
                err = f"{type(exc).__name__}: {str(exc)[:100]}"
                logger.warning(f"graph part {item['index']} failed (attempt {attempt + 1}): {err}")
        return {"results": [{"index": item["index"], "query": item["query"], "label": item["label"], "response": resp, "error": err if resp is None else None}],
                "trace": _node_trace("execute", t, index=item["index"], label=item["label"], ok=resp is not None)}

    def execute_next(state: GraphState) -> dict:
        i = state.get("cursor", 0)
        q, lab = state["plan"][i]
        out = run_part({"query": q, "label": lab, "index": i})
        out["cursor"] = i + 1
        return out

    def more(state: GraphState) -> str:
        return "execute" if state.get("cursor", 0) < len(state["plan"]) else "verify"

    def verify(state: GraphState) -> dict:
        """Each part is checked against ITS OWN evidence (a merged answer has no single evidence set to check against)."""
        from modules.qa import trust

        t = time.perf_counter()
        checked = []
        for r in sorted(state["results"], key=lambda r: r["index"]):
            resp = r["response"]
            if resp is None or trust.failed(resp.get("response")):
                r = {**r, "ok": False, "grounding": {"numbers_checked": False, "passed": False, "unavailable": ["this part"]}}
            else:
                r = {**r, "ok": True, "grounding": trust.enforce(resp)}
            checked.append(r)
        return {"results": checked, "trace": _node_trace("verify", t, ok=sum(1 for r in checked if r["ok"]), of=len(checked))}

    def synthesise(state: GraphState) -> dict:
        t = time.perf_counter()
        # `verify` re-emits every result; keep the last (verified) copy of each index
        latest: dict[int, dict] = {}
        for r in state["results"]:
            latest[r["index"]] = r
        parts = [latest[i] for i in sorted(latest)]
        blocks, ok_parts = [], 0
        for r in parts:
            title = TITLES.get(r["label"] or (r["response"] or {}).get("domain"), "Answer")
            if r.get("ok"):
                ok_parts += 1
                blocks.append(f"**{title}** ({r['query']})\n{r['response']['response']}")
            else:
                blocks.append(f"**{title}** ({r['query']})\nI couldn't complete this part just now, so I won't guess.")
        first = next((r["response"] for r in parts if r.get("ok")), None) or {}
        merged = {"domain": first.get("domain", "general"), "response": "\n\n".join(blocks), "multi_part": True,
                  "parts": [{"query": r["query"], "label": r["label"], "domain": (r["response"] or {}).get("domain"), "ok": bool(r.get("ok")),
                             **{k: r["response"][k] for k in _EVIDENCE if r.get("ok") and k in r["response"]}} for r in parts],
                  "grounding": {"numbers_checked": ok_parts > 0 and all((r.get("grounding") or {}).get("numbers_checked") for r in parts if r.get("ok")),
                                "passed": all((r.get("grounding") or {}).get("passed", False) for r in parts), "fallback": ok_parts < len(parts),
                                "unavailable": [r["query"] for r in parts if not r.get("ok")], "per_part": True}}
        # the report/context card is shown only when it supports the whole reply (one part has it); each part keeps its own under `parts`
        carriers = [r["response"] for r in parts if r.get("ok") and any(k in r["response"] for k in _EVIDENCE)]
        if len(carriers) == 1:
            merged.update({k: carriers[0][k] for k in _EVIDENCE if k in carriers[0]})
        return {"response": merged, "trace": _node_trace("synthesise", t, ok_parts=ok_parts, parts=len(parts))}

    g = StateGraph(GraphState)
    g.add_node("plan", plan)
    g.add_node("verify", verify)
    g.add_node("synthesise", synthesise)
    g.add_edge(START, "plan")
    if parallel:
        g.add_node("execute", run_part)
        g.add_conditional_edges("plan", fan_out, ["execute"])
        g.add_edge("execute", "verify")
    else:
        g.add_node("execute", execute_next)
        g.add_edge("plan", "execute")
        g.add_conditional_edges("execute", more, {"execute": "execute", "verify": "verify"})
    g.add_edge("verify", "synthesise")
    g.add_edge("synthesise", END)
    return g.compile()


def run_multi(query: str, plan: list[tuple[str, str | None]], handler: Handler, parallel: bool = False) -> dict:
    """Execute a multi-part plan; returns the merged ARIA response (with the node trace under `intent_graph`)."""
    out = build(handler, parallel).invoke({"query": query, "plan": plan, "results": [], "trace": [], "cursor": 0})
    resp = out["response"]
    resp["intent_graph"] = {"nodes": out["trace"]}
    return resp


# ---- rule-based decomposition for C (no model): only splits where each side clearly belongs to a different module ----
_SPLIT = re.compile(r"\s*(?:;|\band then\b|\band also\b|\bthen\b|\balso\b|,\s*and\b|\band\b)\s+", re.I)


def split_by_rules(query: str, label_of: Callable[[str], str | None]) -> list[tuple[str, str | None]]:
    """Split "A and B" only if both halves are real clauses (>= 3 words) that the existing rules place in DIFFERENT modules."""
    pieces = [p.strip(" ,.?") for p in _SPLIT.split(query) if p and p.strip(" ,.?")]
    if len(pieces) < 2:
        return []
    merged: list[tuple[str, str | None]] = []
    for p in pieces:
        lab = label_of(p) if len(p.split()) >= 3 else None
        if merged and (lab is None or lab == merged[-1][1]):
            merged[-1] = (merged[-1][0] + " " + p, merged[-1][1] or lab)  # a fragment or same-module continuation stays with its neighbour
        else:
            merged.append((p, lab))
    labels = [lab for _, lab in merged if lab and lab not in (GENERAL, SMALLTALK, CLARIFY)]
    if len(merged) >= 2 and len(set(labels)) >= 2 and all(lab for _, lab in merged):
        return merged[:4]
    return []
