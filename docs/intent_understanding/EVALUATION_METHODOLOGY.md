# Evaluation methodology

## What is compared
Five variants behind one flag, `ARIA_QUERY_ARCHITECTURE` (no separate copies of ARIA):

| Flag | Variant | What runs |
|---|---|---|
| `baseline` | A | today's routing, untouched |
| `semantic_router` | B | A, plus Semantic Router for questions the rules could not place (`ARIA_SR_MODE=override` is the ablation that lets it override the rules) |
| `langgraph` | C | A, plus a LangGraph workflow that splits multi-part questions with rules, runs the parts in parallel through the unchanged pipelines and verifies each part |
| `structured` | D | structured LLM understanding + Semantic Router + LangGraph, replacing the keyword/regex routing |
| `hybrid` | E | A's rules first; the structured layer (+ Semantic Router + LangGraph) only for questions the rules cannot place |

The prompt names three required implementations (A, B, C = hybrid) and five labelled versions (A-E). All five are implemented and measured; the hybrid of the prompt's section 4 is variant E, and D is its ablation without the existing rules.

## Benchmark (`evaluation/intent_understanding/benchmark_v1.jsonl`, 259 items)
* 167 items written on 2026-10-30 by an audit agent from the product description before any router change (142 single turns, 25 follow-up turns); 83 synthetic items (multi-intent, unsupported topics, calculations, entity-heavy, adversarial, follow-up chains); 9 questions that actually failed during live testing on 26-27 Oct. No private user data.
* Labels are the module a sensible user expects, not what ARIA did. Where several modules are reasonable, `acceptable` lists them. Multi-intent items also list the other modules that must be covered.
* Fixed split by hash: `dev` (129) for choosing thresholds and route examples; `test` (130) for the reported numbers. All turns of a follow-up scenario share a split. `check_leakage.py` verifies that no route example equals a benchmark query.
* Not covered (stated limits): real user logs (none exist for this single-user local install), answer-level ground truth for every item, and hallucination rate over the full set (measured on a smaller answer-level sample, see `answer_eval.py`).

## Protocol
1. Routing is measured offline: every module pipeline is a stub that records which branch ran (same technique as `tests/test_understand.py`). This separates routing from answer quality and removes the model's randomness from the routing comparison.
2. Structured-understanding calls (D, E) are made once per distinct input against the real model (`openai/gpt-oss-120b` on Groq, temperature 0) and cached by input hash with latency and token counts; later runs replay the cache, so D and E see identical model outputs and runs are repeatable. Cache misses count as model failures.
3. The legacy follow-up resolver (an LLM call) is switched off in all variants so they differ only in the new layers.
4. Latency is wall time per query after one warm-up query (model loading excluded; cold start reported separately). For D and E the recorded model latency of each call is reported next to the local time.
5. Thresholds are chosen on dev only (`calibrate.py`, coordinate search; objective = lenient accuracy minus half the unnecessary-clarification rate). Raw similarity and model-stated confidence are treated as ranking signals, not probabilities.
6. Metrics (`metrics.py`): strict and lenient accuracy with Wilson 95% intervals, macro precision/recall/F1 (strict, first choice), wrong-route rate (a module neither expected nor acceptable and no clarification), clarification precision/recall, follow-up accuracy, multi-intent coverage/precision, entity precision/recall/F1 (D, E only), latency, calls and tokens per query. Variants are compared paired on the same items with an exact McNemar test.
7. Costs use the recorded token counts; the free-tier model has no price, so cost per 1,000 queries is reported in tokens and, as an illustration only, at a stated list price.

## Reproduce
```
pip install -r requirements-intent.txt
python -X utf8 evaluation/intent_understanding/dataset.py
python -X utf8 evaluation/intent_understanding/run_benchmark.py --arch A --split all --llm off
python -X utf8 evaluation/intent_understanding/run_benchmark.py --arch D --split all --llm replay   # uses llm_cache.json
python -X utf8 evaluation/intent_understanding/report.py
```
