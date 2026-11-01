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

### Items where a variant changed A's outcome

**B +Semantic Router** (0):
- none

**C +LangGraph** (0):
- none

**D structured+SR+LG** (13):
- FIXED `I earn 80k and spend 50k, how much can I save` expected finance, A=general, D=finance
- BROKE `meri bachat kitni hai` expected finance, A=finance, D=clarify
- FIXED `define asset allocation` expected tutor, A=general, D=tutor
- FIXED `what does an equity research analyst do` expected tutor, A=finance, D=tutor
- FIXED `sip kya hai` expected tutor, A=finance, D=tutor
- FIXED `difference between stocks and bonds` expected tutor, A=equity_research, D=tutor
- FIXED `how do index funds work` expected tutor, A=clarify, D=tutor
- BROKE `SBI net profit` expected equity_research, A=equity_research, D=data_lookup
- BROKE `who is the CEO of Infosys` expected equity_research, A=general, D=company_intelligence
- BROKE `revenue of Kaynes Technology` expected data_lookup, A=data_lookup, D=equity_research
- BROKE `recommend a good movie` expected general, A=general, D=smalltalk
- FIXED `what is the taxi fare to the airport` expected general, A=tutor, D=general
- FIXED `SIP` expected tutor, A=finance, D=tutor

**E hybrid** (5):
- FIXED `I earn 80k and spend 50k, how much can I save` expected finance, A=general, E=finance
- FIXED `define asset allocation` expected tutor, A=general, E=tutor
- FIXED `how do index funds work` expected tutor, A=clarify, E=tutor
- BROKE `revenue of Kaynes Technology` expected data_lookup, A=data_lookup, E=equity_research
- BROKE `recommend a good movie` expected general, A=general, E=smalltalk

