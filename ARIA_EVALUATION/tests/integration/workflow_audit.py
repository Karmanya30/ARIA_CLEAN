"""Offline agent-workflow audit probes (no network, no LLM, no server). Every model call, pipeline and classifier is a stub.
usage: OMP_NUM_THREADS=2 python -X utf8 workflow_audit.py [--json out.json]
Each probe prints PASS/FAIL against the EXPECTED-SAFE behaviour and the observed facts; FAIL = a finding."""
import argparse, contextlib, json, os, sys, tempfile, threading, time
from unittest import mock

SCRATCH = os.environ.get("ARIA_SCRATCH", tempfile.mkdtemp())
os.environ["DB_URL"] = f"sqlite:///{SCRATCH}/workflow_audit.db"
os.environ["ARIA_AUTH_MODE"] = "private"
for k, v in dict(ARIA_INTENT_RESOLVER="0", ARIA_MEMORY_SEMANTIC="0", ARIA_WARMUP="0", ARIA_SENTIMENT="0", FI_NEWS_RSS="0").items():
    os.environ.setdefault(k, v)
ROOT = os.environ.get("ARIA_ROOT", "E:/ARIA")
sys.path.insert(0, ROOT); os.chdir(ROOT)

import ai.llm.groq_client as groq
from core import orchestrator as orc
from core import session as sess
from core.intent import arch, graph, semantic

RES = []
def rec(pid, ok, facts):
    RES.append(dict(id=pid, ok=bool(ok), facts=facts)); print(("PASS " if ok else "FAIL ") + pid, json.dumps(facts, default=str)[:600])

def stub(name, calls, boom=None):
    def f(*a, **k):
        calls.append(name)
        if boom and boom(calls.count(name)): raise RuntimeError("injected " + name)
        return {"domain": name, "response": f"{name} stub answer", "query": a[0] if a else ""}
    return f

def common_patches(calls, **over):
    base = dict(company_intelligence=stub("company_intelligence", calls), equity_research_pipeline=stub("equity_research", calls),
                market_pipeline=stub("market", calls), finance_pipeline=stub("finance", calls), tutor_pipeline=stub("tutor", calls),
                validate_output=lambda *a: {"available": False},
                _smalltalk_reply=lambda q: {"domain": "smalltalk", "query": q, "response": "hi"},
                _general_reply=lambda q: (calls.append("general") or {"domain": "general", "query": q, "response": "general model answer"}),
                news_context=lambda q: contextlib.nullcontext([]))
    base.update(over)
    return [mock.patch.multiple(orc, **base), mock.patch.object(groq, "generate_response", lambda *a, **k: "Error: stubbed"),
            mock.patch.object(groq, "generate_structured", lambda *a, **k: None),
            mock.patch.object(semantic, "classify", lambda q: semantic.SemanticChoice(label=None))]

@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update(kv)
    try: yield
    finally:
        for k, o in old.items():
            os.environ.pop(k, None) if o is None else os.environ.__setitem__(k, o)

# ---- P1 graph: retry, partial, all-failed, error text ------------------------------------------------
def p1():
    n = {"a": 0}
    def flaky(q, lab):
        n["a"] += 1
        if "first" in q and n["a"] == 1: raise RuntimeError("boom")
        return {"domain": lab, "response": f"ok {lab}"}
    r = graph.run_multi("x", [("first part here", "market"), ("second part here", "tutor")], flaky)
    rec("P1a graph retries a part once after exception", r["parts"][0]["ok"] and n["a"] == 3, dict(calls=n["a"], parts=r["parts"]))
    def dead(q, lab): raise RuntimeError("down")
    r = graph.run_multi("x", [("one aaa", "market"), ("two bbb", "tutor")], dead)
    g = r["grounding"]
    rec("P1b all parts fail -> honest text, numbers_checked must not be vacuously True", g["numbers_checked"] is False and g["passed"] is False,
        dict(grounding=g, response=r["response"][:160]))
    def err_text(q, lab): return {"domain": lab, "response": "Error: all backends failed"}
    r = graph.run_multi("x", [("one aaa", "market"), ("two bbb", "tutor")], err_text)
    rec("P1c handler returns 'Error:' text -> part marked failed, never shown", "Error:" not in r["response"], dict(parts=r["parts"]))
    r = graph.run_multi("x", [("one aaa", "market"), ("two bbb", "equity_research")],
                        lambda q, lab: {"domain": lab, "response": "r", "context": {"from": lab}, "report_id": lab})
    rec("P1e merged reply carries only first part's evidence (context/report_id)", r.get("report_id") != "market", dict(report_id=r.get("report_id"), context=r.get("context")))

# ---- P2 session lock vs LangGraph parallel fan-out ---------------------------------------------------------
def p2():
    def worker_handler(q, lab):
        with sess.session_lock("sid-par"):  # what any real pipeline does via get_session/save_turn
            return {"domain": lab, "response": "ok"}
    def run(parallel, out):
        with sess.session_lock("sid-par"):
            out.append(graph.run_multi("x", [("one aaa", "market"), ("two bbb", "tutor")], worker_handler, parallel=parallel)["parts"])
    for parallel in (False, True):
        out = []
        t = threading.Thread(target=run, args=(parallel, out), daemon=True); t.start(); t.join(4)
        finished = not t.is_alive()
        rec(f"P2 session lock held + graph parallel={parallel}", finished if not parallel else True,
            dict(finished=finished, note="parallel=True is expected to deadlock when workers take the held session lock (documented); production uses parallel=False"))
    prod = open(os.path.join(ROOT, "core/orchestrator.py"), encoding="utf8").read()
    rec("P2b production call site never passes parallel=True", "parallel=True" not in prod, {})

# ---- P3 variant path: handler exception -> baseline reruns the same pipeline ----------------------------
def p3():
    calls = []
    # variant B: the semantic router (stubbed) picks "market" for a question the rules cannot place; the market pipeline then fails once
    pat = common_patches(calls, market_pipeline=stub("market", calls, lambda k: k == 1))
    with contextlib.ExitStack() as st, env(ARIA_QUERY_ARCHITECTURE="B"):
        [st.enter_context(p) for p in pat]
        st.enter_context(mock.patch.object(semantic, "classify", lambda q: semantic.SemanticChoice(label="market", score=0.9, margin=0.5, engine="stub")))
        sid = "p3"; sess.clear_session(sid)
        try:
            r = orc.handle_query("tell me something unusual about gardening", session_id=sid); err = None
        except Exception as e: r, err = {}, repr(e)
    calls2 = []
    with contextlib.ExitStack() as st, env(ARIA_QUERY_ARCHITECTURE="B", ARIA_SR_MODE="override"):
        [st.enter_context(p) for p in common_patches(calls2, market_pipeline=stub("market", calls2, lambda k: True))]
        st.enter_context(mock.patch.object(semantic, "classify", lambda q: semantic.SemanticChoice(label="market", score=0.9, margin=0.5, engine="stub")))
        sess.clear_session("p3b")
        try: orc.handle_query("how is the nifty doing today", session_id="p3b"); e2 = None
        except Exception as e: e2 = repr(e)
    rec("P3b variant agrees with rules and market pipeline always fails: it must not be invoked twice for one turn", calls2.count("market") <= 1, dict(market_calls=calls2.count("market"), err=e2))
    rec("P3 variant B: market pipeline fails once -> variant swallows it and baseline re-runs; failing pipeline must not run twice", calls.count("market") <= 1,
        dict(market_calls=calls.count("market"), calls=calls, err=err, domain=r.get("domain")))

# ---- P4 baseline: pipeline exception propagates; turn becomes interrupted; retry with same request_id works ---
def p4():
    from shared import conversation_memory as m
    calls = []
    sid = "p4"; sess.clear_session(sid)
    pat = common_patches(calls, market_pipeline=stub("market", calls, lambda k: k == 1))
    with contextlib.ExitStack() as st, env(ARIA_QUERY_ARCHITECTURE="baseline"):
        [st.enter_context(p) for p in pat]
        q = "how is the nifty doing today"
        try:
            sess.execute_turn(sid, q, lambda: orc._handle_query(q, sid), "rid-1"); exc = None
        except Exception as e: exc = repr(e)
        with m.store._SessionLocal() as db:
            st1 = db.query(m.Turn).filter_by(request_id="rid-1").one().status
        r = sess.execute_turn(sid, q, lambda: orc._handle_query(q, sid), "rid-1")
        r2 = sess.execute_turn(sid, q, lambda: (_ for _ in ()).throw(AssertionError("replay must not re-run")), "rid-1")
    rec("P4a unhandled module exception reaches caller (orchestrator has no degraded reply)", exc is None, dict(exc=exc, turn_status=st1))
    rec("P4b retry same request_id after failure re-executes, then replays without re-running", r["domain"] == "market" and r2["domain"] == "market", dict(calls=calls))

# ---- P5 same-session concurrency ---------------------------------------------------------------------------
def p5():
    sid = "p5"; sess.clear_session(sid); n = {"x": 0}; order = []
    def act(tag):
        def f():
            order.append(("in", tag)); n["x"] += 1; time.sleep(0.3); order.append(("out", tag)); return {"domain": "general", "response": tag}
        return f
    res = []
    ts = [threading.Thread(target=lambda: res.append(sess.execute_turn(sid, "same q", act("A"), "rid-same"))) for _ in range(3)]
    [t.start() for t in ts]; [t.join(10) for t in ts]
    rec("P5a 3 concurrent identical request_id -> action ran once", n["x"] == 1 and len(res) == 3, dict(runs=n["x"], results=len(res)))
    order.clear(); res.clear()
    ts = [threading.Thread(target=lambda i=i: res.append(sess.execute_turn(sid, f"q{i}", act(f"T{i}"), f"r{i}"))) for i in range(3)]
    t0 = time.perf_counter(); [t.start() for t in ts]; [t.join(10) for t in ts]
    rec("P5b distinct requests same session serialise (no interleave)", all(order[i][0] == "in" and order[i + 1][0] == "out" for i in range(0, 6, 2)), dict(elapsed=round(time.perf_counter() - t0, 2)))
    t0 = time.perf_counter(); res.clear()
    ts = [threading.Thread(target=lambda i=i: res.append(sess.execute_turn(f"s{i}", "q", act("S"), f"r{i}"))) for i in range(3)]
    [t.start() for t in ts]; [t.join(10) for t in ts]
    rec("P5c different sessions run in parallel", time.perf_counter() - t0 < 0.8, dict(elapsed=round(time.perf_counter() - t0, 2)))
    rec("P5d _LOCKS/_SESSIONS are evicted per session (they are not)", len(sess._LOCKS) < 3, dict(locks=len(sess._LOCKS), sessions=len(sess._SESSIONS)))

# ---- P6 output guard pool starvation -------------------------------------------------------------------------
def p6():
    ev = threading.Event()
    with mock.patch.object(orc, "validate_output", lambda q, t: (ev.wait(6), {"available": True})[1]), mock.patch.object(orc, "GUARD_TIMEOUT_S", 0.3):
        got = []
        for _ in range(6):
            got.append(orc._output_guard("q", "a")["available"])
        stuck = orc._GUARD_POOL._work_queue.qsize()
    ev.set()
    rec("P6 timed-out guard calls free their pool slot (4 workers; 6 slow calls)", stuck == 0, dict(available=got, still_queued_behind_stuck_workers=stuck))

# ---- P7 LLM client failure chain --------------------------------------------------------------------------------
def p7():
    calls = []; sleeps = []
    def bad(name):
        def f(p, s, m=None): calls.append(name); raise RuntimeError("429 rate limit exceeded; try again in 3.0s")
        return f
    with mock.patch.object(groq, "_BACKENDS", (("groq", bad("groq")), ("gemini", bad("gemini")))), mock.patch.object(groq, "_call_groq", bad("groq-fallback")), \
         mock.patch.object(groq.time, "sleep", lambda s: sleeps.append(s)):
        groq._dead.clear(); out = groq.generate_response("hi", system_prompt="x")
    rec("P7a all providers 429: returns 'Error:' string after 2 passes of the chain, with sleeps", out.startswith("Error:"), dict(calls=len(calls), order=calls[:4], sleeps=sleeps))
    calls.clear(); sleeps.clear()
    def quota(name):
        def f(p, s, m=None): calls.append(name); raise RuntimeError("tokens per day (TPD) limit reached")
        return f
    with mock.patch.object(groq, "_BACKENDS", (("groq", quota("groq")), ("gemini", quota("gemini")))), mock.patch.object(groq, "_call_groq", quota("fb")), mock.patch.object(groq.time, "sleep", lambda s: sleeps.append(s)):
        groq._dead.clear(); groq.generate_response("hi", system_prompt="x"); first = len(calls); calls.clear(); groq.generate_response("hi", system_prompt="x"); second = len(calls)
        dead = list(groq._dead); groq._dead.clear()
    rec("P7b daily-quota backends skipped on later calls", second < first, dict(first=first, second=second, dead_keys=dead))
    import inspect
    src = inspect.getsource(groq._call_groq) + inspect.getsource(groq._call_gemini)
    rec("P7c main-path Groq/Gemini calls set an explicit timeout", "timeout" in src, dict(has_timeout_arg="timeout" in src))
    try:
        import groq as g
        print("   groq SDK DEFAULT_TIMEOUT / DEFAULT_MAX_RETRIES:", g.DEFAULT_TIMEOUT, getattr(g, "DEFAULT_MAX_RETRIES", None))
    except Exception as e: print("   groq SDK defaults unavailable:", repr(e)[:80])

# ---- P8 multi-part: data_lookup returns None -> general model answers under 'Data' ---------------------------
def p8():
    calls = []
    with contextlib.ExitStack() as st, env(ARIA_QUERY_ARCHITECTURE="E", ARIA_INTENT_LLM="0"):
        [st.enter_context(p) for p in common_patches(calls)]
        st.enter_context(mock.patch("modules.qa.lookup.data_answer", lambda *a, **k: None))
        plan = [("revenue of Obscure Widgets Ltd please", "data_lookup"), ("what is a SIP and how does it work", "tutor")]
        resp = graph.run_multi("q", plan, lambda text, label: orc._run_label(label or "general", text, text, "p8") or orc._with_news(text, orc._general_reply))
    rec("P8 multi-part 'Data' part must not be answered by the ungrounded general model", "general" not in calls,
        dict(calls=calls, part_domains=[p["domain"] for p in resp["parts"]], text=resp["response"][:220]))

# ---- P9 variants with LLM + router down ---------------------------------------------------------------------------
def p9():
    out = {}
    for a in ("B", "C", "D", "E", "H"):
        calls = []
        with contextlib.ExitStack() as st, env(ARIA_QUERY_ARCHITECTURE=a):
            [st.enter_context(p) for p in common_patches(calls)]
            sess.clear_session("p9" + a)
            try:
                r = orc.handle_query("how is the nifty doing and what is a SIP", session_id="p9" + a); out[a] = (r["domain"], calls)
            except Exception as e: out[a] = ("EXC " + repr(e)[:80], calls)
    rec("P9 every variant survives LLM+router down (no exception)", all(not v[0].startswith("EXC") for v in out.values()), out)
    calls = []
    with contextlib.ExitStack() as st, env(ARIA_QUERY_ARCHITECTURE="B"):
        [st.enter_context(p) for p in common_patches(calls)]
        st.enter_context(mock.patch.object(semantic, "classify", mock.Mock(side_effect=RuntimeError("encoder missing"))))
        sess.clear_session("p9x")
        try: r = orc.handle_query("tell me something unusual about gardening", session_id="p9x"); e = None
        except Exception as ex: r, e = {}, repr(ex)
    rec("P9b semantic router raising -> swallowed, baseline answers", e is None, dict(exc=e, domain=r.get("domain")))

# ---- P10 crisis gate makes zero model calls ---------------------------------------------------------------------------
def p10():
    calls = []; llm = []
    with contextlib.ExitStack() as st:
        [st.enter_context(p) for p in common_patches(calls)]
        st.enter_context(mock.patch.object(groq, "generate_response", lambda *a, **k: llm.append(1) or "x"))
        sess.clear_session("p10")
        r = orc.handle_query("I want to end my life, I lost everything", session_id="p10")
    rec("P10 crisis message -> fixed care reply, no pipeline, no LLM", r["domain"] == "care" and not calls and not llm, dict(domain=r["domain"], calls=calls, llm=len(llm)))

# ---- P11 dead code -------------------------------------------------------------------------------------------------------
def p11():
    import subprocess
    out = subprocess.run(["git", "grep", "-n", "forced_label", "--", "*.py"], capture_output=True, text=True).stdout.strip().splitlines()
    rec("P11 arch.forced_label ContextVar is used somewhere besides its definition", len(out) > 1, dict(hits=out))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--json"); a = ap.parse_args()
    for f in (p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
        try: f()
        except Exception as e: rec(f.__name__ + " CRASHED", False, dict(err=repr(e)[:300]))
    if a.json: json.dump(RES, open(a.json, "w"), indent=1, default=str)
    print(f"\n{sum(r['ok'] for r in RES)}/{len(RES)} expected-safe")
