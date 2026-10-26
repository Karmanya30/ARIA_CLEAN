"""Fixed-label synthetic routing ablation. --live makes bounded Groq calls.

Financial, tutor and research workflows are stubbed: this evaluates routing
and reference reconstruction, not financial results or answer quality.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from loguru import logger

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import orchestrator, session
from shared import user_store
from ai.llm import groq_client


def evaluate(live: bool = False) -> dict:
    cases = json.loads((Path(__file__).resolve().parents[1] / "tests/intent_evaluation_cases.json").read_text(encoding="utf-8"))
    output = {"dataset": "12 independently specified synthetic cases with expected routes/required reference terms",
              "live_model": groq_client.MODEL_NAME if live else None, "modes": {}}
    with tempfile.TemporaryDirectory(prefix="aria-intent-eval-") as directory:
        engine = create_engine("sqlite:///" + (Path(directory) / "eval.db").as_posix())
        user_store.Base.metadata.create_all(engine)
        owner_token = user_store.current_owner.set("synthetic-intent-evaluation")
        original_cache = session._SESSIONS.copy()
        usage = []
        sink = logger.add(lambda msg: usage.append(msg.record["extra"]) if msg.record["message"] == "llm_usage" else None)
        try:
            for mode in (["baseline", "resolver"] if live else ["baseline"]):
                rows = []
                with patch.object(user_store, "_SessionLocal", sessionmaker(bind=engine)), patch.dict(os.environ, {
                    "ARIA_INTENT_RESOLVER": "1" if mode == "resolver" else "0",
                    "ARIA_MEMORY_SEMANTIC": "0", "FI_NEWS_RSS": "0"}):
                    for case in cases:
                        sid = mode + ":" + case["id"]
                        session._SESSIONS.clear()
                        # Seed sources without running the resolver or answer provider.
                        for user, assistant in case["history"]:
                            session.save_turn(sid, user, {"response": assistant})
                        session.get_session(sid)["adapt_tone"] = False
                        calls = []
                        def stub(route):
                            def run(query, **kw):
                                calls.append((route, kw.get("intent_query") or query))
                                return {"domain": route, "response": "Synthetic workflow stub."}
                            return run
                        started = time.perf_counter()
                        usage_start = len(usage)
                        with patch.multiple(orchestrator, equity_research_pipeline=stub("equity_research"),
                                            market_pipeline=stub("market"), finance_pipeline=stub("finance"),
                                            tutor_pipeline=stub("tutor"), _general_reply=stub("general"),
                                            _smalltalk_reply=stub("smalltalk"), company_intelligence=lambda q: None,
                                            _with_news=lambda q, fn, *a, **kw: fn(q, *a, **kw)):
                            result = orchestrator.handle_query(case["query"], sid, mode="Live Avatar", correct=False)
                        effective = calls[-1][1] if calls else case["query"]
                        route_correct = result["domain"] == case["intent"]
                        terms_correct = all(t.lower() in effective.lower() for t in case["required_terms"])
                        diagnostic = result.get("intent_resolution", {})
                        rows.append({"id": case["id"], "expected": case["intent"], "actual": result["domain"],
                                     "route_correct": route_correct, "reference_correct": terms_correct,
                                     "intent_status": diagnostic.get("status", "fast_path"),
                                     "resolver_called": diagnostic.get("attempted", False),
                                     "effective_query": effective,
                                     "provider_prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage[usage_start:]) if len(usage) > usage_start else None,
                                     "provider_output_tokens": sum(u.get("output_tokens") or 0 for u in usage[usage_start:]) if len(usage) > usage_start else None,
                                     "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
                output["modes"][mode] = {
                    "cases": len(rows), "routing_accuracy": sum(r["route_correct"] for r in rows)/len(rows),
                    "route_and_reference_accuracy": sum(r["route_correct"] and r["reference_correct"] for r in rows)/len(rows),
                    "resolver_calls": sum(r["resolver_called"] for r in rows),
                    "provider_prompt_tokens": sum(r["provider_prompt_tokens"] or 0 for r in rows),
                    "provider_output_tokens": sum(r["provider_output_tokens"] or 0 for r in rows),
                    "mean_latency_ms": sum(r["latency_ms"] for r in rows)/len(rows), "results": rows}
        finally:
            logger.remove(sink)
            user_store.current_owner.reset(owner_token)
            session._SESSIONS.clear()
            session._SESSIONS.update(original_cache)
            engine.dispose()
    output["limitations"] = "Small labelled routing fixture, no answer-quality claims. Latency includes local persistence/context; cold import excluded. No private data or real tool execution."
    if not live:
        output["note"] = "Resolver accuracy requires --live; no model performance is inferred from mocked tests."
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run the same configured Groq model on synthetic cases")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(evaluate(args.live), indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)
