# Selective Groq intent resolver

Implemented on 2026-10-16. The resolver uses the existing configured Groq `MODEL_NAME`; it does not require a second model, provider, NLP framework or database.

## Request flow

1. Existing safety checks, exact conversation acts and explicit general tasks retain priority.
2. Clear calculations, educational questions, research requests, numeric answers and pending financial confirmations keep their existing paths.
3. Ambiguous inherited tasks, choices, references and unclear task requests can make one separate Groq interpretation call.
4. A validated interpretation selects an existing workflow, asks a focused clarification, or falls back to the existing router if interpretation fails.
5. The original user message is retained for display and archiving. Evidence is retrieved again for an accepted standalone interpretation.

The transport sends a stable interpretation system prompt and a bounded JSON input containing the current query and up to four recent user/assistant exchanges. It does not inject tone instructions, live news, arbitrary profile records or other users' history. Truncated excerpts are marked. No hidden reasoning is requested or returned.

## Implementation

| File | Change |
| --- | --- |
| `shared/intent_resolver.py` | Selective invocation policy; strict local Pydantic contract; confidence handling; provenance and input validation; request-local interpretation state |
| `ai/llm/groq_client.py` | Dedicated structured call using the same Groq `MODEL_NAME`, temperature 0, a 1,024-token completion cap, SDK timeout and no SDK retries |
| `core/orchestrator.py` | Dispatches accepted interpretations to existing finance, market, research, tutor or general workflows; persists diagnostic metadata |
| `modules/finance/pipeline.py` | Optional `intent_query` determines intent, while facts are extracted only from the original user message; missing-input follow-ups retain the interpreted task |
| `tests/test_intent_resolver.py` | Contract, selection, failures, transport, numeric/company protection, dispatch and finance-state tests |
| `tests/intent_evaluation_cases.json` | Fixed expected routes and reference terms for 12 synthetic evaluation cases |
| `scripts/evaluate_intent_resolver.py` | Reproducible routing ablation, optionally using live Groq; financial/research tools and answer generation are stubbed |

The structured response contains `intent`, `standalone_query`, `referenced_topic`, `required_capability`, `missing_inputs`, `confidence`, `clarification_question` and `source_turn_ids`. Unknown fields, unsupported capabilities and mismatched intent/capability pairs are rejected.

Groq strict JSON-schema mode is used for the documented supported model identifiers, including ARIA's `openai/gpt-oss-120b`. Other configured model names use JSON-object mode with the schema included in the prompt and the same local validation. The resolver does not silently substitute a different model. Provider failure falls back to ARIA's existing routing; the answer generator retains its existing provider fallback behavior. [Groq structured outputs](https://console.groq.com/docs/structured-outputs).

## Safety and correctness boundaries

- The resolver cannot select arbitrary tools or authorize transactions, trades, external actions or profile updates.
- Pending confirmations and numeric replies are handled by the existing deterministic workflow.
- Referenced source ids must belong to the recent turns actually supplied for this request.
- New numeric values, dropped current numbers or negations, changed numeric units and replacement of an explicitly named company are rejected. These guards are conservative and may reject equivalent rewrites.
- Finance receives the original user text for fact extraction, not the generated standalone query. Interpreted intent can initiate a calculation; the existing engine loads the profile and asks for missing inputs.
- Low confidence or an unresolved choice produces a clarification. A schema/provider failure uses the previous routing behavior rather than a scope refusal.
- Category labels never mean a question is forbidden. Existing safety, privacy and financial-risk rules still apply.
- Confidence is self-reported by the model, not a calibrated probability. Schema compliance and lexical provenance checks do not prove semantic correctness.
- Interpretation state is scoped to the request and reset on exit; there is no shared private response cache.

## Configuration

No `.env` edit is required. Defaults are enabled, using the existing Groq model and credentials. Optional settings are listed in `.env.example`:

| Variable | Default |
| --- | --- |
| `ARIA_INTENT_RESOLVER` | `1`; set to `0` to use the existing router alone |
| `ARIA_INTENT_TIMEOUT_SECONDS` | `8`; SDK request timeout, clamped to 0.1–15 seconds; no SDK retries |
| `ARIA_INTENT_MIN_CONFIDENCE` | `0.8`; values below this ask for clarification |

There is one interpretation call at most per selected request, with no interpretation retry loop or alternate-model chain. Unsupported structured output, truncation, invalid JSON, rate limits or timeouts leave the existing routing available. The SDK timeout is not a guarantee of an exact end-to-end wall-clock deadline.

Responses that attempted interpretation include `intent_resolution` metadata: outcome, chosen capability, confidence, source ids, elapsed time, and a privacy-safe validation error code where applicable. Structured logs contain numeric/status diagnostics rather than the query, response, credentials or hidden reasoning. Groq's existing provider usage logger records prompt/completion/cache token counts when returned.

## Measured evaluation

The fixture's expected routes and required reference terms were authored independently of the target resolver's responses, by the coding assistant. They have **not** been reviewed by a human evaluator. This is a small development fixture, not a representative held-out benchmark or a claim about human-level understanding. Expected labels and term checks were not changed to improve the measured scores.

Both a first and a final live run are preserved. The configured model was `openai/gpt-oss-120b`; each run selected eight of the twelve requests for interpretation. The remaining requests, including `ok`, a clear lesson, a clear calculation and a creative request, made no resolver call.

| Metric | Existing router | Resolver enabled, final run |
| --- | ---: | ---: |
| Correct route | 7/12 (58.3%) | 10/12 (83.3%) |
| Correct route plus required reference terms | 4/12 (33.3%) | 9/12 (75.0%) |
| Resolver calls | 0 | 8 |
| Mean fixture processing time | 32.9 ms | 796.8 ms |
| Provider-reported resolver prompt tokens | 0 | 4,910 |
| Provider-reported resolver completion tokens | 0 | 1,481 |

These latency and token figures cover the synthetic routing harness. They exclude answer generation and real financial/research tools, which are stubbed in both modes. Cold imports are excluded. They are not full chat-response latency or total application cost. The first run also measured 10/12 correct routes and 9/12 route/reference matches; its timing differed, as expected for a small live test.

Observed limitations: one inherited financial lesson was routed to general conversation, and a personal-payment follow-up did not reach the expected finance route. A second-company query reached the correct company workflow but missed the fixture's exact `valuation` term. Literal term checks can penalize a useful paraphrase; conversely, matching terms does not guarantee a correct answer. Guard failures preserve the old routing rather than executing a questionable interpretation.

For project assessment, obtain evaluator-reviewed labels and test a larger unseen set, including Hinglish, corrections, multiple referents, unsupported requests and provider outages. Report routing accuracy separately from financial answer quality. Do not use the answering model as the only judge of its own correctness.

## Validation and running

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_intent_resolver.py -q
# Baseline only, no live model call:
.\.venv\Scripts\python.exe -m scripts.evaluate_intent_resolver
# Live interpretation on synthetic data only; uses the existing Groq quota:
.\.venv\Scripts\python.exe -m scripts.evaluate_intent_resolver --live --output reports/intent-resolver-evaluation.json
```

- Final functional regression: **446 passed** (`intent-resolver-final-regression.txt`), covering resolver, dialogue, finance, tutor, history, APIs and voice.
- Dedicated safety and finance-follow-up checks: **64 passed** (`intent-resolver-safety-tests.txt`).
- Final transport/diagnostic checks and the isolated tone timing test: **44 passed** (`intent-resolver-final-checks.txt`).
- An earlier broad run had 289 passes and an existing tone-engine wall-clock timing assertion failure at about 0.53 seconds versus a 0.50-second limit. The tone-scoring implementation was unchanged; its isolated rerun is recorded with the final checks.

Unit/regression calls use mocks; the evaluation script makes real Groq calls only with `--live`. New unit tests and the live harness use temporary databases and synthetic conversations. No private user history was used for evaluation, no production data was migrated or deleted, and `.env` and provider secrets were unchanged.

Restart the local backend to load the implementation. No frontend or database migration is required. No production deployment was performed.
