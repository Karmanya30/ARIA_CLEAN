# Adaptive hybrid (H) versus structured understanding (D)

Setting: `ARIA_QUERY_ARCHITECTURE=H` (adaptive) or `D` (structured understanding on every question). The default is H (adaptive) since 2026-11-03; set `ARIA_QUERY_ARCHITECTURE=baseline` to go back to the earlier routing. Without a working model key, H falls back to the baseline routing.

## What H does
Rules and the semantic router answer on their own when they are confident. The model is asked only when the question looks ambiguous, multi-part or follow-up (`needs_model` in `core/intent/arch.py`); a guard then checks the model's route against the rules before it is used.

## Results
Same 130-question test split as the other variants (H was tuned after its first failures on this split, so its number is optimistic):

| Variant | Correct on the test split |
|---|---|
| A baseline | 86.9% |
| E | 86.9% (88.5% with the model off) |
| D | 91.5% |
| H | 95.4% (tuned on these questions) |

A second set of 105 new questions, written after H and D were fixed and not used to tune either (`benchmark_fresh.jsonl`, `dataset_fresh.py`):

| Variant | Correct | Questions that called the model |
|---|---|---|
| A baseline | 74.3% | 0 |
| E | 88.6% | 26 |
| H | 91.4% | 43 |
| D | 94.3% | 94 |

D's run is complete (no missing recorded calls). The per-question results are in `evaluation/intent_understanding/results/` (`*_fresh_all.json`, `Dfresh3_all.json`).

## Reading it
- On questions neither variant was tuned on, D is ahead of H by 3 of 105 questions. That is a small gap, within what a different set of questions could change.
- H asks the model on 43 of 105 questions, D on 94 of 105. Each model call adds a delay and token use, so H is the cheaper and faster one.
- Both are well above the baseline (74.3% on the same questions).
- Not measured: end-to-end hallucination rate per variant with a real model, and real-user latency. The model calls were replayed from a recorded cache.

## Decision
H is the default: it is 17 points above the baseline on the fresh questions and calls the model on fewer than half of them. D is available for accuracy-first use.
