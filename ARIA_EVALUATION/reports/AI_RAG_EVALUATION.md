# ARIA AI / RAG evaluation (Phase A, offline measurements only)

Date: 2 Nov 2026. Scope: classification and retrieval plumbing, grounding, memory, injection handling. No LLM provider, no network, no server, no browser. Local SBERT (`sentence-transformers/all-MiniLM-L6-v2`, from the HF cache, `HF_HUB_OFFLINE=1`), 2 threads, below-normal priority. Memory runs used a scratch SQLite file in the session scratchpad; `data/user_profiles/*.db` was not touched. The finance-knowledge index already existed (`data/vector_store/finance_knowledge`, 34 passages), so nothing was built.

Scripts and raw results (all in `ARIA_EVALUATION/evaluation/`): `rag_kb_trust_eval.py` -> `rag_kb_trust_results.json`; `rag_memory_eval.py` -> `rag_memory_results.json`. Queries, synthetic histories and synthetic answers are written by the evaluator; sample sizes are stated next to every number. Samples are small (20-60 items): treat every rate as indicative, not as a launch SLA.

Labels: VERIFIED (command or file evidence given), SUSPECTED, RECOMMENDATION, UNTESTED, BLOCKED.

## 1. Summary

1. Query routing accuracy is not repeated here; see `docs/intent_understanding/COMPLETE_HELDOUT_BENCHMARK.md` (its own note, line 10: it measures routing only, no answer-level hallucination rate).
2. Retrieval over the two knowledge bases is fast (12-16 ms per search, VERIFIED) and the concept gate is conservative: 0 of 25 off-topic or out-of-KB queries accepted, but on paraphrased (not name-bearing) questions it accepts only 4 of 40, so most such questions fall to the generic model path (RAG-10).
3. The number-grounding guard in `modules/qa/trust.py` is strong on precise figures (10/10 invented 1-2 decimal figures caught, 0/15 grounded sentences wrongly flagged) and consistent with the existing `answer_eval.py` result (198/210, 94.3%). It has structural blind spots that the existing test does not exercise: integers 1-31, 1900-2100 and {12, 24, 52, 100, 365} are never checked in strict mode (0/13 caught), number words are never checked (0/3), and figures within about 0.5-1% of a real one pass (RAG-01, -03, -04).
4. Only some routes are checked at all. Tutor, general and untagged news/lookup replies pass through with `numbers_checked: false` even when they contain an invented figure (RAG-02).
5. Conversation memory works for owner isolation, clear boundaries and wording-overlap recall (100% at 40 and, when facts are recent, at 420 stored turns). Its semantic stage only sees the newest 200 records: at 420 turns an older fact is found by a paraphrase 1 time in 20, and turning the semantic stage on lowers recall for plain keyword queries from 100% to 60% (RAG-05).
6. Memory text is inserted between `<historical_evidence>` tags without escaping, and stored assistant output (including web-search text) is replayed (RAG-09).
7. NOT measurable offline: faithfulness of generated text, answer relevance, hallucination rate end to end, citation accuracy of model prose, spoken rewrite. See section 8.

## 2. AI pipeline map (code-level, VERIFIED by reading the files cited)

```
request -> modules/qa/pipeline.py answer()
  understand()          shared/understand.py normalize (spelling, Hinglish)         pipeline.py:30
  _precheck()           conversation owner check, instrument exists
  execute_turn()        core/session.py: builds memory context (conversation_memory.context_for) and persists the turn
  _run() -> core/orchestrator.handle_query -> _handle
      0 interpreted intent (core/intent/*, flag-gated; routing numbers in the heldout benchmark)
      1 general_task, focus (instrument / headline) -> modules/qa/focus.py grounded_answer
      2 follow-up with memory evidence -> _general_reply
      3 small talk, crisis (shared/human_state.py)
      4 finance_intent / route_query -> finance | tutor | market | equity_research | company intelligence | lookup (modules/qa/lookup.py) | web fallback (shared/websearch.py)
  trust.enforce() + trust.finalize()   pipeline.py:58-59   (checks only some routes, see 4.2)
  present()             spoken rewrite / audio (mode only)
```

Retrieval components:

| Component | Method | Store | Gate |
|---|---|---|---|
| Tutor concepts (`modules/tutor/retriever.py`) | SBERT MiniLM + FAISS flat IP, k=5 | `data/vector_store/concepts` (50 concepts) | `RETRIEVAL_THRESHOLD` 0.40, plus a second gate: below 0.6 every non-filler query word must appear in the concept name or aliases (`retriever.py:26`, `_SURE`) |
| Finance knowledge (`shared/finance_knowledge.py`) | same encoder, k=3 | `data/vector_store/finance_knowledge` (34 passages, 316-644 chars each, median 470) | `FINANCE_KNOWLEDGE_RETRIEVAL_THRESHOLD` 0.30; empty result is not an error. Used by tutor fallback (`modules/tutor/pipeline.py:89`), finance (`modules/finance/pipeline.py:1049`), market (`modules/market/pipeline.py:98`) |
| Conversation memory (`shared/conversation_memory.py:300`) | BM25 + exact phrase + optional SBERT (cosine >= 0.25 on the newest 200 records), reciprocal-rank fusion k=60; last 6 turns of the session always included; "correction" turns sharing the topic added | SQLite turns + saved reports + embeddings cache table | owner scoped, `cleared_through` boundary, 6000 "token" budget (UTF-8 byte upper bound unless `ARIA_TOKENIZER_PATH` is set) |
| Web search (`shared/websearch.py`, `modules/qa/lookup.py:web_answer`) | DDG/Bing snippets, titles only | none | facts passed as `UNTRUSTED_CONTEXT_JSON`, answer must pass `trust.ungrounded` (strict) with one retry, then a facts-only summary |
| Instrument / headline answers (`modules/qa/focus.py`) | facts JSON built in code | none | prompt rule 6 (untrusted), numbers checked strict with retry (`focus.py:86`) |
| Equity research agents | `<untrusted_source>` tags, `_untrusted()` strips `<` `>` (`agents.py:179`) | none | ledger-based figure insertion (outside this audit) |

Failure propagation (what happens when a stage is wrong):
* Wrong concept accepted by `best()` -> a confident TAXAL lesson on the wrong concept, no later check (section 3.1: 2 of 50 accepted wrongly in the earlier run).
* Concept rejected -> generic model call with up to 3 finance passages (threshold 0.30); no citation of which passage was used is returned to the user (`modules/tutor/pipeline.py` return dict has no sources field).
* Embedding failure in memory -> `except Exception: semantic_status = "unavailable"` with no log (`conversation_memory.py:351`); retrieval silently becomes lexical-only (section 5).
* Model down -> `trust.DEGRADED` text, never a raw error (`pipeline.py:55`, VERIFIED by reading; not exercised, needs the provider path).
* Invented number on an unchecked route -> reaches the user (RAG-02).

## 3. Retrieval quality of the knowledge bases

### 3.1 Tutor concept KB (50 concepts)

Earlier run in this folder (`ai_tutor_retrieval.py`, results file dated 2 Nov 03:07, not re-run): 50 name-bearing in-KB queries, top-1 0.96, hit@5 1.0, `best()` accepted 0.96 of which correct 0.92 (so 2 of 50 were confidently wrong: "how does interest on interest work over the years" -> simple_interest, "what is a CIBIL score" -> credit_score), 0/20 off-topic false accepts, p50 197 ms / p95 355 ms on the first run (cold caches).

New set B (this run, n = 40 in-KB, written as descriptions or typos instead of concept names; n = 25 out-of-KB, mostly finance topics that are not in the 50 concepts):

| Metric | Value |
|---|---|
| top-1 | 29/40 = 72.5% |
| hit@3 / hit@5 | 36/40 = 90% / 38/40 = 95% |
| `best()` accepted | 4/40 = 10% (all 4 correct) |
| out-of-KB accepted by `best()` | 0/25 |
| raw top-1 score >= 0.40 on out-of-KB (before the second gate) | 3/25 ("what is short selling" -> stcg 0.40, "what is TDS on fixed deposit interest" -> fd 0.56, "what is forex trading" -> etf 0.43); the second gate rejected all three |
| p50 / p95 search latency | 15.8 / 19.6 ms (warm) |

VERIFIED (`rag_kb_trust_results.json` -> `concept_kb_setB`). Reading: the gate trades recall for precision. Description-style questions without the concept's own words are not routed to the lesson (RAG-10). Of the 11 queries where top-1 was wrong, all 11 were rejected by `best()`, so the second gate does protect against wrong lessons on this set.

### 3.2 Finance-knowledge KB (34 passages)

n = 40 in-KB queries (one or two per passage), n = 25 out-of-KB.

| Metric | Value |
|---|---|
| top-1 / hit@3 | 40/40 / 40/40 |
| gold passage served after the 0.30 threshold | 40/40 |
| search latency p50 / p95 | 12.4 / 15.9 ms |
| queries given >= 1 passage at 0.30 among the 25 out-of-KB | 13/25 |
| same at 0.40 / 0.50 | 6/25 / 1/25, with in-KB still served 39/40 / 37/40 |

The 13 included finance-adjacent items ("what is the price of gold today" -> gold_etf_sgb 0.47, "explain dividends" -> fpo 0.32, "what is inflation" -> capital_gains_indexation 0.44, "what is a hedge fund" -> expense_ratio_exit_load 0.43). Pure off-topic items (code, jokes, capitals, cooking) received none. VERIFIED. Context precision here is therefore high for in-KB questions and mediocre for finance-adjacent questions that the KB does not cover (RAG-11). Coverage: 34 single-passage topics; a question outside them gets either nothing or a tangential passage. Whether the tangential passage degrades the final answer is UNTESTED (needs a model).

## 4. Grounding (modules/qa/trust.py)

Fixture: one synthetic evidence JSON (15 fields), 60 synthetic sentences labelled by me as containing an invented figure or not (45 invented, 15 grounded). Caution on small effects: some invented values coincide with digits that exist in the fixture (the date `2026-10-30` supplies a "30", the ROE 17.8 absorbs "18"); that is the same chance-match effect the larger `answer_eval.py` study was designed around.

Totals (`ungrounded()`):

| Mode | invented caught | grounded wrongly flagged |
|---|---|---|
| strict (used by instrument, headline, web answers: `focus.py:86`) | 21/45 | 0/15 |
| lenient (used by `enforce()` for market, equity research, finance tag) | 25/45 | 0/15 |

By category (strict caught/total; lenient in brackets):

| Category | Result |
|---|---|
| invented precise figures (1-2 decimals, large) | 10/10 (10/10) |
| derived figures (e.g. "25.4 percent below high", "4.1 times book") | 3/3 (3/3) |
| injection-style replies ("guaranteed 45%", "price is 99999", "buy 500 shares") | 3/3 (3/3) |
| invented small number with %/x/range marker | 0/5 (4/5) |
| invented bare small integer <= 31 ("P/E is 29", "D/E 2", "12 rupees") | 0/6 (1/6) |
| invented integer 1900-2100 as an amount ("price is 2,050", "target 2000") | 0/4 (0/4) |
| invented 12/24/52/100/365 ("returned 100 percent") | 0/3 (0/3) |
| perturbed real value: 0.3% / 0.5% / 0.5% | 0/3 (0/3) |
| perturbed real value: 1% | 1/1 (0/1) |
| perturbed real value: 3% / 3% / 5% / 10% | 4/4 (4/4) |
| number written as words ("twenty-one percent") | 0/3 (0/3) |
| grounded: verbatim 6, rounded 4, lakh/crore/million scaled 3, period labels 2 | 0 false flags of 15 |

VERIFIED: `rag_kb_trust_results.json` -> `trust_grounding`; the exemption is in code at `modules/qa/trust.py:54` (`n <= 31 or n in _OK_INTS or 1900 <= n <= 2100`, and `_claim_like` only restores the check for small numbers in lenient mode).

Coverage by route (`enforce()`, response containing "profit of 7,777.7 crore and P/E 61.3" with a data fixture that does not contain them), VERIFIED:

| Route | Checked | Reply edited |
|---|---|---|
| market / investment with `context` | yes | yes (sentence removed + notice) |
| equity_research with `normalized_data` | yes | yes |
| finance with `engine` | yes (tag only) | no (passed=false recorded, text unchanged) |
| tutor, general, finance without engine | no (`numbers_checked: false`) | no |
| market / equity_research without data, news and lookup replies without a `grounding` tag | no | no |

Redaction behaviour: a sentence with one untraceable figure is dropped whole, "Label:" prefixes are kept with "no figure that ARIA could verify." and a count notice is appended (`rag_kb_trust_results.json` -> `redaction_example`). Prior-art check: `evaluation/intent_understanding/answer_eval.py` reports 198/210 (94.3%) invented figures caught with 0/210 clean sentences flagged on 7 figure types (prices, revenue, profit, P/E, NAV, market cap, yield) with inventions scaled 1.3-5x. My run agrees on that class and adds the classes that file does not include.

## 5. Conversation memory (synthetic archive, scratch DB, SBERT local)

Method: 20 stated user facts (each a one-turn conversation), plus 40 or 400 distractor turns of ~750 chars. Each fact gets two queries: "lexical" (shares words with the fact) and "paraphrase" (shares none). recall@5 is the fraction of the 20 facts whose own turn is in the top 5 by fusion score. Three archives: 40 distractors (60 turns, facts oldest), 400 distractors with facts oldest (420 turns, facts beyond the newest-200 window), and 400 distractors with facts newest.

| Archive | Query | Semantic | recall@5 | MRR@5 | p50 / p95 ms |
|---|---|---|---|---|---|
| 60 turns | keyword | off | 1.00 | 1.00 | 6.5 / 8.1 |
| 60 turns | keyword | on | 1.00 | 1.00 | 114 / 130 |
| 60 turns | paraphrase | off | 0.15 | 0.15 | 7.7 / 9.5 |
| 60 turns | paraphrase | on | 0.70 | 0.56 | 92 / 119 (warm) |
| 420 turns, facts oldest | keyword | off | 1.00 | 1.00 | 38 / 55 |
| 420 turns, facts oldest | keyword | on | 0.60 | 0.60 | 347 / 390 |
| 420 turns, facts oldest | paraphrase | off | 0.20 | 0.16 | 39 / 56 |
| 420 turns, facts oldest | paraphrase | on | 0.05 | 0.05 | 343 / 391 |
| 420 turns, facts newest | keyword | on | 1.00 | 1.00 | 288 / 336 |
| 420 turns, facts newest | paraphrase | on | 0.60 | 0.49 | 291 / 308 |

Context actually injected (`build_context`, keyword queries, n = 20 per archive): gold turn included 20/20 at 60 turns, 12/20 at 420 turns with facts oldest, 20/20 with facts newest; mean 4.3-6.0 records included, so context precision (gold records / included records) is 0.14-0.18, mostly the always-included last-6-turns. Memory size 3.9-4.4k "tokens" (UTF-8 byte upper bound, not real tokens) of the 6000 budget; nothing was excluded.

Other checks (n as stated), VERIFIED in `rag_memory_results.json`:
* Owner isolation: another owner retrieved 0 records in all three archives. Clear boundary: cleared fact not retrievable in all three.
* Correction: for "what is my monthly salary" both the old (80000) and the correcting turn are selected (1 case). Only the prompt text (`MEMORY_RULES`) tells the model the later one wins; no code ordering or supersession.
* Follow-up reference expansion (`_FOLLOWUP`, `conversation_memory.py:271`): resolved 5/10 phrasings ("it", "this", "that", "continue", "compare it" yes; "its", "their", "the same fund", "isme", and a bare "what are the returns?" no). Mitigated: the last 6 turns of the session are always included regardless.
* The earlier results file (`ai_memory_retrieval_results.json`) recorded `semantic: "unavailable"` for every query. In this run the semantic path worked for all queries (`semantic_status: ok`) and no embedding exception was captured, so I could not reproduce the cause; SUSPECTED: encoder load failed under the memory pressure noted in `EXECUTION_STATUS.md`. The point stands: the failure is silent.

## 6. Prompt-injection handling in retrieved text (code level; no model, so effectiveness of prompts is UNTESTED)

VERIFIED present: `focus.py` rule 6 and `UNTRUSTED_CONTEXT_JSON` for headlines and web snippets; `agents._untrusted()` strips `<` `>` from third-party text inside `<untrusted_source>` (probe passed); `MEMORY_RULES` marks history as untrusted data; `shared/intent_resolver.py:42` and `core/intent/understanding.py:20` treat all input as untrusted; the trust layer blocks an injected figure on checked routes (probe: "Price target is 3,333" removed on the market route).

VERIFIED gaps:
* Memory serialisation uses `json.dumps` and so does not escape `<` `/`: a stored turn containing `</historical_evidence>` appears raw in the next prompt context (2 raw closing tags in the probe, user text and stored assistant text) and can end the wrapper early.
* Stored assistant responses are replayed in full as `assistant_and_artifacts` (`conversation_memory.py:403`), including the facts-only fallback that prints raw web titles and snippets (`lookup.py:web_answer`). Web text therefore persists across turns and conversations of the same owner. The probe confirmed stored assistant text is replayed (`stored_assistant_text_replayed: true`).
* Finance-knowledge passages come from a static curated index, not from user or web input; injection through that channel is not possible without writing to `data/vector_store`.
* On unchecked routes (RAG-02) an injected instruction that makes the model emit a figure is not stopped by code.

## 7. Defects

| ID | Title | Component | Sev | Status |
|---|---|---|---|---|
| RAG-01 | Strict number check ignores small integers, 1900-2100 and 12/24/52/100/365 | `modules/qa/trust.py:54` | P2 | VERIFIED |
| RAG-02 | Tutor, general and untagged routes are not grounding-checked | `modules/qa/trust.py:_evidence`, `enforce` | P2 | VERIFIED |
| RAG-03 | Numbers written as words are never checked | `trust.py` `_NUM` | P3 | VERIFIED |
| RAG-04 | Rounding tolerance lets ~0.5-1% figure errors through | `trust.py:50` | P3 | VERIFIED (by design; documents the limit) |
| RAG-05 | Memory semantic stage limited to newest 200 records; fusion then lowers keyword recall | `conversation_memory.py:348` | P2 | VERIFIED |
| RAG-06 | Memory retrieval adds 290-390 ms per turn at 420 turns | `conversation_memory.py:343-349` | P3 | VERIFIED |
| RAG-07 | Embedding failure is swallowed silently | `conversation_memory.py:351` | P3 | VERIFIED (code); trigger SUSPECTED |
| RAG-08 | Follow-up detector misses "its", "their", "same", Hinglish | `conversation_memory.py:271` | P3 | VERIFIED |
| RAG-09 | Memory context not escaped; stored web text replayed | `conversation_memory.py:396-423` | P2 | VERIFIED mechanism; exploit SUSPECTED |
| RAG-10 | Concept gate rejects description-style questions | `modules/tutor/retriever.py:23-39` | P3 | VERIFIED |
| RAG-11 | Finance-KB threshold 0.30 injects tangential passages; no provenance returned | `config/settings.py:91`, `modules/tutor/pipeline.py:89` | P3 | VERIFIED; effect on answers UNTESTED |

Details (evidence: reproduce with the two scripts above; severity rationale; fix; regression risk):

**RAG-01** Evidence: 0/13 invented small/year-range/special integers caught in strict mode (`rag_kb_trust_results.json`, categories `invented_small_bare`, `invented_year_range_int`, `invented_ok_int_set` and `invented_small_claim`); strict mode is what protects instrument, news-item and web-search answers (`focus.py:86`). Why it matters: "the price is 2,050 rupees" or "ROE is 19 percent" is exactly the kind of invented figure the guard exists for, and the claim-like repair exists only in lenient mode. Fix (RECOMMENDATION): apply the small-number exemption only when the number is not adjacent to a currency sign, rupee/crore/lakh/percent/x/times unit, or a metric word; limit the 1900-2100 exemption to year context ("in 2024", "FY", month names). Risk: more false flags on counts like "3 reasons" or "5 years"; measure with `answer_eval.py` clean sentences before and after.

**RAG-02** Evidence: `rag_kb_trust_results.json` -> `enforce_by_domain`: tutor, general, finance without engine, market and equity_research without data, news and lookup_instrument without a tag all returned `numbers_checked: false`, text unchanged. Why it matters: tutor fallback and general answers carry figures from model memory (rates, limits, prices) next to the finance passages; the `no_data` gate only covers named-entity data questions. Fix (RECOMMENDATION): for the tutor-fallback and general routes, check numbers against the injected passages plus the user's own query and tag rather than redact, or add a "unverified figures" notice; at minimum surface `numbers_checked: false` in the UI. Risk: the tutor KB legitimately contains rates that change (tax slabs); a hard redaction would remove correct statements. UNTESTED how often real model replies on these routes contain unsupported figures (needs a model).

**RAG-03** Evidence: 0/3 number-word sentences caught. Fix: low value; add a small number-word parser for common forms or accept as a known limit. Risk: low.

**RAG-04** Evidence: perturbations of 0.3% and 0.5% (3 items) pass in both modes; 1% passes in lenient. Tolerance is `0.6%` relative (strict) / `1.2%` (lenient) with absolute floors (`trust.py:50`). Fix: none needed unless exact quoting is required; documenting it is enough. Risk of tightening: false flags on rounded values.

**RAG-05** Evidence: `n400_facts_oldest` vs `n400_facts_newest` in `rag_memory_results.json`: keyword recall@5 with semantic on 0.60 vs 1.00; with semantic off 1.00 in both. Mechanism: records beyond the 200th newest never get a semantic rank, while newer distractors get fused scores from two lists and outrank a gold turn that only appears in the lexical list. Paraphrase recall 0.05 for old facts. Why it matters: after ~200 stored turns (a few weeks of use) the user's older stated facts become harder to recall exactly when the semantic stage is on. Fix (RECOMMENDATION): embed on write and rank all of the owner's records with a vector index, or restrict semantic to rerank the lexical top-N plus recent; weight lexical rank 1 more. Risk: moderate (changes what the model sees; re-run this script and the existing `tests/.../test_conversation_memory.py`). Sample: 20 facts per archive, one archive per condition.

**RAG-06** Evidence: warm p50 347 ms (semantic on) vs 38 ms (off) at 420 turns; embeddings are fetched from SQLite and parsed from JSON per record per query, then dotted in pure Python (`conversation_memory.py:285-349`). It is capped by the 200-candidate window so does not grow unbounded. Fix: cache vectors in memory or use numpy/FAISS. Risk: low. This is added to every chat turn, including the voice path.

**RAG-07** Fix: log a warning once with the exception class when the semantic stage fails; expose `semantic` in the response trace. Risk: none.

**RAG-08** Evidence: 5/10 phrasings. Impact low because recent turns are always included. Fix: add `its|their|them|same|isme|iska` and similar to `_FOLLOWUP`. Risk: low; slightly broadens query expansion.

**RAG-09** Evidence: probe `tag_breakout` (2 raw `</historical_evidence>`, assistant text replayed). The owner's own history is only exposed to that owner (isolation VERIFIED), so the main route is indirect: web snippets or news text that end up in a stored response. Fix: escape `<`/`>` in serialised records (as `agents._untrusted` does) and store a shortened or tagged form of web-derived text. Risk: low; memory text gets slightly longer.

**RAG-10** Evidence: set B accepted 4/40, top-1 72.5%, hit@5 95%; 0 wrong accepts; earlier set A 2 wrong accepts of 50. RECOMMENDATION: no change before a model-based comparison; the rejected queries still reach the generic model with finance passages. If tuned, use the top-1/top-2 margin as an additional accept signal and re-check the 25 out-of-KB items. Risk: wrong-concept lessons.

**RAG-11** Evidence: 13/25 vs 6/25 passage injection at 0.30 vs 0.40, in-KB retention 40/40 vs 39/40. RECOMMENDATION (low confidence, n = 25/40): raise to about 0.40 only after checking a handful of real model answers; add the passage ids to the response so the UI can show a source. Risk: lost grounding for oblique phrasing.

## 8. Not tested, and why

* BLOCKED (needs the generating model, quota is in use by the benchmark): faithfulness to retrieved passages, answer relevance, end-to-end hallucination rate, citation accuracy in model prose (`source_message` ids requested by `MEMORY_RULES`), the retry loop in `focus.grounded_answer`, the spoken rewrite, whether the prompt rules actually resist injection, context precision/recall as seen by the model.
* UNTESTED: query understanding (spelling, Hinglish, text-speak) quality; crisis detection (see `docs/intent_understanding`); web search (network); research-report agents' ledger and citation system; reranking (none exists: the pipeline has no reranker, only RRF in memory); the DKT/DQN tutor policy; token budget with a real tokenizer (`ARIA_TOKENIZER_PATH` not set); concurrency of memory retrieval; the 71 API operations (other agents).
* Routing: the earlier `ai_routing_offline.py` (hand-copied replica of the routing order, 57/67 correct, written before this task) was not re-run or validated here; use the heldout benchmark instead. Its failures were listed for interest only: tax-regime comparison to lookup, emergency-fund to general, "I feel like ending it all" to general (crisis, since fixed per the intent-understanding docs), Hinglish market question to general.
* Latency numbers are warm-cache measurements on a loaded laptop with 2 threads; cold start of the SBERT encoder was ~8.8 s in the earlier run and is not part of per-query figures.
