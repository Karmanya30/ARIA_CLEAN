# ARIA current architecture audit: how a question is understood, routed and answered

Scope: Phase 1 of task `P0 — ARIA Intent Understanding & Hallucination Reduction`. Everything here was read from the code on branch `feature/intent-understanding` (from `main` 984ffbb) or measured by `evaluation/intent_understanding/`. Items not verified are marked SUSPECTED.

## 1. Where a question enters and what touches it

```
POST /api/chat  (api/routes/chat.py)  or  WebSocket /api/live/ws  or  Explore ask  (api/routes/*)
   -> modules/qa/pipeline.answer()                       the ONE pipeline: understand, context, answer, ground, trust, persist, present
        understand  shared/understand.normalize()         spelling, text-speak, Hinglish   (rewrites the query)
        _precheck   ownership of the conversation, instrument exists
        execute_turn(core/session.py)                     replay by request_id, memory evidence (shared/conversation_memory)
        core/orchestrator.handle_query -> _handle_query
             1. crisis check  human_state.is_crisis        fixed care reply, no model
             2. dialogue acts (ok / thanks / no)           shared/dialogue
             3. general_task (write/translate/code)        -> general model
             4. focus (instrument / news item open)        modules/qa/focus
             5. legacy LLM resolver  shared/intent_resolver  ONLY for follow-ups / ambiguous tasks (structured, validated, advisory)
             6. tone layer (human_state) -> _handle
        _handle: smalltalk -> pending-finance answer -> finance_intent regex -> route_query keyword bucket
                 -> quiz -> catalogue/web data lookup -> intelligence / equity / broad-market regex -> finance / tutor / market / general
   -> trust.enforce / finalize                            removes sentences whose numbers are not in the fetched evidence
```

## 2. The existing intent classifier

`shared/intent_classifier.py` is a keyword classifier with word-boundary matching and four outputs: `finance`, `market`, `tutor`, `general`. Order matters: strong tutor phrases first, then FINANCE_KEYWORDS (about 35), MARKET_KEYWORDS (stock names and "market cap"), TUTOR_KEYWORDS (including "company", "business", "ceo"), else `general`. It is not a model: no probability, no margin, no notion of "I am not sure".

The finer routing is a stack of regexes and name lists in `core/router.py` (`is_equity_research_query`, `is_broad_market_query`, `is_intelligence_query`, `is_quiz_request`), `modules/finance/pipeline.finance_intent`, and `shared/company_resolver` (45 hard-coded companies; any other name is handled by `modules/qa/lookup`, added 27 Oct).

The only learned/LLM component is `shared/intent_resolver`: a bounded structured call (strict Pydantic schema, validation that the model did not invent numbers, drop negations, or change a named company, confidence threshold 0.8) that runs only when a follow-up or a vague task needs a standalone rewrite. It returns one of six intents, a rewritten query and a clarification question.

## 3. Component inventory (what can be reused, what must change)

| Component | Role | Reuse? |
|---|---|---|
| `shared/understand` | spelling / Hinglish normalisation | reuse; known risk: it can rewrite a name (Kaynes -> Keynes), so routing must also see the original text (already done: `shown` vs `query`) |
| `core/router`, `shared/intent_classifier` | deterministic placement | keep as the baseline and as a fast path |
| `shared/intent_resolver` | LLM follow-up resolver | keep (baseline); superseded by structured understanding in variant D |
| `shared/conversation_memory` | evidence from earlier turns | reuse unchanged |
| `modules/*/pipeline.py` | the capabilities (finance, tutor, market, equity research, intelligence, lookup) | reuse unchanged; the new layers only choose and order them |
| `modules/qa/trust` | strips figures not in the fetched evidence | reuse; extended per part for multi-part answers |
| `core/orchestrator._handle` | the decision chain | one new hook (`_architecture_route`), default off |

## 4. Where wrong or invented answers can enter (verified unless marked)

1. **Silent fall-through to the general model.** Anything the rules do not place ends in `_general_reply`, which has no evidence check. Verified: before the 27 Oct fixes, an unlisted company ("PE of Suzlon") reached it and the model answered from memory; the gold price of 55,800 rupees came from here.
2. **Single-route model.** One question maps to one module. Multi-part questions are answered by the first matching module only (benchmark: coverage 45% of expected modules on dev multi-intent items).
3. **Keyword collisions.** "SBI Bluechip fund" matched the bank; "what is inflation" matched a market keyword; "show me the NAV" triggered the supportive-tone reply. All fixed individually on 26-27 Oct; the class of error remains because routing is substring and regex based.
4. **Crisis detection was a narrow phrase list.** Verified by this benchmark: "I am thinking of hurting myself" reached the general model. Fixed in this task (see FAILURE_ANALYSIS.md); 12 of 12 test phrasings are now caught.
5. **Context.** Follow-ups depend on the legacy resolver (an LLM call) or on the single-company pronoun shortcut; "should I sell it" after a company question is routed as finance on the model's confidence, with no check that the user holds the stock (SUSPECTED; measured in the benchmark).
6. **Evidence handling after routing.** Verified earlier in this project: fundamentals and research-report replies lost every figure because the number check had no evidence (fixed 26-27 Oct). Per-part evidence is needed for any merged answer (implemented in `core/intent/graph.py`).
7. **Retrieval.** Tutor concept retrieval uses SBERT with a threshold and a lexical guard; web-search snippets are treated as untrusted text and checked against the answer's numbers.

## 5. Integration risks

* The orchestrator file is also edited by other work; the hook is one function and one `if` so the merge surface is small.
* The new layers add latency: Semantic Router about 10 ms warm (local embedding), structured understanding about 1.3 to 1.6 s (one Groq call, about 1.2k tokens). Decision: structured understanding runs only when the deterministic layer cannot place the question (variant E).
* Free-tier LLM limits make large benchmarks expensive; LLM outputs are cached by input hash for repeatable reruns.
* Semantic Router and LangGraph pull about 40 extra packages (cohere, openai, mistral SDKs). They are optional: `requirements-intent.txt`, default flag `baseline`, and every new component degrades to "no opinion".

## 6. Strategy

Keep every existing capability. Add a decision layer in front of the existing chain, behind `ARIA_QUERY_ARCHITECTURE`: B adds Semantic Router for questions the rules cannot place; C adds a LangGraph workflow that splits multi-part questions, runs the parts in parallel through the unchanged pipelines and verifies each part on its own evidence; D replaces the rule-based routing with structured understanding + Semantic Router + LangGraph; E keeps the rules first and invokes the structured layer only when they cannot place the question. All five are measured on the same benchmark (EVALUATION_METHODOLOGY.md, BENCHMARK_RESULTS.md).
