# Task completion report: P0 Intent Understanding & Hallucination Reduction

Status: **substantially complete, with three items blocked by the language-model provider's free daily quota (below).** Branch `feature/intent-understanding`.

## Acceptance criteria (section 12 of the brief)

| Criterion | Status | Evidence |
|---|---|---|
| Baseline documented and evaluated | Done | IMPLEMENTATION_A_BASELINE.md, BENCHMARK_RESULTS.md (A on 259 items) |
| Semantic Router integrated and tested | Done | `core/intent/semantic.py` (library engine, ARIA's own encoder), tests, B results; measured result: no benefit |
| LangGraph orchestration implemented and evaluated in the hybrid | Done, sequential | `core/intent/graph.py`; parallel mode exists but is unsafe in production (deadlock found and documented) |
| All approaches independently executable | Done | one flag, `ARIA_QUERY_ARCHITECTURE`; A-E plus ablation switches |
| Same benchmark for all | Done for the benchmark; **D and E test split incomplete (75 of 130 recorded)** | BENCHMARK_RESULTS.md sections 2-4 |
| Intent and routing metrics | Done | accuracy with Wilson CIs, macro P/R/F1, wrong-route rate, clarification P/R, follow-up accuracy, multi-intent coverage; entity F1 for D only (E handles entity questions with rules) |
| Final answer quality and hallucination metrics | **Partly:** numeric-grounding component test done (94.3% of invented figures caught, 0 of 210 clean sentences flagged); **end-to-end hallucination rate per variant not measured** | answer_eval.py; blocked by quota and by the rule against judging with an LLM alone |
| Latency and cost measured | Done for routing (local ms, model ms, tokens per query); money cost not computed (free tier) | BENCHMARK_RESULTS.md |
| Failures analysed | Done | FAILURE_ANALYSIS.md |
| Regression tests pass | Done for the changed areas (see below) | |
| Deployment compatibility verified | Partly: Windows + project venv; Docker image not built | DEPLOYMENT_GUIDE.md |
| Final recommendation documented | Done, provisional | FINAL_ARCHITECTURE_RECOMMENDATION.md |

## What was built
`core/intent/` (taxonomy, semantic router, schema, structured understanding, decision layer, LangGraph workflow); a one-function hook in `core/orchestrator.py` (default off); `evaluation/intent_understanding/` (259-item benchmark with dev/test split and leakage check, runner with cached model calls, calibration, metrics, report generator, answer-level component test); `tests/intent/` (19 offline tests); `requirements-intent.txt`; the documents in this folder.

## Findings that matter beyond the comparison
1. **Safety bug fixed:** the crisis detector missed 8 of 12 realistic phrasings of self-harm intent; widened with a regression test.
2. **Deadlock found and fixed:** parallel parts inside a turn wait on the per-conversation lock held by the waiting turn.
3. **Rule-labeller flaw found by a live check and fixed:** concept questions were not separated from personal calculations, so a two-part question was not split.
4. Provider constraints found: strict structured output rejects free-form maps; the free tier has a per-minute and a per-day token limit that bounds how large a benchmark of model calls can be run per day.

## Blocked, and how to finish
* **D and E on the remaining 55 test items** (about 95k tokens): wait for the provider's daily budget to refill, then `python -X utf8 evaluation/intent_understanding/run_benchmark.py --arch D --split test --llm record` (resumes from `llm_cache.json`; set `ARIA_BENCH_PACE_S=15`), the same for `--arch E`, then `report.py`. No code change is needed. Until then D/E test results are preliminary.
* **End-to-end answer evaluation** (hallucination rate per variant): needs several hundred model-written answers per variant and claim-level labels from a person; not run.
* **Live check of a multi-part answer through the real pipelines:** both language-model providers were out of quota when attempted (Groq daily tokens, Gemini 20 requests per day). The graph was verified with stubs and with a handler that reads the session while the turn holds its lock; a real end-to-end multi-part answer has not been seen.

## Recommended next steps
Implement shadow mode for E and D (log the decision, do not act); run it on real traffic; complete the held-out comparison; decide on enabling E (then D). Collect real labelled queries (with consent) before any fine-tuning discussion; grow the benchmark with a second human rater.

## Tests run
`tests/intent` (19), `tests/test_human_state.py`, `tests/test_router.py`, `tests/test_understand.py`, `tests/qa` and the earlier orchestrator tests passed at each change. Full suite (`pytest tests`, default baseline architecture): 1274 passed, 0 failed. The working tree also contained unrelated uncommitted edits from another session (Tavus/ngrok removal and similar), which are not part of this work and are not in the commits.
