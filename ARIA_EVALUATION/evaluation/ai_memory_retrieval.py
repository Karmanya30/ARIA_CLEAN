"""Conversation-memory retrieval benchmark (shared/conversation_memory.py) on a synthetic, isolated DB. No LLM.
Run with DB_URL=sqlite:///<scratch>/mem.db. Measures recall@5 / MRR (lexical-only vs +semantic), follow-up reference
resolution, correction supersede, clear boundary, owner isolation, token-budget inclusion and latency vs archive size."""
import json, os, statistics, sys, time
sys.path.insert(0, r"E:\ARIA")
assert "DB_URL" in os.environ and "ai" in os.environ["DB_URL"], "set DB_URL to a scratch file"
from shared import conversation_memory as memory, user_store
from core import session

OWNER = "synthetic-eval-owner"
FILLER = ("Here is a general explanation. " * 25)  # ~750 chars, what a normal assistant answer weighs
FACTS = [  # (fact the user stated, lexical query sharing words, paraphrase query sharing none)
    ("My target retirement age is 58 and I want 4 crore by then", "retirement age target", "when do I plan to stop working"),
    ("My home loan rate is 8.65 percent with Kotak", "home loan rate Kotak", "what interest am I paying on my mortgage"),
    ("I want no small cap funds, my risk appetite is low", "small cap funds risk appetite", "what kind of volatility can I tolerate"),
    ("My daughter's college fund target is 40 lakh by 2035", "daughter college fund target", "saving for my child's education"),
    ("I stopped my Axis Bluechip SIP in March", "Axis Bluechip SIP stopped", "which monthly investment did I discontinue"),
    ("Our family health insurance cover is 15 lakh with Niva Bupa", "health insurance cover Niva Bupa", "how much medical protection do we have"),
    ("I rent my flat in Pune for 22000 a month", "rent flat Pune", "income from my property"),
    ("My employer matches 12 percent of basic into EPF", "employer EPF basic", "provident fund contribution from my company"),
    ("I hold 200 shares of Tata Steel bought at 118", "Tata Steel shares bought", "my steel stock purchase price"),
    ("My emergency fund sits in a Fino liquid fund", "emergency fund Fino liquid", "where is my rainy day money kept"),
]
CORR = ("Correction: my monthly salary is now 95000, not 80000", "what is my monthly salary", "salary")


def build(n_distractors, owner=OWNER, extra_owner=True):
    tok = user_store.current_owner.set(owner)
    ids = {}
    try:
        for i, (fact, _, _) in enumerate(FACTS):
            sid = f"ep-{n_distractors}-{i}"
            session.execute_turn(sid, fact, lambda: {"domain": "general", "response": "Noted. " + FILLER[:300]})
            ids[i] = session.get_session(sid)["history"][-1]["message_id"]
        session.execute_turn(f"sal-old-{n_distractors}", "My monthly salary is 80000", lambda: {"domain": "general", "response": "Noted."})
        session.execute_turn(f"sal-new-{n_distractors}", CORR[0], lambda: {"domain": "general", "response": "Updated."})
        ids["corr"] = session.get_session(f"sal-new-{n_distractors}")["history"][-1]["message_id"]
        ids["old"] = session.get_session(f"sal-old-{n_distractors}")["history"][-1]["message_id"]
        topics = ["nifty outlook", "what is an ETF", "tax on mutual funds", "how to pick a fund", "explain compound interest", "gold price view",
                  "budget for a trip", "car loan EMI", "what is a bond", "inflation and savings", "how do dividends work", "credit card rewards"]
        for j in range(n_distractors):
            session.execute_turn(f"dist-{n_distractors}", f"{topics[j % len(topics)]} number {j}", lambda: {"domain": "tutor", "response": FILLER})
    finally:
        user_store.current_owner.reset(tok)
    return ids


def rank_of(records, target):
    ranked = sorted(records, key=lambda r: r["retrieval_score"], reverse=True)[:5]
    idl = [r["id"] for r in ranked]
    return idl.index(target) + 1 if target in idl else None


def run_queries(ids, kind, semantic):
    os.environ["ARIA_MEMORY_SEMANTIC"] = "1" if semantic else "0"
    out, lat = [], []
    tok = user_store.current_owner.set(OWNER)
    try:
        for i, (_, lex, para) in enumerate(FACTS):
            q = lex if kind == "lexical" else para
            t = time.perf_counter(); recs, diag = memory.retrieve("eval-query-session", q, limit=12); lat.append((time.perf_counter() - t) * 1000)
            out.append({"q": q, "rank": rank_of(recs, ids[i]), "semantic": diag["semantic"], "n_records": diag["archive_records"]})
    finally:
        user_store.current_owner.reset(tok)
    r = [o["rank"] for o in out]
    return {"kind": kind, "semantic_flag": semantic, "recall_at_5": sum(x is not None for x in r) / len(r),
            "mrr_at_5": round(sum(1 / x for x in r if x) / len(r), 3), "p50_ms": round(statistics.median(lat), 1),
            "p95_ms": round(sorted(lat)[max(0, int(.95 * len(lat)) - 1)], 1), "detail": out}


if __name__ == "__main__":
    results = {}
    for n in (40, 400):
        ids = build(n)
        results[f"archive_{n}"] = [run_queries(ids, k, s) for k in ("lexical", "paraphrase") for s in (False, True)]
        # correction supersede: does the corrected fact appear among selected records, and is the old one also present (acceptable)?
        os.environ["ARIA_MEMORY_SEMANTIC"] = "1"
        tok = user_store.current_owner.set(OWNER)
        try:
            recs, _ = memory.retrieve("eval-query-session", CORR[1], limit=12)
            sel = [r["id"] for r in recs]
            results[f"archive_{n}_correction"] = {"corrected_in_selected": ids["corr"] in sel, "old_in_selected": ids["old"] in sel}
            # token budget: what fraction of selected records survives the 6000 'token' budget
            ctx = memory.build_context("eval-query-session", "what is my retirement age target")
            d = ctx["diagnostics"]
            results[f"archive_{n}_budget"] = {"included": len(d["included_ids"]), "excluded": len(d["excluded_ids"]), "memory_tokens": d["memory_tokens"],
                                              "counter": d["token_counter"], "target_included": ids[0] in d["included_ids"], "text_chars": len(ctx["text"])}
            # follow-up with a pronoun in a conversation that holds the antecedent
            sid = f"follow-{n}"
            session.execute_turn(sid, "Tell me about the Axis Bluechip fund", lambda: {"domain": "instrument", "response": "Axis Bluechip is a large-cap fund."})
            ctx = memory.build_context(sid, "what are its returns?")
            results[f"archive_{n}_followup"] = {"reference_resolved": ctx["diagnostics"]["reference_resolved"],
                                                "antecedent_in_context": "Axis Bluechip" in ctx["text"]}
            # owner isolation: another owner must not retrieve OWNER's facts
        finally:
            user_store.current_owner.reset(tok)
        tok = user_store.current_owner.set("someone-else")
        try:
            recs, _ = memory.retrieve("other-session", "retirement age target", limit=12)
            results[f"archive_{n}_isolation"] = {"records_visible_to_other_owner": len(recs), "leaked": any("retirement age" in r["query"] for r in recs)}
        finally:
            user_store.current_owner.reset(tok)
        # clear boundary
        tok = user_store.current_owner.set(OWNER)
        try:
            session.clear_session(f"ep-{n}-0")
            recs, _ = memory.retrieve("eval-query-session", "retirement age target", limit=12)
            results[f"archive_{n}_clear"] = {"cleared_fact_still_retrievable": ids[0] in [r["id"] for r in recs]}
        finally:
            user_store.current_owner.reset(tok)
    # latency scaling (semantic on, warm embedding cache vs cold)
    json.dump(results, open(r"E:\ARIA\ARIA_EVALUATION\evaluation\ai_memory_retrieval_results.json", "w", encoding="utf-8"), indent=1)
    for k, v in results.items():
        if isinstance(v, list):
            for e in v:
                print(k, e["kind"], "sem" if e["semantic_flag"] else "lex", "recall@5", e["recall_at_5"], "mrr", e["mrr_at_5"], "p50", e["p50_ms"], "p95", e["p95_ms"], "records", e["detail"][0]["n_records"], "status", e["detail"][0]["semantic"])
        else:
            print(k, v)
