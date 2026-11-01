# Benchmark results

Everything below is computed by `evaluation/intent_understanding/report.py` from the stored per-query rows in `results/` (raw outputs are committed). Benchmark: 259 items, `benchmark_v1`, split into dev (129) and test (130). **Status: the test-split model calls for variants D and E are only partly recorded (75 of 130 test items), because the free-tier daily token budget of the provider was exhausted; D and E test numbers are therefore preliminary and are reported only on the items where every variant has its recorded model output.** Dev numbers for D and E are complete but are optimistic: the thresholds were chosen on dev. Variants A, B, C and the ablations without a model are complete on both splits.

## 1. What can be trusted, in one table

| Claim | Evidence | Strength |
|---|---|---|
| Baseline routes 81.5% of test and 83.7% of dev questions acceptably; 16-18% go to a wrong module | A rows, both splits, complete | solid (n=259) |
| Semantic Router alone does not help on this benchmark | B: 0 fixed / 2 broken on test (p=0.50), 0 / 0 on dev; "override" ablation 6 fixed / 10 broken | solid for this encoder and these route examples |
| LangGraph with rule-based splitting helps multi-part questions and does not hurt single ones | multi-intent coverage 0.50 -> 0.61 (test), 0.455 -> 0.727 (dev); test 2 fixed / 0 broken, dev 1 fixed / 1 broken | small n (multi-intent: 11 dev, 9 test) |
| Structured understanding (D) is better than the rules on dev | 91.5% vs 83.7%, wrong-route 5.4% vs 15.5%, p=0.041 | tuned on dev: optimistic |
| ... and on the part of test that is recorded | 90.7% vs 86.7% (n=75), 8 fixed / 5 broken, p=0.58 | preliminary, not significant |
| Hybrid E is a small, cheap improvement | dev +2.3 points (6 fixed / 3 broken, p=0.51), test subset +1.3 points (3 fixed / 2 broken, p=1.0) | not significant |

## 2. Dev split (n=129; thresholds for B, D, E chosen here)

### Routing and understanding (dev split, n=129)

| Variant | Lenient acc. [95% CI] | Strict acc. | Wrong-route rate | Macro F1 | Clarify P / R | Needless clarifications | Follow-up acc. | Multi-intent coverage / precision | Entity P / R / F1 |
|---|---|---|---|---|---|---|---|---|---|
| A baseline | 83.7% [76.4%, 89.1%] | 65.9% | 15.5% | 0.626 | 0.00 / 0.00 | 1 | 0.778 | 0.455 / 0.909 | n/a (no extractor) |
| B +Semantic Router | 83.7% [76.4%, 89.1%] | 67.4% | 15.5% | 0.634 | 0.00 / 0.00 | 1 | 0.778 | 0.455 / 0.909 | n/a (no extractor) |
| C +LangGraph | 83.7% [76.4%, 89.1%] | 65.9% | 15.5% | 0.626 | 0.00 / 0.00 | 1 | 0.778 | 0.727 / 0.955 | n/a (no extractor) |
| D structured+SR+LG | 91.5% [85.4%, 95.2%] | 81.4% | 5.4% | 0.785 | 0.56 / 1.00 | 4 | 0.889 | 0.727 / 0.773 | 0.50 / 0.55 / 0.52 |
| E hybrid | 86.0% [79.0%, 91.0%] | 74.4% | 11.6% | 0.729 | 0.57 / 0.80 | 3 | 0.889 | 0.727 / 0.955 | n/a (no extractor) |

### Cost and latency (dev split)

| Variant | Local routing p50 / p95 (ms) | Model calls per query | Tokens per query | Model time per query (ms, recorded) | Tokens per 1,000 queries | Errors / cache misses |
|---|---|---|---|---|---|---|
| A baseline | 18 / 24 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| B +Semantic Router | 20 / 37 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| C +LangGraph | 20 / 32 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| D structured+SR+LG | 37 / 89 | 0.88 | 1149 | 1098 | 1,148,643 | 0 / 1 |
| E hybrid | 23 / 42 | 0.16 | 201 | 208 | 200,705 | 0 / 0 |

Local routing time is the measured wall time of the routing step with all pipelines stubbed (model-load excluded); model time is the latency recorded when the real call was made, so end-to-end routing time = local + model time. Tokens are prompt + completion as reported by the provider.

### Lenient accuracy by category (dev split)

| Category (n) | A | B | C | D | E |
|---|---|---|---|---|---|
| adversarial (9) | 78% | 78% | 78% | 78% | 67% |
| ambiguous (3) | 100% | 100% | 100% | 100% | 100% |
| calculation (5) | 40% | 40% | 40% | 100% | 60% |
| care (2) | 100% | 100% | 100% | 100% | 100% |
| entity_heavy (4) | 100% | 100% | 75% | 100% | 75% |
| equity (9) | 89% | 89% | 89% | 100% | 89% |
| finance (12) | 92% | 92% | 92% | 100% | 92% |
| followup (16) | 88% | 88% | 88% | 94% | 94% |
| general (7) | 100% | 100% | 100% | 100% | 100% |
| hinglish (8) | 62% | 62% | 62% | 88% | 75% |
| intel (4) | 100% | 100% | 100% | 100% | 100% |
| lookup (2) | 100% | 100% | 100% | 100% | 100% |
| market (6) | 100% | 100% | 100% | 100% | 100% |
| multi_intent (11) | 64% | 64% | 73% | 73% | 73% |
| real_estate_alternatives (5) | 80% | 80% | 80% | 60% | 80% |
| real_failure (1) | 100% | 100% | 100% | 100% | 100% |
| smalltalk (3) | 100% | 100% | 100% | 100% | 100% |
| support (2) | 100% | 100% | 100% | 100% | 100% |
| terse (1) | 100% | 100% | 100% | 100% | 100% |
| tutor (10) | 70% | 70% | 70% | 100% | 80% |
| typo (4) | 100% | 100% | 100% | 100% | 100% |
| unsupported_technical (5) | 80% | 80% | 80% | 60% | 80% |

### Paired comparison with baseline A (dev split, exact McNemar on lenient correctness)

| Variant | Fixed vs A | Broken vs A | p-value |
|---|---|---|---|
| B +Semantic Router | 0 | 0 | 1.000 |
| C +LangGraph | 1 | 1 | 1.000 |
| D structured+SR+LG | 15 | 5 | 0.041 |
| E hybrid | 6 | 3 | 0.508 |

## 3. Test split, variants that need no model (n=130, complete)

### Routing and understanding (test split, n=130)

| Variant | Lenient acc. [95% CI] | Strict acc. | Wrong-route rate | Macro F1 | Clarify P / R | Needless clarifications | Follow-up acc. | Multi-intent coverage / precision | Entity P / R / F1 |
|---|---|---|---|---|---|---|---|---|---|
| A baseline | 81.5% [74.0%, 87.3%] | 71.5% | 17.7% | 0.704 | 0.50 / 0.17 | 1 | 0.714 | 0.500 / 1.000 | n/a (no extractor) |
| B +Semantic Router | 80.0% [72.3%, 86.0%] | 70.8% | 20.0% | 0.696 | 1.00 / 0.17 | 0 | 0.714 | 0.500 / 1.000 | n/a (no extractor) |
| C +LangGraph | 83.1% [75.7%, 88.6%] | 73.1% | 16.2% | 0.714 | 0.50 / 0.17 | 1 | 0.714 | 0.611 / 0.944 | n/a (no extractor) |
| B-ablation: router may override rules | 78.5% [70.6%, 84.7%] | 68.5% | 21.5% | 0.669 | 1.00 / 0.17 | 0 | 0.714 | 0.500 / 1.000 | n/a (no extractor) |
| E-ablation: no LLM | 81.5% [74.0%, 87.3%] | 72.3% | 18.5% | 0.706 | 1.00 / 0.17 | 0 | 0.714 | 0.611 / 0.944 | n/a (no extractor) |

### Cost and latency (test split)

| Variant | Local routing p50 / p95 (ms) | Model calls per query | Tokens per query | Model time per query (ms, recorded) | Tokens per 1,000 queries | Errors / cache misses |
|---|---|---|---|---|---|---|
| A baseline | 22 / 30 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| B +Semantic Router | 20 / 36 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| C +LangGraph | 18 / 26 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| B-ablation: router may override rules | 32 / 48 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| E-ablation: no LLM | 20 / 38 | 0.00 | 0 | 0 | 0 | 0 / 0 |

Local routing time is the measured wall time of the routing step with all pipelines stubbed (model-load excluded); model time is the latency recorded when the real call was made, so end-to-end routing time = local + model time. Tokens are prompt + completion as reported by the provider.

### Lenient accuracy by category (test split)

| Category (n) | A | B | C | B-ablation: | E-ablation: |
|---|---|---|---|---|---|
| adversarial (6) | 100% | 100% | 100% | 100% | 100% |
| ambiguous (7) | 100% | 100% | 100% | 100% | 100% |
| calculation (5) | 80% | 60% | 80% | 40% | 60% |
| care (1) | 100% | 100% | 100% | 100% | 100% |
| entity_heavy (6) | 67% | 67% | 67% | 83% | 67% |
| equity (7) | 100% | 100% | 100% | 71% | 100% |
| finance (11) | 91% | 91% | 91% | 82% | 91% |
| followup (22) | 82% | 82% | 82% | 77% | 82% |
| general (7) | 86% | 86% | 86% | 86% | 86% |
| hinglish (2) | 50% | 50% | 50% | 50% | 50% |
| intel (1) | 100% | 100% | 100% | 100% | 100% |
| lookup (3) | 100% | 100% | 100% | 100% | 100% |
| market (6) | 83% | 83% | 83% | 67% | 83% |
| multi_intent (9) | 44% | 44% | 67% | 78% | 67% |
| real_estate_alternatives (3) | 67% | 33% | 67% | 33% | 33% |
| real_failure (8) | 75% | 75% | 75% | 75% | 75% |
| smalltalk (3) | 100% | 100% | 100% | 100% | 100% |
| terse (3) | 67% | 67% | 67% | 67% | 67% |
| tutor (9) | 56% | 56% | 56% | 67% | 56% |
| typo (8) | 100% | 100% | 100% | 88% | 100% |
| unsupported_technical (3) | 100% | 100% | 100% | 100% | 100% |

### Paired comparison with baseline A (test split, exact McNemar on lenient correctness)

| Variant | Fixed vs A | Broken vs A | p-value |
|---|---|---|---|
| B +Semantic Router | 0 | 2 | 0.500 |
| C +LangGraph | 2 | 0 | 0.500 |
| B-ablation: router may override rules | 6 | 10 | 0.454 |
| E-ablation: no LLM | 2 | 2 | 1.000 |

`E-ablation: no LLM` is E with the structured layer switched off (rules + router + graph); it differs from A only through the router and the graph.

## 4. Test split, all five variants, on the items with recorded model output (preliminary)

_Restricted to the 75 items for which every variant has its recorded model output (preliminary: the remaining test items are waiting for the provider's daily token budget)._

### Routing and understanding (test split, n=75)

| Variant | Lenient acc. [95% CI] | Strict acc. | Wrong-route rate | Macro F1 | Clarify P / R | Needless clarifications | Follow-up acc. | Multi-intent coverage / precision | Entity P / R / F1 |
|---|---|---|---|---|---|---|---|---|---|
| A baseline | 86.7% [77.2%, 92.6%] | 80.0% | 12.0% | 0.808 | 0.50 / 0.25 | 1 | 0.857 | n/a | n/a (no extractor) |
| B +Semantic Router | 86.7% [77.2%, 92.6%] | 80.0% | 13.3% | 0.809 | 1.00 / 0.25 | 0 | 0.857 | n/a | n/a (no extractor) |
| C +LangGraph | 86.7% [77.2%, 92.6%] | 80.0% | 12.0% | 0.808 | 0.50 / 0.25 | 1 | 0.857 | n/a | n/a (no extractor) |
| D structured+SR+LG | 90.7% [82.0%, 95.4%] | 85.3% | 8.0% | 0.801 | 0.67 / 0.50 | 1 | 0.857 | n/a | n/a (no extractor) |
| E hybrid | 88.0% [78.7%, 93.6%] | 82.7% | 12.0% | 0.827 | 1.00 / 0.50 | 0 | 0.857 | n/a | n/a (no extractor) |

### Cost and latency (test split)

| Variant | Local routing p50 / p95 (ms) | Model calls per query | Tokens per query | Model time per query (ms, recorded) | Tokens per 1,000 queries | Errors / cache misses |
|---|---|---|---|---|---|---|
| A baseline | 22 / 29 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| B +Semantic Router | 18 / 33 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| C +LangGraph | 18 / 25 | 0.00 | 0 | 0 | 0 | 0 / 0 |
| D structured+SR+LG | 38 / 59 | 0.80 | 1011 | 896 | 1,010,627 | 0 / 0 |
| E hybrid | 18 / 34 | 0.16 | 200 | 170 | 200,307 | 0 / 0 |

Local routing time is the measured wall time of the routing step with all pipelines stubbed (model-load excluded); model time is the latency recorded when the real call was made, so end-to-end routing time = local + model time. Tokens are prompt + completion as reported by the provider.

### Lenient accuracy by category (test split)

| Category (n) | A | B | C | D | E |
|---|---|---|---|---|---|
| ambiguous (4) | 100% | 100% | 100% | 100% | 100% |
| care (1) | 100% | 100% | 100% | 100% | 100% |
| equity (7) | 100% | 100% | 100% | 71% | 100% |
| finance (11) | 91% | 91% | 91% | 100% | 100% |
| followup (10) | 90% | 90% | 90% | 90% | 90% |
| general (7) | 86% | 86% | 86% | 86% | 71% |
| hinglish (2) | 50% | 50% | 50% | 50% | 50% |
| intel (1) | 100% | 100% | 100% | 100% | 100% |
| lookup (3) | 100% | 100% | 100% | 67% | 67% |
| market (6) | 83% | 83% | 83% | 83% | 83% |
| smalltalk (3) | 100% | 100% | 100% | 100% | 100% |
| terse (3) | 67% | 67% | 67% | 100% | 67% |
| tutor (9) | 56% | 56% | 56% | 100% | 78% |
| typo (8) | 100% | 100% | 100% | 100% | 100% |

### Paired comparison with baseline A (test split, exact McNemar on lenient correctness)

| Variant | Fixed vs A | Broken vs A | p-value |
|---|---|---|---|
| B +Semantic Router | 0 | 0 | 1.000 |
| C +LangGraph | 0 | 0 | 1.000 |
| D structured+SR+LG | 8 | 5 | 0.581 |
| E hybrid | 3 | 2 | 1.000 |

The 75 items are the earlier part of the dataset order (mostly single-turn questions from the audit set), so multi-part, adversarial and follow-up categories are under-represented here; this subset is easier for every variant than the whole test split (A scores 86.7% on it, 81.5% on the whole split).

## 5. Answer-level check: can the grounding stage catch an invented figure? (component test, no model)

| Figure type | n pairs | Invented figure caught | Clean sentence wrongly flagged |
|---|---|---|---|
| price | 30 | 29/30 (97%) | 0/30 |
| revenue | 30 | 27/30 (90%) | 0/30 |
| profit | 30 | 30/30 (100%) | 0/30 |
| pe | 30 | 28/30 (93%) | 0/30 |
| nav | 30 | 30/30 (100%) | 0/30 |
| mcap | 30 | 29/30 (97%) | 0/30 |
| yield | 30 | 25/30 (83%) | 0/30 |
| **all** | 210 | **198/210 (94.3%)** | **0/210** |

redaction demo -> Infosys revenue was ₹178,650 Cr. Net profit was ₹26,750 Cr. |  | Note: 1 statement(s) with figures that are not in the data ARIA fetched were left out. | removed: [340000.0, 250000.0]

Deterministic (seed 7), 210 pairs of the same sentence with the true figure and with a fabricated one, against evidence tables that also hold about 21 other figures. The misses are fabricated values that land within the rounding tolerance of another real figure in a dense table. This tests **numeric** fabrication only. It says nothing about invented names, dates or unsupported qualitative claims.

## 6. Not measured (and why)

* **End-to-end hallucination rate per variant** (a model writes the answer and a judge or a person checks every claim): not run. It needs several hundred model-written answers per variant plus claim-level labels; the provider's free daily budget does not allow it, and an LLM judge alone would not be acceptable evidence under the methodology. The numeric-grounding component test above and the routing results are the available evidence.
* **Cost in money:** the provider used is free-tier, so only tokens are reported (D about 1.0k tokens per query, E about 0.2k). Price per 1,000 queries = tokens per query x price per token of whichever provider is used in production.
* **Memory/CPU:** local routing adds 1 to 3 ms (router) per query; the router loads ARIA's existing sentence model, so no extra model memory beyond the index of 93 short examples. Not separately profiled.
* **Context-resolution accuracy as its own number:** reported as follow-up accuracy (turns 2+ of 12 scenarios; 21 dev turns, 14 test turns).
* **The legacy follow-up resolver (an LLM call) was switched off in all variants** so that they differ only in the new layers; its contribution is therefore not measured here.
