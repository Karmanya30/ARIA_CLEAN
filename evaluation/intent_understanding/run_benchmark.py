"""Runs one query architecture (A-E) over the benchmark and stores raw per-query results.

Routing is measured with the same offline technique as tests/test_understand.py: every module pipeline is a stub that only records WHICH
branch was reached, so routing quality is separated from answer quality (answer-level checks are in answer_eval.py).
Structured-understanding calls (D, E) go through a disk cache: `--llm record` calls the real model once per distinct input and stores
the output with its latency and token counts; `--llm replay` re-uses it (free, repeatable); `--llm off` disables the model.

usage: python -X utf8 evaluation/intent_understanding/run_benchmark.py --arch D --split dev --llm record
"""
import argparse
import collections
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRATCH = os.environ.get("ARIA_SCRATCH", tempfile.mkdtemp())
os.environ.setdefault("DB_URL", f"sqlite:///{SCRATCH}/intent_bench.db")
os.environ["ARIA_AUTH_MODE"] = "private"
os.environ["ARIA_INTENT_RESOLVER"] = "0"  # the legacy follow-up resolver is an LLM call; it is off in every variant so they differ only in the new layers
os.environ["ARIA_WARMUP"] = "0"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

CACHE_FILE = HERE / "llm_cache.json"
import ai.llm.groq_client as _groq_real  # noqa: E402

REAL_STRUCTURED = _groq_real.generate_structured
CALLS = collections.Counter()


def key_of(prompt: str, system: str) -> str:
    return hashlib.sha256((system + "\x00" + prompt).encode("utf-8")).hexdigest()[:24]


class CachedLLM:
    """Wraps ai.llm.groq_client.generate_structured; one entry per distinct input."""

    def __init__(self, mode: str):
        self.mode = mode
        self.cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
        self.last = {"calls": 0, "ms": 0.0, "tokens": 0, "miss": 0}
        self.dirty = False
        self._tokens = []
        if mode == "record":
            from loguru import logger

            def sink(msg):
                rec = msg.record["extra"]
                if "prompt_tokens" in rec:
                    self._tokens.append((rec.get("prompt_tokens") or 0) + (rec.get("output_tokens") or 0))
            logger.add(sink, level="INFO", filter=lambda r: "prompt_tokens" in r["extra"])

    @staticmethod
    def _bounded(fn, prompt, system_prompt, schema, timeout, hard=60.0):
        """The provider call in a worker thread with a hard limit: a dead connection must not stall the whole run."""
        import threading

        box = {}

        def work():
            box["out"] = fn(prompt, system_prompt=system_prompt, schema=schema, timeout=timeout)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(hard)
        return box.get("out")

    def reset(self):
        self.last = {"calls": 0, "ms": 0.0, "tokens": 0, "miss": 0}

    def __call__(self, prompt, *, system_prompt, schema, timeout=8.0):
        k = key_of(prompt, system_prompt)
        entry = self.cache.get(k)
        if entry is None and self.mode == "record":
            generate_structured = REAL_STRUCTURED  # captured before the harness stubs the model out for pipeline answers

            self._tokens.clear()
            out = None
            started = time.perf_counter()
            for attempt in range(4):
                t_call = time.perf_counter()
                out = self._bounded(generate_structured, prompt, system_prompt, schema, max(timeout, 20.0))
                if out is not None:
                    break
                time.sleep(20 * (attempt + 1))  # per-minute token limit of the free tier: wait for the window to reopen
            if out is not None:  # a failed call is never cached: it would be mistaken for a model answer on replay
                entry = {"out": out, "ms": round((time.perf_counter() - t_call) * 1000, 1), "tokens": sum(self._tokens)}
                self.cache[k] = entry
                self.dirty = True
                if len(self.cache) % 10 == 0:
                    self.save()  # checkpoint: an interruption must not lose recorded calls
            time.sleep(float(os.environ.get("ARIA_BENCH_PACE_S", "9")))  # about 6 calls a minute stays under the free-tier token limit
        if entry is None:
            self.last["miss"] += 1
            return None
        self.last["calls"] += 1
        self.last["ms"] += entry["ms"]
        self.last["tokens"] += entry["tokens"]
        return entry["out"]

    def save(self):
        if self.dirty:
            CACHE_FILE.write_text(json.dumps(self.cache), encoding="utf-8")


def load(split, bench="benchmark_v1.jsonl"):
    items = [json.loads(l) for l in (HERE / bench).read_text(encoding="utf-8").splitlines() if l.strip()]
    return [i for i in items if split == "all" or i["split"] == split or split == "challenge"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=list("ABCDEH"))
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all", "challenge"])
    ap.add_argument("--bench", default="benchmark_v1.jsonl")
    ap.add_argument("--llm", default="replay", choices=["record", "replay", "off"])
    ap.add_argument("--out")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    os.environ["ARIA_QUERY_ARCHITECTURE"] = args.arch
    for k in ("sr_score", "sr_margin", "llm_intent", "llm_context", "sr_veto"):  # thresholds chosen on dev by calibrate.py
        t = HERE / f"thresholds_{args.arch}.json"  # chosen on the dev split by calibrate.py
        if t.exists() and k in json.loads(t.read_text()):
            os.environ.setdefault(f"ARIA_INTENT_{k.upper()}", str(json.loads(t.read_text())[k]))

    import ai.llm.groq_client as groq
    from core import orchestrator
    from core.intent import understanding
    from core.session import clear_session, get_session
    from modules.finance.pipeline import finance_intent
    from shared.understand import normalize

    llm = CachedLLM(args.llm if args.arch in ("D", "E", "H") else "off")

    def stub(name):
        def f(*a, **k):
            CALLS[name] += 1
            return {"domain": name, "response": f"stub {name}"}
        return f

    def fake_lookup(shown, normalised, owner, history):
        from modules.qa import lookup
        if not lookup.is_data_question(shown) and not lookup.is_data_question(normalised):
            return None
        # The real decision: a name in the local instrument catalogue (no Yahoo call in the benchmark), or a named thing that would go to web search.
        if lookup.find_instrument(shown, normalised) or (lookup._has_proper_noun(shown) and lookup.candidates(shown)):
            return {"domain": "data_lookup", "response": "stub"}
        return None

    def understand(query, history):
        if args.llm == "off":
            return None, {"status": "unavailable", "latency_ms": 0.0}
        return understanding.understand(query, history, caller=llm)

    patches = [
        mock.patch.multiple(orchestrator, company_intelligence=stub("company_intelligence"), equity_research_pipeline=stub("equity_research"),
                            market_pipeline=stub("market"), finance_pipeline=stub("finance"), tutor_pipeline=stub("tutor"),
                            validate_output=lambda *a: {"available": False},
                            _smalltalk_reply=lambda q: {"domain": "smalltalk", "query": q, "response": "hi"},
                            _general_reply=lambda q: {"domain": "general", "query": q, "response": "stub"},
                            news_context=lambda q: contextlib.nullcontext([]), _understand=understand),
        mock.patch("modules.qa.lookup.data_answer", fake_lookup),
        mock.patch("modules.market.instruments._yahoo_lookup", lambda q: []),  # benchmark stays offline; the local catalogue still answers
        mock.patch.object(groq, "generate_response", lambda *a, **k: "Error: stubbed"),
        mock.patch.object(groq, "generate_structured", lambda *a, **k: None),
    ]
    items = load(args.split, args.bench)
    rows = []
    seen_scen = set()
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        orchestrator.handle_query("hello", session_id="__warm")  # exclude one-time model loading from latency
        if args.arch in ("B", "D", "E", "H"):
            from core.intent import semantic
            semantic.classify("warm up")
        clear_session("__warm")
        for it in items:
            sid = f"__ib_{it['scenario'] or it['id']}"
            if it["scenario"] and it["turn"] == 1 and it["scenario"] not in seen_scen:
                clear_session(sid)
            elif not it["scenario"]:
                clear_session(sid)
            seen_scen.add(it["scenario"])
            get_session(sid)["adapt_tone"] = True
            llm.reset()
            t0 = time.perf_counter()
            err = None
            try:
                r = orchestrator.handle_query(it["query"], session_id=sid)
            except Exception as exc:  # a crash is a routing failure
                r, err = {}, f"{type(exc).__name__}: {exc}"[:160]
            ms = (time.perf_counter() - t0) * 1000
            label = r.get("domain", "EXC")
            if label == "finance" and (hit := finance_intent(normalize(it["query"])[0])):
                label = "finance"
            parts = [p.get("domain") for p in r.get("parts", [])] if r.get("multi_part") else []
            route = r.get("intent_route") or {}
            rows.append(dict(id=it["id"], category=it["category"], split=it["split"], query=it["query"], scenario=it["scenario"], turn=it["turn"],
                             expected=it["expected_primary"], acceptable=it["acceptable"], secondary=it["secondary"], entities_expected=it["entities"],
                             got=label, got_parts=parts, clarified=label == "clarify", latency_ms=round(ms, 1),
                             llm_calls=llm.last["calls"], llm_ms=round(llm.last["ms"], 1), llm_tokens=llm.last["tokens"], llm_miss=llm.last["miss"],
                             route=route, error=err))
            if not it["scenario"]:
                clear_session(sid)
    llm.save()
    out = Path(args.out) if args.out else HERE / "results" / f"{args.arch}{args.tag}_{args.split}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"arch": args.arch, "split": args.split, "llm": args.llm, "n": len(rows), "rows": rows,
                               "env": {k: v for k, v in os.environ.items() if k.startswith("ARIA_INTENT") or k in ("ARIA_QUERY_ARCHITECTURE", "ARIA_SR_MODE")}},
                              indent=0), encoding="utf-8")
    acc = sum(r["got"] == r["expected"] or r["got"] in r["acceptable"] for r in rows)
    print(f"arch={args.arch} split={args.split} n={len(rows)} lenient-correct={acc} ({acc / max(1, len(rows)):.1%}) "
          f"llm_calls={sum(r['llm_calls'] for r in rows)} misses={sum(r['llm_miss'] for r in rows)} -> {out}")


if __name__ == "__main__":
    main()
