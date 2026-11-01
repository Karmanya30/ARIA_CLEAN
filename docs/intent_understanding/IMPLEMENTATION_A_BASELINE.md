# Implementation A: the existing ARIA baseline

Nothing is changed: `ARIA_QUERY_ARCHITECTURE=baseline` (the default) makes `core.orchestrator._architecture_route` return immediately, so the code path is the pre-existing chain (crisis check, dialogue acts, rules, `shared/intent_classifier`, `core/router`, `modules/qa/lookup`, legacy resolver for follow-ups). The only edits to shared code made during this task are bug fixes found by the benchmark and applied to every variant equally:

* `shared/human_state.CRISIS`: widened, because the benchmark showed "I am thinking of hurting myself" reaching the general model (measured on 12 phrasings of self-harm intent: 4 caught before, 12 caught after; 12 money idioms such as "my SIP will kill my savings" produced one false alarm, "what is self harm insurance cover", which gets the gentle care reply; regression test in `tests/test_human_state.py`).

The measured baseline (accuracy, per-category results, latency) is in BENCHMARK_RESULTS.md. The baseline makes no LLM call for routing (the legacy resolver is disabled in all variants for the comparison), so its token cost per query is 0.
