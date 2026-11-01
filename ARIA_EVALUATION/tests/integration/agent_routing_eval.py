"""Routing accuracy of ARIA's rule+model hybrid router, measured in-process. No network, no LLM, no microphone:
every module pipeline, the LLM client, news, the output guard and the instrument/web lookup are stubs that only record WHICH
branch was reached (same technique as tests/test_understand.py::route_label). The intent-resolver LLM is "down"
(generate_structured -> None), so this measures the deterministic rule layer; follow-ups that need the resolver are counted.

usage: python -X utf8 agent_routing_eval.py [--tone on|off] [--json out.json]
"""
import argparse
import collections
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

SCRATCH = os.environ.get("ARIA_SCRATCH", tempfile.mkdtemp())
os.environ.setdefault("DB_URL", f"sqlite:///{SCRATCH}/agents_routing.db")
os.environ["ARIA_AUTH_MODE"] = "private"
ROOT = os.environ.get("ARIA_ROOT", "E:/ARIA")  # E:/ARIA = working tree; scratchpad/base = git archive of 984ffbb
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).parent))
os.chdir(ROOT)

from routing_dataset import SCENARIOS, SINGLE  # noqa: E402

import ai.llm.groq_client as groq  # noqa: E402
from core import orchestrator  # noqa: E402
from core.session import clear_session, get_session  # noqa: E402
from modules.finance.pipeline import finance_intent  # noqa: E402
from shared.understand import normalize  # noqa: E402

CALLS = collections.Counter()


def stub(name):
    def f(*a, **k):
        CALLS[name] += 1
        return {"domain": name, "response": "stub"}
    return f


def fake_lookup(shown, normalised, owner, history):
    from modules.qa import lookup
    if not lookup.is_data_question(shown) and not lookup.is_data_question(normalised):
        return None
    if lookup._has_proper_noun(shown) and lookup.candidates(shown):  # stand-in for "catalogue hit or web search finds something"
        return {"domain": "data_lookup", "response": "stub"}
    return None


def patches(tone):
    return [
        mock.patch.multiple(orchestrator, company_intelligence=stub("company_intelligence"), equity_research_pipeline=stub("equity_research"),
                            market_pipeline=stub("market"), finance_pipeline=stub("finance"), tutor_pipeline=stub("tutor"),
                            validate_output=lambda *a: {"available": False},
                            _smalltalk_reply=lambda q: {"domain": "smalltalk", "query": q, "response": "hi"},
                            _general_reply=lambda q: {"domain": "general", "query": q, "response": "stub"},
                            news_context=lambda q: contextlib.nullcontext([])),
        mock.patch("modules.qa.lookup.data_answer", fake_lookup),
        mock.patch.object(groq, "generate_response", lambda *a, **k: "Error: stubbed"),
        mock.patch.object(groq, "generate_structured", lambda *a, **k: None),
    ]


def run_turn(sid, query, tone):
    get_session(sid)["adapt_tone"] = tone
    r = orchestrator.handle_query(query, session_id=sid)
    label = r["domain"]
    if label == "finance" and (hit := finance_intent(normalize(query)[0])):
        label += ":" + hit[0]
    return label, r


def ok(label, primary, alts):
    base = label.split(":")[0]
    return base == primary, base == primary or base in alts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tone", default="on")
    ap.add_argument("--json")
    args = ap.parse_args()
    tone = args.tone == "on"
    rows, confusion = [], collections.Counter()
    with contextlib.ExitStack() as st:
        for p in patches(tone):
            st.enter_context(p)
        for i, (q, primary, alts, tag) in enumerate(SINGLE):
            sid = f"__rt_{i}"
            clear_session(sid)
            try:
                label, r = run_turn(sid, q, tone)
                err = None
            except Exception as exc:  # a crash is a routing defect
                label, r, err = "EXC", {}, f"{type(exc).__name__}: {exc}"[:200]
            clear_session(sid)
            strict, lenient = ok(label, primary, alts)
            res = (r.get("intent_resolution") or {})
            rows.append(dict(kind="single", q=q, tag=tag, expected=primary, alts=list(alts), got=label, strict=strict, lenient=lenient,
                             resolver_attempted=bool(res.get("attempted")), resolver_status=res.get("status"), err=err))
            if not lenient:
                confusion[(primary, label.split(":")[0])] += 1
        for name, turns in SCENARIOS.items():
            sid = f"__rt_sc_{name}"
            clear_session(sid)
            for j, (q, primary, alts) in enumerate(turns):
                try:
                    label, r = run_turn(sid, q, tone)
                    err = None
                except Exception as exc:
                    label, r, err = "EXC", {}, f"{type(exc).__name__}: {exc}"[:200]
                strict, lenient = ok(label, primary, alts)
                res = (r.get("intent_resolution") or {})
                rows.append(dict(kind="multi:" + name, q=q, tag=f"turn{j + 1}", expected=primary, alts=list(alts), got=label,
                                 strict=strict, lenient=lenient, resolver_attempted=bool(res.get("attempted")),
                                 resolver_status=res.get("status"), err=err))
                if not lenient:
                    confusion[(primary, label.split(":")[0])] += 1
            clear_session(sid)

    def acc(sel):
        n = len(sel)
        return n, sum(r["strict"] for r in sel), sum(r["lenient"] for r in sel)

    out = {"tone": args.tone, "total": acc(rows), "single": acc([r for r in rows if r["kind"] == "single"]),
           "multi": acc([r for r in rows if r["kind"].startswith("multi")])}
    print(f"tone={args.tone}  total n/strict/lenient={out['total']}  single={out['single']}  multi={out['multi']}")
    print("\nper expected label (n, strict, lenient):")
    for lab in sorted({r["expected"] for r in rows}):
        print(f"  {lab:22s}", acc([r for r in rows if r["expected"] == lab]))
    print("\nper tag (single):")
    for tag in sorted({r["tag"] for r in rows if r["kind"] == "single"}):
        print(f"  {tag:12s}", acc([r for r in rows if r["kind"] == "single" and r["tag"] == tag]))
    print("\nconfusion pairs (expected -> got) on lenient failures:")
    for (a, b), n in confusion.most_common():
        print(f"  {a} -> {b}: {n}")
    att = [r for r in rows if r["resolver_attempted"]]
    print(f"\nresolver (LLM) attempted on {len(att)} of {len(rows)} turns; statuses:", collections.Counter(r["resolver_status"] for r in att))
    print("\nFAILURES (lenient):")
    for r in rows:
        if not r["lenient"]:
            print(f"  [{r['kind']}/{r['tag']}] {r['q']!r}: expected {r['expected']}{r['alts'] or ''} got {r['got']} {r['err'] or ''}")
    print("\nSTRICT-ONLY misses (accepted alternate used):")
    for r in rows:
        if r["lenient"] and not r["strict"]:
            print(f"  {r['q']!r}: expected {r['expected']} got {r['got']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": out, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
