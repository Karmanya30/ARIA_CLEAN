# ARIA conversation memory implementation

Implementation and validation date: 2026-10-16. This report distinguishes working code from optional future extensions.

## Confirmed failures and request trace

Before this change, React posted a tab-scoped session UUID to `/api/chat`. The route set a device owner ContextVar and called `handle_query`. Module routing, financial computations, tutor RAG and report agents ran, then `core/session.py` appended a turn to a process-local dictionary. The model client sent only one system and one current user message. The history endpoint read that dictionary.

Confirmed causes:

1. `_SESSIONS` was the only transcript store. A server restart lost chat history; different workers had different histories.
2. Browser `sessionStorage` discarded the active conversation when the tab closed, even though a separate device owner already existed for research reports.
3. Normal-mode model calls had no prior messages. Voice-mode rewriting saw only three previous user questions and omitted assistant answers and research artifacts.
4. The news `system_context` bypass called the model without saving a turn.
5. Confident non-finance classifications explicitly returned a refusal. The tutor prompt alone could not fix this earlier return.
6. Research agent cache keys omitted the owner and selected model. Thread-pool tasks did not propagate owner ContextVars.
7. There was no context inspection, source-selection accounting, input archive for interrupted generation, or idempotency key.

## Implemented architecture

`React -> owner validation -> input archive / request claim -> context retrieval -> existing orchestrator and tools -> model -> final archive + task checkpoint -> response`

The existing SQLAlchemy database now contains four additional tables:

| Table | Purpose |
| --- | --- |
| `chat_conversations` | Owner binding, persisted task state, visible-history boundary |
| `chat_turns` | Original input, final structured response/artifacts, timestamp, ordered id, request id, completion status |
| `chat_request_leases` | Database-backed claims for duplicate requests and crashed-worker recovery |
| `chat_embeddings` | Local encoder vectors cached by model and content hash |

Each turn is an episode with original user text and the complete response dictionary, including whatever document references, calculations, source links and report artifacts the existing pipeline returns. Separate user/assistant transport messages are reconstructed from these source records; no summary replaces them. Existing financial profiles, goals and learned conversation style remain in their existing tables.

`shared/conversation_memory.py` provides owner-filtered BM25, exact substring matching and local Sentence-BERT retrieval, combined with reciprocal rank fusion. Recent conversation turns and related explicit corrections are also considered. Saved research versions are read directly from the existing owner-filtered reports table. Follow-up queries expand with recent user questions; recent assistant answers are supplied as evidence. Selected sources carry message/report identifiers and timestamps, and are rendered chronologically.

`core/session.py` keeps the original public module interface. Inputs are committed before generation; completion is committed after the final result and before returning it. Failed/interrupted work is not presented as a completed answer. A successful retry with the same `request_id` replays the stored result; using that id for different text returns HTTP 409. An active duplicate also returns 409. Database claims expire after 30 minutes by default; a late worker cannot overwrite a replacement worker's result. Different requests in the same conversation are serialized inside one worker.

Default narration calls receive retrieved evidence in the input, leaving stable system instructions before dynamic evidence. Constrained classification, extraction and evidence-ledger verification prompts keep their original inputs. General answers use the same evidence explicitly. Existing financial safety checks and numerical computation paths remain in place.

Both frontend versions and the shared frontend API send the owner on history and clear requests. The active conversation is retained in localStorage; existing tab ids are migrated when no saved active id exists. Tavus callbacks propagate the owner through their callback URL. Live streaming archives inputs and final responses, and completes persistence before sending `done`.

## Context limits and temporal handling

Selection uses a configured local model tokenizer when available. Otherwise it uses a conservative UTF-8 byte upper bound, explicitly labelled in diagnostics; this is not an exact provider token count. Whole evidence records are selected within the memory budget, prioritizing recent context and retrieval score. The provider-input check reserves response capacity. Oversized evidence can be excluded, and excluded ids are observable. No generated compaction summaries are introduced.

Historical prices and reports are labelled as historical evidence. The model is instructed to use later explicit corrections for present assumptions and retain earlier values for historical questions. Corrections are retrieved as source messages, not silently overwritten facts. These instructions and source ordering are tested; universal model adherence has not been established.

## Caching and observability

No general answer cache or retrieval-result cache was added. Retrieval reads the current database, so a new completed turn or cleared conversation changes the next result immediately. Local embeddings are cached for unchanged content. Research JSON caching retains its existing 600-second TTL, now keyed by owner, backend function, model, system and complete evidence prompt. Research worker threads copy ContextVars.

Groq/Gemini native implicit caching is used without adding an explicit cache service. Numeric provider usage, cached input tokens and elapsed time are logged when returned by the SDK. No provider cache-hit percentage or savings is claimed without real usage measurements. Stable prefixes only create an opportunity for a hit; they do not guarantee one. [Groq caching](https://console.groq.com/docs/prompt-caching), [Gemini caching](https://ai.google.dev/gemini-api/docs/caching).

`context_assembled` logs contain counts and semantic retrieval status, without query text. With `ARIA_CONTEXT_DEBUG=1`, `/api/chat/context?session_id=...&owner_id=...&query=...` returns selected/excluded record ids, token accounting and retrieval status, without transcript content or hidden reasoning. Leave this developer feature disabled in normal use.

## Dependency evaluation

No new dependency or paid memory service is required. SQLite/SQLAlchemy and ARIA's existing SentenceTransformer were sufficient for the confirmed failures.

| Candidate | Evaluation and decision |
| --- | --- |
| [Mem0](https://github.com/mem0ai/mem0) / [OSS documentation](https://docs.mem0.ai/open-source/overview) | Apache-2.0; Python library and self-hosted options. Useful retrieval/extraction design. Its defaults introduce model/embedding calls and additional vector storage. Reuse the ideas without adding another memory runtime. Vendor benchmark results are not ARIA results. |
| [LangGraph](https://github.com/langchain-ai/langgraph) / [persistence docs](https://docs.langchain.com/oss/python/langgraph/persistence) | MIT; thread checkpoints and cross-thread stores are useful concepts. ARIA already has a synchronous orchestrator and SQLite; adding a graph runtime is unnecessary for restoring turns and task state. Reconsider for resumable multi-step jobs. |
| [Graphiti](https://github.com/getzep/graphiti) / [documentation](https://help.getzep.com/graphiti/getting-started/overview) | Apache-2.0; temporal graph retrieval is relevant to evolving company relationships. Its documented Python/graph-database deployment adds infrastructure and extraction calls. Not selected for this patch; no temporal graph capability is claimed. |
| [Letta](https://github.com/letta-ai/letta) | Apache-2.0 reference for stateful agents. The referenced repository now points active work to `letta-code` and identifies its V1 server as historical. Adopting its runtime would require a much larger migration. Not installed. |

These were source/documentation evaluations, not installation or version-compatibility certification. No candidate's runtime was tested against ARIA's Python environment. The selected native implementation was tested locally.

The public [OpenAI compaction documentation](https://developers.openai.com/api/docs/guides/compaction), [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide), and [Anthropic context engineering article](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) informed source preservation, bounded working context and stable prompt prefixes. ARIA uses Groq/Gemini, so OpenAI compaction endpoints were not wired into it.

## Migration, configuration and rollback

Startup creates only missing tables using the existing `DB_URL`; existing profile/report/financial tables are not rewritten. No conversations, reports or files are deleted. SQLite foreign keys are enabled for archive integrity. Historical saved reports are searchable directly, without a destructive backfill. Messages already lost from the old in-memory process cannot be recovered by a database migration.

Back up the database using SQLite's backup API, or stop the application before making a filesystem copy so WAL state is handled correctly. Validate first against a backup database using a temporary `DB_URL`. Roll back application code while retaining the added tables; older code ignores them. Do not drop archive tables during rollback.

No required environment changes. Optional settings are documented in `.env.example`:

| Variable | Default / effect |
| --- | --- |
| `ARIA_MEMORY_SEMANTIC` | `1`; existing local SBERT, `0` for lexical-only retrieval |
| `ARIA_MEMORY_SEMANTIC_CANDIDATES` | `200`; maximum source records embedded/scored per query |
| `ARIA_MEMORY_TOKEN_BUDGET` | `6000`; evidence budget |
| `ARIA_MODEL_CONTEXT_TOKENS` | `32768`; set to the smallest configured provider/fallback window |
| `ARIA_RESPONSE_RESERVE_TOKENS` | `4096`; capacity reserved for output |
| `ARIA_TOKENIZER_PATH` | Optional installed model-matched tokenizer; no tokenizer download during a chat |
| `ARIA_CONTEXT_DEBUG` | `0`; diagnostics opt-in |
| `ARIA_REQUEST_LEASE_SECONDS` | `1800`; abandoned-request claim expiry |

The existing provider credentials and `SBERT_MODEL` settings remain applicable. `.env` and production secrets were not edited.

## Validation and known boundaries

Baseline: the original chat, small-talk and domain-guard tests passed, 14/14. The old guard test encoded the refusal behavior that this request intentionally changes. No pre-change retrieval accuracy benchmark was run, so no numerical improvement over a measured recall baseline is claimed.

New synthetic tests cover restart restoration, both conversation roles, cross-conversation recall, exact numbers/dates, corrections and original values, multiple sources, older exact details, semantic channel/fallback, tool/document references, context limits, fresh reads, owner isolation, idempotent retries, failures, interrupted work, non-destructive clearing, task checkpoints, provider context injection, classifier isolation, general questions, news-context persistence, diagnostics, database claims, research episodes/cache isolation and usage telemetry. Temporary databases keep these tests separate from private chats.

`scripts/evaluate_context_memory.py` measures retrieval separately from generated answers and writes no private data. The lexical fixture and the real SBERT fixture have separate JSON results in this directory. The latter includes paraphrases. These small fixtures are development checks, not production recall or hallucination benchmarks. Full regression output is recorded in `context-regression.txt`; final results are recorded below after completion.

Boundaries:

- User isolation follows the existing local application's device-owner capability model. ARIA still has no authenticated accounts. Do not equate an owner UUID with production identity/authentication.
- Request deduplication is database-backed; mutable module task state is designed primarily for the existing single-worker local deployment. Different simultaneous requests across workers can still race on task-state updates.
- Lexical retrieval scans an owner's visible archive. Semantic scoring is bounded, and saved report retrieval currently considers the latest 100 versions. Large-corpus indexing, background embedding jobs and ANN performance have not been load-tested.
- The transcript plus existing profile/style/report stores provide memory. There is no new LLM fact-extraction service, versioned generated-summary layer, cross-encoder, project graph, or autonomous generic browser/tool agent. Existing financial research/tool workflows are reused. Returned artifacts are archived; individual internal tool attempts not returned by those workflows do not acquire a new universal event journal.
- General questions are helped directly or use existing news/research capabilities where routed. Missing tool access must be stated. This does not add arbitrary computer execution or general web browsing to ARIA.
- Very large individual records can be omitted to respect the budget. Diagnostics expose this; retention does not imply that every record enters every prompt.
- Native provider cache telemetry is implemented, but live cache savings, live model answer quality and provider outages were not benchmarked with private conversations.
- Audio tokens remain process-local artifacts and may expire after restart; transcript text and structured research persist.

## Run and validate

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_conversation_memory.py -q
.\.venv\Scripts\python.exe -m scripts.evaluate_context_memory
.\.venv\Scripts\python.exe -m pytest -m 'not network and not slow' -q
Set-Location web
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m api.main
```

Restart the local backend and refresh the UI to use the changes. Verify a synthetic discussion, restart the backend, then ask a follow-up and inspect history. Start a new conversation under the same owner and revisit the topic. Repeat with a different owner to check isolation. No production deployment was performed.

## Recorded results

- Original targeted baseline: **14 passed**.
- Full available non-network/non-slow suite: **914 passed, 5 failed, 7 deselected** (354.73 seconds). All five failures are in the pre-existing instrument working changes: quote source text, unknown mutual-fund ids, two grounding-fallback expectations, and missing-data model calls. `verify_instrument_baseline.py` loads the tracked pre-memory backend in memory, without replacing working files; it reproduces the identical five failures (**20 passed, 5 failed, 2 deselected**). See `instrument-baseline.txt`.
- Final focused memory/chat/voice/routing/tone/finance/research-agent regression run: **234 passed** (65.65 seconds). Additional final follow-up checks: **60 passed** (46.33 seconds), including a pronoun follow-up that still invokes the live financial pipeline; recorded in `context-final-followup.txt`.
- Frontend `npm run build`: **passed**, including TypeScript and both Vite application versions. Minimal syntax/type/unused-binding repairs were needed in the existing StockDrawer, IntelligenceTab and NormalModeOrb working files; their feature edits were preserved.
- Lexical synthetic fixture, 8 questions/30 distractors: **Recall@5 1.00, MRR@5 1.00**.
- Real local SBERT fixture, 10 questions including two paraphrases/30 distractors: initial **Recall@5 0.90, MRR@5 0.85**. Separately scoring original user statements prevented generic acknowledgements/JSON formatting from diluting facts. Final **Recall@5 1.00, MRR@5 0.90**. Initial and final JSON files are retained. These are small development fixtures, not claims of perfect recall or production answer accuracy.
