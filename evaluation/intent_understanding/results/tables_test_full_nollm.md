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

### Items where a variant changed A's outcome

**B +Semantic Router** (2):
- BROKE `how does leverage affect real estate returns` expected tutor, A=general, B=equity_research
- BROKE `convert 5 lakh rupees to crore` expected general, A=general, B=market

**C +LangGraph** (2):
- FIXED `Quiz me on SIP and then tell me my savings rate` expected tutor, A=finance, C=tutor
- FIXED `What is beta, and what is the beta of Tata Motors` expected tutor, A=equity_research, C=tutor

**B-ablation: router may override rules** (16):
- BROKE `should I stop my SIP, markets are down` expected finance, A=finance, B_override=tutor
- BROKE `tax regeme old vs new for me` expected finance, A=finance, B_override=tutor
- FIXED `difference between stocks and bonds` expected tutor, A=equity_research, B_override=tutor
- BROKE `what is happening in the stock market` expected market, A=market, B_override=tutor
- BROKE `valuation of Infosys` expected equity_research, A=equity_research, B_override=company_intelligence
- BROKE `pe ratio of L&T and HDFC Bank` expected equity_research, A=equity_research, B_override=data_lookup
- BROKE `Reliance` expected equity_research, A=equity_research, B_override=tutor
- FIXED `SIP` expected tutor, A=finance, B_override=tutor
- BROKE `what is compound interest` expected tutor, A=tutor, B_override=market
- FIXED `Tell me what inflation is and how the RBI repo rate affects markets` expected tutor, A=market, B_override=tutor
- FIXED `Quiz me on SIP and then tell me my savings rate` expected tutor, A=finance, B_override=tutor
- FIXED `Teach me about mutual funds and plan my monthly budget` expected tutor, A=finance, B_override=tutor
- BROKE `how does leverage affect real estate returns` expected tutor, A=general, B_override=equity_research
- BROKE `XIRR of my investments` expected finance, A=finance, B_override=tutor
- BROKE `convert 5 lakh rupees to crore` expected general, A=general, B_override=market
- FIXED `ITC and Hindustan Unilever dividend yield` expected equity_research, A=finance, B_override=data_lookup

**E-ablation: no LLM** (4):
- FIXED `Quiz me on SIP and then tell me my savings rate` expected tutor, A=finance, E_nollm=tutor
- FIXED `What is beta, and what is the beta of Tata Motors` expected tutor, A=equity_research, E_nollm=tutor
- BROKE `how does leverage affect real estate returns` expected tutor, A=general, E_nollm=equity_research
- BROKE `convert 5 lakh rupees to crore` expected general, A=general, E_nollm=market

