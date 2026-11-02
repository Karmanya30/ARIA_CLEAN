# ARIA performance and reliability audit (Phase A)

Date: 2026-11-02. Branch: chore/single-ui-vitara-markets (working tree with uncommitted edits from other sessions; not ours). Application code was read-only.
Scripts and raw results: `ARIA_EVALUATION/evaluation/performance/` (scripts at top level, JSON in `results/`). Every number below is from those files.

## Summary

Labels: VERIFIED (measured, with the file and sample size), SUSPECTED (code reading or a single observation), RECOMMENDATION, UNTESTED, BLOCKED.

Headline findings

1. VERIFIED, P1. The instrument catalogue search is pure-Python difflib over ~39k items. `GET /api/instruments/search` takes a median 1.14 s (p95 1.61 s, n=60) for most queries of 4+ characters, and the same function makes every `data_lookup` chat query 1.6 to 2.2 s median (up to ~10 s) in the routing benchmark. It is the dominant routing latency in every variant A to H.
2. VERIFIED, P1. When Hugging Face is unreachable and `HF_HUB_OFFLINE` is not set, the first SBERT load takes 218.0 s instead of 0.35 s. In the routing run this showed up as one chat turn taking 218 s (the first turn that reads conversation memory). The repo sets the offline flag nowhere (only `scripts/run_system_audit.py` does).
3. VERIFIED, P2. Conversation-memory retrieval (run inside every chat turn, before the model call) is linear in the owner's whole archive: 28 ms at 100 turns, 1.5 s at 5,000, 3.4 s at 10,000 (BM25 only). The semantic part adds ~0.16 to 0.2 s of lookups when warm, and 28.6 s on the first query for a 1,000-turn archive with real SBERT (n=1).
4. VERIFIED, P2. Per-turn persistence cost grows linearly with conversation length: 12 ms at 5 prior turns, 232 ms at 595, 312 ms at 995 (no model involved). `GET /api/chat/history` is unpaged: 14.2 MB and 186 ms p50 at 3,000 turns.
5. VERIFIED, P2. `/api/voice/transcribe` is `async def` but runs blocking Whisper: `/api/health` stalled 1.7 s during a 1.75 s transcription.
6. VERIFIED, P2. Provider outage amplification: one general question while all providers fail makes 8 provider attempts (16 plus 8 s of sleeps for a 503/429-type failure), and resends about 7.6k estimated prompt tokens. A hung (not failing) provider was not testable, but SDK defaults are 60 s read timeout and 2 retries per Groq call.
7. VERIFIED, P2. Open WebSockets consume admission slots: with the limiter at N slots, N open sockets make every `/api` call return 503 (default N = 16).
8. VERIFIED, P3. A degraded "I couldn't reach my language model" answer is stored as a complete turn and replayed for the same `request_id` after providers recover (8 ms, zero model calls). A crashed worker blocks a retry of the same `request_id` for the lease time (default 1800 s).
9. VERIFIED, cost. Every written (non-avatar) reply starts a background audio job: one extra model call (prompt 940 to 1,480 chars) plus one TTS synthesis, whether or not the user ever plays it.

What held up (VERIFIED): SQLite under 1 to 8 concurrent writers had zero errors (WAL, 30 s busy timeout); lease races are safe (8 workers, same request id: 1 lease, 7 RequestBusy; expired lease takeover rejects the stale worker); the deterministic engines cost microseconds; concept and finance-knowledge retrieval is ~18 ms p50; the rate limiter engages exactly at request 121; with providers down the finance engine paths still return numeric answers and the others degrade to a fixed message with HTTP 200.

Machine for all numbers: Windows 11, 22 logical CPUs, 16 GB RAM, CPU-only torch, project venv (Python 3.13). Free RAM 0.7 to 3.9 GB during the work. Every process ran at BelowNormal with OMP/MKL threads = 2. The routing sweep (about 75 min) ran in the background while the other benchmarks ran, and another session's uvicorn on port 8000 was alive, so all latencies are "busy laptop" numbers, not quiet-machine numbers. Where the p99 matters I say how many samples it rests on.

Safety record: scratch SQLite files only (`DB_URL` asserted to contain `aria_perf_`, and scripts assert the engine URL does not contain `user_profiles`); `ARIA_AUTH_MODE=private`; `GROQ_API_KEY` and `GEMINI_API_KEY` set to empty; outbound sockets blocked in-process (loopback allowed), `curl_cffi` made unimportable and `yfinance.Ticker/download/Search` replaced by raisers; `HF_HUB_OFFLINE=1` except in the one test that measures its absence; the only server was one process on 127.0.0.1:8016 (stopped; port verified closed); no browser, no microphone (the voice test uses audio synthesised by Piper). Scratch directories were deleted. No provider call was made. The user's real DB `data/user_profiles/aria.db` was never opened by these scripts.

## 1. Routing latency per architecture variant (A baseline to H adaptive)

Method (VERIFIED): `evaluation/intent_understanding/run_benchmark.py` unchanged, driven by `run_routing.py`, `--split all` (259 queries = dev 129 + test 130), `--llm replay` (cached structured-understanding answers, so no provider call; 0 cache misses, 0 errors in all runs), 2 repetitions per variant in fresh processes (n = 518 per variant). Module pipelines are stubs, so this is routing plus the local steps in `handle_query` plus conversation-memory persistence, not answer generation. Model time for D, E and H is the latency recorded when the cache was filled, not re-measured. Summary: `results/routing_summary.json`.

| Variant | p50 ms | p95 ms | p99 ms | max ms | mean ms | queries > 1 s | model calls / query | tokens / query | recorded model ms / query | lenient acc. (259) |
|---|---|---|---|---|---|---|---|---|---|---|
| A baseline | 26.6 | 2569 | 7346 | 9411 | 391 | 51 of 516 | 0 | 0 | 0 | 88.4% |
| B +Semantic Router | 26.2 | 2032 | 4751 | 8662 | 277 | 42 of 518 | 0 | 0 | 0 | 88.8% |
| C +LangGraph | 20.8 | 2396 | 5752 | 7012 | 321 | 50 of 516 | 0 | 0 | 0 | 89.6% |
| D structured+SR+LG | 41.8 | 1625 | 3350 | 4868 | 217 | 39 of 518 | 0.89 | 1154 | 1112 | 91.1% |
| E hybrid | 28.5 | 1760 | 5155 | 10660 | 280 | 34 of 518 | 0.13 | 164 | 151 | 88.4% |
| H adaptive | 40.2 | 1799 | 5712 | 9942 | 291 | 42 of 518 | 0.29 | 383 | 378 | 95.0% |

Rows for A and C exclude 2 samples each (4 in total) of 218 s (see section 7, REL-01), which are the offline SBERT load, not routing. Full figures with them: A p95 3091 / p99 7660 / max 218,876; C p95 2630 / p99 6121 / max 219,043. Reproducibility between the two repetitions of one variant: p50 within 5 to 10 ms, p95 within 0.1 to 0.7 s (`rep_p50_p95` in the summary); the differences between variants in p95 and p99 are therefore partly noise. p99 rests on 518 samples, i.e. the 5 slowest.

Readings.
* VERIFIED: the local cost of choosing a route is small in every variant (p50 21 to 42 ms). D and H add ~15 ms p50 for the extra layers.
* VERIFIED: the tails are not the architecture. The slow queries are all `data_lookup` (p50 by route 1.6 to 2.2 s in every variant, against 20 to 45 ms for the other routes) plus a few Hinglish/terse ones ("kitna kharch hua food pe" 6 to 10 s, "how does leverage affect real estate returns" 6 to 8 s). The cause of the data_lookup cost is PERF-01 (profile below). The link for the two non-lookup queries is SUSPECTED (same function, not call-traced).
* VERIFIED against the published table: `tables_final_test.md` reports local p50/p95 of 20/1731 (A) to 41/1367 (D) on the 130-query test split; this run gives 21 to 42 ms p50 and 1.4 to 2.6 s p95 on 259 queries, i.e. the same shape on a busier machine.
* Model cost of the structured layer (from the replay cache, VERIFIED arithmetic, not re-measured): D = 0.89 calls and 1,154 tokens per query (about 1.15 M tokens per 1,000 queries); E = 164 tokens; H = 383 tokens. Adding D or H to a path that already makes 1 to 3 answer calls roughly adds 1 to 3 extra seconds of model time per query at the recorded 1.1 s per call (D). That is end-to-end routing time = local + model time, as the published table states.

## 2. Deterministic engines and text steps (VERIFIED, `results/engines_retrieval.json`)

In-process timings, hot (the same inputs repeated), 200 to 2,000 samples each. p50 / p99 in milliseconds:

| Function | p50 | p99 |
|---|---|---|
| sip_future_value, sip_required, emi | 0.0005 | 0.001 |
| tax_new / tax_old | 0.0044 / 0.0052 | 0.007 |
| engine.snapshot / goals / retirement | 0.0065 / 0.0104 / 0.0045 | 0.018 |
| engine.health_score | 0.033 | 0.052 |
| afford_purchase / afford_sip / tax_compare | 0.0046 / 0.0071 / 0.0094 | 0.017 |
| engine.what_if (runs health_score twice) | 0.12 | 0.23 |
| shared.understand.normalize (10 queries per sample) | 0.51 | 1.15 |
| modules.finance.pipeline.finance_intent (10 queries per sample) | 0.20 | 0.46 |

Reading: the engines are not a performance concern. `normalize` ran on 10 repeated strings, so it may be benefiting from a cache; first-call cost was not isolated (UNTESTED). `trust.enforce` was not measured meaningfully (my input short-circuited), so no number is claimed (UNTESTED).

## 3. Retrieval (VERIFIED, `results/engines_retrieval.json`, `results/memory_scaling*.json`)

* Concept KB (`modules/tutor/retriever.retrieve`, SBERT+FAISS, 50 concepts): n=280 (70 distinct queries x 4) p50 18.4 ms, p95 27.3, p99 31.7, max 34.1. `retriever.best` gate: n=140, p50 19.5, p95 23.7. Finance knowledge (`retrieve_passages`): n=140, p50 18.9, p95 23.4, p99 27.9. The older figure in `ai_tutor_retrieval_results.json` (p50 197 ms, p95 355) was taken on a different, busier moment; the current figure is ~10x lower. Split: one query encode is 16.1 ms p50 (n=100), reading FAISS + meta.json from disk each call is 0.57 ms p50 (n=300). `vector_store.search` re-reads both files on every call; harmless at 50 concepts (RECOMMENDATION: cache the index if the corpus grows).
* SBERT model load 0.35 s with `HF_HUB_OFFLINE=1` from the local cache (n=2 fresh processes: 0.36 and 0.34 s; 13.5 to 13.9 s wall including `import torch`).
* Conversation memory (`shared/conversation_memory.retrieve`, synthetic turns of ~4.6 KB, scratch DB): BM25 + exact phrase over every complete turn of the owner (all conversations) plus 100 saved reports. p50 by archive size (n=9 per size): 100: 27.6 ms, 500: 120, 1,000: 272, 2,500: 667, 5,000: 1,514, 10,000: 3,395 (p95 3,845). About 0.3 ms per record, linear. Semantic mode with a zero-cost stub encoder, warm cache: 100: 165 ms, 500: 409, 1,000: 541, 2,500: 964, 5,000: 2,034 (so ~160 ms plus ~0.3 ms/record of DB lookups: 200 candidates x 2 texts, one DB session each). With the real SBERT (1,000 records, scratch DB): first query 28.6 s max (n=1 cold; 403 embeddings computed at ~70 ms each), then 647 ms p50 warm (n=9). The 28.6 s is a one-off per archive/model, but it is paid inside a user's chat turn.
* Whether that cost buys anything: with the `tutor` path the prompt did not grow with history (2,012 to 1,989 estimated tokens at 0, 5, 20, 60 prior turns), because `augment()` only applies to calls that use the default system prompt (`generate_response(prompt)` with no `system_prompt`). The retrieval work is still done on every turn (`execute_turn` -> `context_for`). VERIFIED for the tutor path only; the `general` path prompt did grow (1,261 -> 1,468 -> 1,937 estimated tokens over three consecutive requests of the same owner as the archive grew), bounded by `ARIA_MEMORY_TOKEN_BUDGET=6000` (counted in UTF-8 bytes, so at most ~1,500 real tokens per default-system-prompt call).

## 4. History, list, search and export with large synthetic data (VERIFIED, `results/history_scale.json`)

Data: 151 conversations, 9,000 turns for one owner (plus 400 for other owners), 4.6 KB average response JSON, 45 MB SQLite file, FastAPI TestClient (in process; no network stack). p50 / p95 / p99 in ms, n as shown:

| Endpoint | n | p50 | p95 | p99 | payload |
|---|---|---|---|---|---|
| GET /api/conversations (page 1, 30 items) | 40 | 75 | 104 | 114 | 5 KB |
| same, offset 150 | 20 | 74 | 86 | 94 | 0.2 KB |
| search q=nifty (title hit) | 15 | 322 | 356 | 358 | 6.5 KB |
| search q="question 7" (body, rare) | 15 | 298 | 317 | 318 | 6.5 KB |
| search miss | 15 | 238 | 252 | 253 | 0 |
| GET messages (page of 50, 3,000-turn conversation) | 40 | 13.5 | 15.9 | 73 | 236 KB |
| export JSON, 3,000 turns | 5 | 232 | 338 | 350 | 14.7 MB |
| GET /api/chat/history (unpaged), 3,000 turns | 8 | 186 | 245 | 266 | 14.2 MB |
| same, 50 turns | 20 | 12 | 14 | 14 | 193 KB |

Reading. Listing and paging scale well (the list is aggregated in SQL, pages are `limit+1`). Search is a case-insensitive `ILIKE` over `chat_turns.query` and `response_json` with no index, a full scan: ~240 to 320 ms at 9,400 turns, expected to grow linearly (UNTESTED beyond this size). The unpaged `GET /api/chat/history` and the export return the entire conversation (14 MB at 3,000 turns). The web client uses the paged endpoint for the sidebar; whether any screen still calls `/api/chat/history` was not checked (UNTESTED).

In-process effect on the next section: `execute_turn` loads the history three times per turn (see PERF-03).

## 5. SQLite concurrency, request leases and retries (VERIFIED, `results/sqlite_concurrency.json`)

Scratch DB, synthetic turns, the real `begin -> snapshot -> complete -> checkpoint` write path, no in-process session lock (as with several uvicorn workers). Journal mode `wal`, pool QueuePool size 5, 30 s busy timeout (`shared/user_store.py:219`).

| Writers (separate conversations) | cycles | errors | throughput cycles/s | p50 ms | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| 1 | 40 | 0 | 75.8 | 10.9 | 24 | 32 | 32 |
| 2 | 80 | 0 | 69.0 | 17.4 | 67 | 85 | 97 |
| 4 | 160 | 0 | 71.3 | 15.8 | 135 | 351 | 1,327 |
| 8 | 320 | 0 | 80.5 | 13.9 | 297 | 1,387 | 2,103 |
| 8, all on ONE conversation | 200 | 0 | 70.0 | 16.4 | 453 | 1,106 | 1,598 |

Reading: writes serialise at roughly 70 to 80 persistence cycles per second regardless of thread count, with no `database is locked` errors; waiting shows up as tail latency (p99 above 1 s at 8 writers). That is plenty for this product (a chat turn also spends seconds in the model). Reads under write load: 6 reader threads alone p50 33 ms (pairs of list+messages), with 2 writers p50 62 ms, p99 95 ms, 0 errors (8 s each).

Lease and retry behaviour (all VERIFIED by `bench_sqlite_concurrency.py`):
* 8 workers race `begin()` on the same `request_id`: 1 gets the lease, 7 get `RequestBusy` (409 over HTTP). No double execution.
* Worker crashed after `begin()` (no `fail()`): a retry of the same `request_id` gets `RequestBusy` until the lease expires; default `ARIA_REQUEST_LEASE_SECONDS` = 1800 s (REL-04).
* Lease expiry: a second worker takes over after expiry (new token); the stale first worker's `complete()` is rejected with `RequestBusy`; the final turn is complete once. Correct.
* `fail()` after an exception marks the turn `interrupted` and a retry gets a new lease. Correct.
* A reply that starts with "Error:" is stored `failed` and a retry regenerates. But the user-visible degraded text does not start with "error", so it is stored `complete` and replayed (REL-03).

HTTP-level (VERIFIED, `results/http_load.json`, one uvicorn process on 8016, real app, stub model sleeping 300 ms per call, scratch DB, localhost client; the routing sweep was running at the same time):
* Boot to `/api/health` 200: 2.8 s with warm-up off.
* `/api/health`: 1/4/8 client threads: 109 / 338 / 435 req/s, p50 4.4 / 8.1 / 15.2 ms, p99 29 / 36 / 40 ms, 0 errors (about 650 to 2,600 requests per level).
* `/api/conversations` list: 73 / 231 / 214 req/s (1/4/8 threads), p50 6.9 / 13.7 / 36 ms, p99 32 / 39 / 66 ms, 0 errors.
* `POST /api/chat` (tutor question, 2 stub model calls of 300 ms, distinct sessions, 24 requests per level, all 200): 1 thread 774 ms p50 (1.29 req/s); 2: 827 ms (2.36 req/s); 4: 1,047 ms (3.58 req/s); 8: 2,250 ms p50, 2,860 p95 (3.26 req/s). So one worker saturates at about 3.3 to 3.6 chat requests per second beyond 4 concurrent requests; the server-side time that is not the model is about 170 ms at 1 thread and CPU-bound beyond that. n=24 per level: no p99 is claimed.
* Rate limiter: 130 POSTs to `/api/chat/clear` from one client: requests 1 to 120 returned 200, 121 to 130 returned 429 (first 429 at request 121), matching the configured 120 per minute.

## 6. Startup, memory and token cost

Startup and memory (VERIFIED, `results/startup_*.json`, fresh processes, HF offline flag set, warm page cache):
* `import api.main` 1.1 s, 152 MB (n=3). The server answers `/api/health` 2.8 s after launch with `ARIA_WARMUP=0`.
* Warm-up steps that need no network (one process): `import core.orchestrator` 10.2 s (to 503 MB), SBERT load 0.35 s, spelling model 1.3 s, FinBERT first score 1.4 s (RSS jumps 644 -> 1,089 MB), concept search 0.01 s. About 17.5 s wall and 1.09 GB working set at the end. Not measured: market live start, instrument/AMFI/coin warm, news warm and Piper warm (network or large downloads; UNTESTED). The first chat after boot (stub model, scratch DB, includes SBERT, retriever and first-time imports) took 10.4 s (n=1); the HTTP run's first tutor chat after seeding took 1.08 s.
* Peak working set of the in-process chat benchmark: 1,088 MB (`results/cost_failure.json`); with Whisper loaded 1,204 MB (`results/voice.json`). On the user's laptop, whose free RAM was 0.4 to 1.9 GB in earlier sessions, one API process with all models is a large share of what is free (RECOMMENDATION: lazy-load FinBERT and Whisper).
* Session cache: `core/session._SESSIONS` and `_LOCKS` never evict (code reading, 100 sessions x 10 turns gave 100 cached sessions). RSS growth was within noise (+15 MB at 50 sessions, -12 MB at 100) so no leak is demonstrated at that scale (SUSPECTED at much larger session counts; UNTESTED). Raw console capture: `results/session_memory_console.txt`.

Token cost per request path (computed from the prompts actually built, with a stub model; no provider call; tokens = characters / 4, an ESTIMATE; `results/cost_failure.json`, 3 runs per path, owner archive growing between runs). Calls include the background audio-script call (section 8):

| Path | query | model calls | est. input tokens (3 runs) | est. output tokens (canned reply) | server time ms (stub model, 3 runs) |
|---|---|---|---|---|---|
| smalltalk | hello | 2 | 516 / 516 / 516 | 290 | 184 / 107 / 87 |
| general | recommend a good movie | 2 to 3 | 1,261 / 1,468 / 1,937 | 290 | 109 / 92 / 103 |
| tutor concept | what is the sharpe ratio | 2 to 5 | 1,572 / 1,082 / 1,518 | 290 | 182 / 115 / 129 |
| finance calc | how much sip ... 1 crore in 20 years | 2 | 2,244 / 2,061 / 2,296 | 290 | 114 / 104 / 108 |
| finance profile | what is my savings rate | 3 | 2,650 / 2,741 / 2,740 | 434 | 118 / 111 / 111 |
| finance tax | old vs new tax regime for me | 2 | 1,568 / 2,104 / 1,853 | 290 | 128 / 110 / 110 |
| market | how is the nifty doing today | 2 | 2,346 / 2,464 / 2,504 | 290 | 169 / 138 / 137 |
| equity research | tell me about TCS fundamentals | 2 | 947 / 947 / 947 | 290 | 142 / 140 / 147 |

Caveats: the stub's canned reply is 580 characters, so output tokens are not a model estimate; the tutor path returned the degraded message with the canned reply (a stub-format effect, not analysed) so its numbers are not representative; market and equity-research data fetches failed instantly because the network was blocked, so those prompts lack real fetched data and real prompts will be larger (UNTESTED with real data). A data-lookup question ("market cap of Zomato") made 1 call and took 3.3 to 3.9 s of server time (PERF-01). Money cost: BLOCKED/UNTESTED. The repo contains no price table, the providers are on free tiers, and I did not assume prices. Multiply tokens by your provider's current rates. Routing add-on cost: section 1.

Hidden background cost (VERIFIED, `results/background_audio.json`, stub model and stub synthesiser, 12 requests over 6 path/query pairs): every one of them started exactly one extra model call (`audio_script`, prompt 996 to 1,483 chars for smalltalk/general/tutor and 942 for finance, i.e. roughly 235 to 370 estimated input tokens) and exactly one TTS synthesis, in the background, and returned an `audio_token`.

## 7. Provider-down behaviour

Method: the stub replaces `_BACKENDS`, `_call_groq`, `_call_gemini` of `ai/llm/groq_client.py`, so the real fallback chain and retry code run; sleeps are recorded, not performed (`bench_cost_failure.py`, one request per path). Chat via TestClient, all HTTP 200.

| Failure mode | Provider attempts per question | Recorded sleeping | What the user gets |
|---|---|---|---|
| auth/other error (no 429/503 text) | smalltalk 4, general 8, tutor 8, finance 8, finance-profile 12, market 8 | 0 s | smalltalk: friendly fixed greeting; general/tutor/market: "I couldn't reach my language model just now, so I won't guess." (`degraded: true`); finance paths: the deterministic engine answer ("Insight: Your monthly surplus is ..."), no degraded flag |
| 503/429 type | smalltalk 8, general/tutor/finance/market 16, finance-profile 24 | 4 s (smalltalk), 8 s, 12 s | same answers, after the sleeps (`time.sleep(2)` per pass, blocking the worker thread and the conversation's lock) |
| daily token quota ("tokens per day") | the first request tries (smalltalk 4); every later request 0 | 4 s on the first | backends are marked dead for 30 min, later requests answer in ~0.25 s with the same degraded text |

Server time with providers down was 0.24 to 0.32 s in every case apart from the recorded sleeps (the failures are instant in the stub). VERIFIED (arithmetic from the sleep log): with a real 429, the added wall time is 8 s per general question.

* A hung provider (neither failing nor answering) was NOT simulated: it needs a slow local fake server on a second port, which the task did not allow. From the installed SDK (VERIFIED by reading `groq._constants`, version 1.2.0): default timeout read=60 s, connect=5 s, `max_retries=2`; `_call_groq` does not override either, and the chain tries three Groq entries and Gemini (no explicit timeout set). That implies a worst case of minutes per question (SUSPECTED, UNTESTED). Only `generate_structured` (intent understanding) sets `timeout` and `max_retries=0`.
* Retrying the same `request_id` once providers are back returned the stored degraded text in 8 ms with zero model calls (VERIFIED). A fresh `request_id` got a real answer (2 calls).
* Offline machine: the first memory-using chat turn blocks on the SBERT load for 218 s (REL-01, VERIFIED below).
* External data libraries: with the network blocked, `yfinance` and Yahoo symbol search raise at once, equity, market and lookup paths returned fixed "couldn't find reliable data" style answers (HTTP 200) rather than errors. `instruments._yahoo_lookup` uses `timeout=6` and failures are not cached (`_cached` stores only successes), so with a hanging Yahoo each search window would wait up to 6 s, up to 6 windows per query (`lookup._MAX_SEARCHES = 6`): up to ~36 s (SUSPECTED, UNTESTED).

## 8. Voice latency and avatar (local engines only; `results/voice.json`)

* The previous avatar measurements in `docs/MEASUREMENTS.md` (engine and LiveTalking modes, GPU) concern modes the changelog says were removed; the current tree has only an `/avatar/render` page and a live WebSocket. I re-measured nothing from that file, and no browser/avatar path was driven (UNTESTED).
* Piper TTS (`ai/speech/live_tts`, `en_US-amy-medium`, CPU): model load plus first synthesis 2.5 s; 20 syntheses of 5 sentences (2.9 to 6.8 s of audio each): p50 265 ms, p95 323, max 335; real-time factor p50 0.049, p95 0.055 (about 20x faster than real time).
* Whisper `base.en` on CPU (torch CPU-only; `/api/voice/transcribe` path): load 5.5 s; 10 transcriptions of 5.2 s clips: p50 1.88 s, p95 2.26 s, max 2.40 s (about 0.36x real time). The clips were synthetic Piper speech, so transcription accuracy is not assessed.
* Written replies use `ai/speech/tts.synthesize` (Edge-TTS over the network, pyttsx3 fallback), not Piper. Edge-TTS latency was UNTESTED (network). The background pool is 4 workers with 16 slots (`api/audio_store.py`).
* SUSPECTED: in an early, uncaptured run two audio jobs started together logged `Edge-TTS failed: module 'edge_tts' has no attribute 'Communicate'` and `cannot import name 'hdrs' from partially initialized module 'aiohttp' (most likely due to a circular import)`, i.e. a first-import race between the two worker threads, after which pyttsx3 was used. I did not capture it to a file or reproduce it afterwards.

## 9. Defects

| ID | Title | Severity | Label |
|---|---|---|---|
| PERF-01 | Instrument search is an O(catalogue) pure-Python fuzzy scan | P1 | VERIFIED |
| REL-01 | Offline / unreachable Hugging Face stalls the SBERT load for 218 s | P1 | VERIFIED |
| PERF-02 | Memory retrieval cost grows with the owner's whole archive, every turn | P2 | VERIFIED |
| PERF-03 | Per-turn persistence and history reads grow with conversation length; unpaged history/export | P2 | VERIFIED |
| PERF-04 | Voice transcribe blocks the event loop | P2 | VERIFIED |
| REL-02 | Retry amplification and blocking sleeps when providers fail; no deadline | P2 | VERIFIED (amplification), UNTESTED (hang) |
| REL-05 | WebSockets use admission slots, so open sockets 503 the whole API | P2 | VERIFIED |
| PERF-05 | Every written reply triggers an unrequested audio-script model call and TTS | P2 | VERIFIED |
| REL-03 | Degraded answer persisted as complete and replayed on retry | P3 | VERIFIED |
| REL-04 | Crashed request holds its lease for 30 min | P3 | VERIFIED |
| REL-06 | Rate limiter is per socket peer, one bucket behind a proxy | P3 | VERIFIED (boundary), RECOMMENDATION |
| REL-07 | Failed Yahoo lookups are not negatively cached | P3 | SUSPECTED |
| PERF-06 | ~1.1 GB resident with all models; session cache never evicts | P3 | VERIFIED / SUSPECTED |

### PERF-01 Instrument search is an O(catalogue) pure-Python fuzzy scan (P1, VERIFIED)
* Component: `modules/market/instruments.py` `_score` (lines ~381 to 410, `SequenceMatcher(...).ratio()` against every word of every catalogue item), `search` (442); callers `api/routes/instruments.py:26` and `modules/qa/lookup.py:107-125` (`find_instrument`, up to 6 windows per question).
* Evidence: `bench_instrument_search.py`: 20 typeahead queries x 3: p50 1,136 ms, p95 1,606, max 1,737 (n=60; "tat" 26 ms, "tata" 1,079 ms, "reliance" 1,596 ms, "zomato" 1,647 ms returning 0 items, "xyzq" 813 ms). `bench_lookup_hotspot.py` profile: 12.5 s for 2 calls under cProfile, 310,634 `SequenceMatcher.ratio` calls, 38,938 `_score` calls (about 39k items); direct timing 1.1 to 2.9 s per call; routing p50 by route for `data_lookup` 1.6 to 2.2 s in every variant.
* Why it matters: the Markets/Explore search box (a call per keystroke is plausible) and every "price/market cap of X" question wait 1 to 10 s on a single-threaded GIL-bound loop, which also slows concurrent requests on the same process.
* Proposed fix: index the catalogue once (token or n-gram inverted index, or `rapidfuzz` with a prefilter), run fuzzy matching only after exact and prefix matching fail, cache results per normalised query (including empty results), debounce on the client.
* Regression risk: medium; ranking and typo-tolerance behaviour are tested by `tests/` and the lookup benchmarks, so rerun them.

### REL-01 Offline / unreachable Hugging Face stalls the SBERT load for 218 s (P1, VERIFIED)
* Component: `shared/vector_store.py:25` (`SentenceTransformer(SBERT_MODEL, device=...)`, no `local_files_only`), called lazily from `shared/conversation_memory._embedding` (line 293, in the request path) and from the warm-up thread (`api/main.py:_warm_up`). Nothing in the repo sets `HF_HUB_OFFLINE` or `TRANSFORMERS_OFFLINE` (grep; only `scripts/run_system_audit.py` does).
* Evidence: `bench_startup.py sbert-no-flag` (HF unreachable by connection refusal, model present in the local cache): 218.0 s load (wall 232 s) vs 0.34 to 0.36 s with `HF_HUB_OFFLINE=1` (n=2). The stack dump `results/diag_slow_query_stacks.txt` shows the thread inside `huggingface_hub.get_hf_file_metadata` retrying ("Retrying in 1s/2s/4s [Retry n/5]") under `_get_encoder <- _embedding <- retrieve <- context_for`. In the routing sweep the same 218 s showed as "what about infosys" in variants A and C (4 samples between 217.9 and 219.0 s), the first turn with prior conversation records in a process whose encoder had not been loaded. Variants B, D, E, H preload the encoder in the harness so were unaffected.
* Condition: a refused connection. A fully offline NIC (DNS failure) was not tested and may differ (UNTESTED).
* Why it matters: a laptop product used on a flaky or absent connection freezes the first chat (and the warm-up thread) for ~3.6 minutes, or longer if more files are checked.
* Proposed fix: set `HF_HUB_OFFLINE=1` in the launcher, Dockerfile and compose when the model is baked in or cached, or pass `local_files_only=True` first and fall back to download; never load the encoder inside a request without a timeout (use the warm state or skip the semantic part).
* Regression risk: low; a first-ever run without the cached model must still be able to download (provide an explicit download step).

### PERF-02 Memory retrieval cost grows with the owner's whole archive, every turn (P2, VERIFIED)
* Component: `shared/conversation_memory.py` `retrieve` (lines 300 to 375): loads all complete turns of the owner (`rows = db.scalars(...)`, no limit), `json.loads` of each, tokenises all, BM25 over all, and for semantic mode up to 200 candidates x 2 texts with one DB session per embedding (`_embedding`, 285). Called under the session lock from `core/session.execute_turn`.
* Evidence: section 3: p50 28 / 120 / 272 / 667 / 1,514 / 3,395 ms at 100 / 500 / 1,000 / 2,500 / 5,000 / 10,000 records (n=9 each); +~0.16 s (stub encoder) for semantic; first semantic query 28.6 s at 1,000 records with real SBERT (n=1). Prompt growth showed no benefit on the tutor path (sec. 3).
* Why it matters: latency before any model call increases for heavy users: a user with 2,500 saved turns adds 0.7 to 1 s to every message; there is no cap. It also keeps the whole archive in memory per request.
* Proposed fix: restrict candidates in SQL (recent N plus FTS5 hits on `query`), cache document statistics, batch the embedding lookups in one query and encode misses in one batch, precompute embeddings on write (background), and only build context for calls that will use it.
* Regression risk: medium (retrieval quality is covered by `rag_memory_eval.py`; rerun it).

### PERF-03 Per-turn persistence and history reads grow with conversation length (P2, VERIFIED)
* Component: `core/session.py` `execute_turn` / `get_session` call `memory.load(session_id)` (reads and `json.loads` every complete turn) several times per turn; `api/routes/chat.py` `GET /history` returns all turns; `shared/conversation_history.export`.
* Evidence: `results/session_memory_console.txt` (execute_turn with a trivial action, no model, scratch DB, n=5 per length): p50 11.8 ms at 5 prior turns, 48.2 at 95, 126 at 295, 232 at 595, 312 at 995 (about 0.3 ms per prior turn). `history_scale.json`: unpaged history 186 ms p50 and 14.2 MB at 3,000 turns; export 232 ms and 14.7 MB.
* Why it matters: a long-running chat gets steadily slower to save, and the unpaged endpoints transfer megabytes.
* Proposed fix: keep `execute_turn` from reloading full history (use the last k turns and a count), page `GET /history` (the paged `/api/conversations/{id}/messages` already exists), stream the export.
* Regression risk: low to medium (the in-memory `history` is read by module pipelines for follow-ups).

### PERF-04 Voice transcribe blocks the event loop (P2, VERIFIED, n=1 stall observation)
* Component: `api/routes/voice.py:13-30` (`async def transcribe_audio` calling blocking `ai.speech.stt.transcribe`).
* Evidence: `bench_voice.py`: a 1.75 s transcription of a 5.5 s clip on the 8016 server; the concurrent `/api/health` poll (every 50 ms) completed once during it with 1,706 ms latency (27 ms before). CPU Whisper: p50 1.88 s per 5.2 s clip (n=10).
* Why it matters: every request on the process (chat, health, WebSockets) stops for the transcription; with a longer clip the pause is longer.
* Proposed fix: make the endpoint a plain `def` (FastAPI runs it in the thread pool) or `await run_in_threadpool(...)`; bound concurrent transcriptions.
* Regression risk: low.

### REL-02 Retry amplification and blocking sleeps when providers fail (P2, VERIFIED amplification; hang UNTESTED)
* Component: `ai/llm/groq_client.py:195-262` `generate_response` (chain groq, gemini, groq-small, groq-qwen; two passes on `429|503|rate limit|unavailable|overloaded` with `time.sleep(2)`); `_dead` only reacts to "tokens per day".
* Evidence: section 7 table; one general question with every provider failing: 8 attempts, 30,336 prompt characters (about 7,600 estimated input tokens) sent across attempts; 16 attempts and 8 s sleeping for a 503-type failure; the finance-profile path 24 attempts and 12 s. The sleeps run in the request thread while the conversation lock is held.
* Why it matters: an outage multiplies free-tier quota use and request time per message, and the extra attempts on a rate-limited key are likely to deepen the rate limit; there is no per-request deadline.
* Proposed fix: one deadline budget per user request; short circuit breaker (for example 30 to 60 s) on connect errors, 5xx and 429 for each backend; skip the second pass unless the wait hint is short; set explicit timeouts and `max_retries` on both SDKs.
* Regression risk: medium (changes fallback order and answer availability).

### REL-05 WebSockets use admission slots (P2, VERIFIED)
* Component: `api/resource_limits.py:36-56`: `self.active` is incremented for websockets too and held for the life of the socket; default `ARIA_MAX_ACTIVE_REQUESTS=16`.
* Evidence: `test_resource_limits.py` with the real `ResourceLimits(max_active=4)`: 4 open sockets -> `GET /api/ping` returned 503 with `Retry-After: 60`; after closing one socket it returned 200 (`results/resource_limits.json`). The test uses a toy app; the ARIA app was not saturated with 16 real sockets (UNTESTED).
* Why it matters: 16 idle live-meeting tabs or leaked sockets make the whole API return 503 for that process.
* Proposed fix: do not count websockets in `active` (or give them a separate cap); keep the rate limit per connection attempt.
* Regression risk: low.

### PERF-05 Every written reply triggers an extra model call and a TTS job (P2, VERIFIED)
* Component: `modules/qa/present.py:26-38, 53` `audio_token` -> `ai/llm/audio_script.generate_audio_script` (model call) -> `ai/speech/tts.synthesize` (Edge-TTS over the network); `api/audio_store.py` (4 workers, 16 slots).
* Evidence: `results/background_audio.json`: 12 of 12 replies produced one audio-script call (942 to 1,483 chars of prompt) and one synthesis, in Normal Mode.
* Why it matters: about 235 to 370 extra input tokens and an external TTS request per reply, even if the user never presses play; it competes for the same free-tier quota as the answer. If the model fails, the spoken text becomes "Sorry, something went wrong while generating audio." (code reading).
* Proposed fix: create the clip on first play request (lazy), or only in voice modes.
* Regression risk: low to medium (first-play latency; the UI expects an `audio_token`).

### REL-03 Degraded answer persisted as complete and replayed (P3, VERIFIED)
* Component: `shared/conversation_memory.complete` (status is `failed` only when the response starts with "error:"), `modules/qa/trust.py` (`DEGRADED` text replaces the "Error:" reply before it is stored).
* Evidence: `bench_cost_failure.py` section "retry_same_request_id": same `request_id` after recovery -> 8 ms, 0 model calls, degraded text; new `request_id` -> real answer. `bench_sqlite_concurrency.py` (f) shows the stored status is `complete`.
* Why it matters: a client or proxy that retries the same `request_id` keeps the apology forever; the apology is also in the history and is fed to later memory retrieval as an assistant turn. The web client generates a new UUID on every send (`web/src/api.ts:134`), so the UI itself is not affected.
* Proposed fix: store degraded replies as `failed`, so `begin()` regenerates; exclude them from memory retrieval.
* Regression risk: low.

### REL-04 Crashed request holds its lease for 30 minutes (P3, VERIFIED)
* Component: `shared/conversation_memory.begin` (`ARIA_REQUEST_LEASE_SECONDS`, default 1800).
* Evidence: `sqlite_concurrency.json` `leases.retry_after_crash_within_lease`: retry gets `RequestBusy` (HTTP 409 via `answer_http`) while the lease is valid. The in-process lock does not help after a hard kill.
* Proposed fix: lease of a few minutes with heartbeat/extension, or tie it to a process id and expire it at startup.
* Regression risk: low.

### REL-06 Rate limiter is per socket peer (P3, RECOMMENDATION)
* `api/resource_limits.py`: the bucket key is `scope["client"][0]`; forwarded headers are deliberately ignored (documented). Behind a reverse proxy or Docker NAT all users share one 120 POST/min bucket. Boundary VERIFIED (request 121 returned 429). Every POST counts, including cheap ones such as `/api/chat/clear`. Fix: set the proxy to rate-limit (as the docstring says) or accept a trusted-proxy list. Regression risk: low.

### REL-07 Failed Yahoo lookups not negatively cached (P3, SUSPECTED)
* `modules/market/instruments.py:72-88` `_cached` stores only successes; `_yahoo_lookup` has a 6 s timeout; `lookup.find_instrument` can try 6 windows. With a hanging Yahoo that is up to ~36 s per question. Not tested (needs a hanging peer). Fix: short negative cache (30 to 60 s) and a per-request network budget.

### PERF-06 Memory footprint and session cache (P3)
* VERIFIED: 1.09 GB working set after warm-up, 1.2 GB with Whisper; FinBERT alone is +445 MB. SUSPECTED: `_SESSIONS` and `_LOCKS` in `core/session.py` never evict; each cached session holds its whole `history`. Fix: lazy FinBERT/Whisper, LRU for sessions.

## 10. What was NOT tested, and why

* Any real provider call (Groq, Gemini, Edge-TTS, Yahoo, Screener, news, FRED, AMFI): forbidden. Provider latency, real rate-limit behaviour and a hung provider are UNTESTED; the fake-slow-server test would need a second local port.
* Real money cost: no price table in the repo, free tiers, no real calls. Only estimated tokens (characters / 4) are given.
* Full end-to-end answer quality and answer latency per path with real data (equity, market, intelligence, forecast, scenario backtest, report generation, statement import): the data sources are network-only. Their module-level cost on real data is UNTESTED.
* Browser page load and the React app: no browser was allowed; the `web/` build and bundle size were not measured. The earlier avatar/lip-sync figures in `docs/MEASUREMENTS.md` were not re-measured because those modes were removed; the current live WebSocket and `/avatar/render` page were not driven.
* Edge-TTS latency, the live-meeting audio pipeline, and the `warm_up` steps for markets, instruments, news and Piper in the real server.
* A fully offline NIC (as opposed to a refused connection) for the Hugging Face stall.
* Long soak (hours), many-GB archives, and multi-worker uvicorn (the lease race was simulated with threads, not processes). The 8 client-thread limit applied, so concurrency above 8 and the 16-slot admission limit on the real app are UNTESTED.
* Quiet-machine numbers: all runs shared the laptop with a background sweep and other sessions.
* `trust.enforce` and cached versus first-call `normalize` costs (see section 2).
* Locust/k6: not installed; the simple threaded harness in `http_load.py` was used instead.

## 11. How to re-run

From `ARIA_EVALUATION/evaluation/performance/` (Git Bash): `./run_scratch.sh <script.py>` runs one script with a scratch DB, private auth and blank keys at low priority (HF flag: prefix `HF_HUB_OFFLINE=1`). Routing: `python run_routing.py A,B,C,D,E,H 2` then `python summarize_routing.py` (about 5 min per run). Server tests: `http_load.py`, `bench_voice.py` start and stop their own server on port 8016. Scripts: `bench_engines_retrieval.py`, `bench_history_scale.py`, `bench_memory_scaling.py [--real]`, `bench_sqlite_concurrency.py`, `bench_cost_failure.py`, `bench_background_audio.py`, `bench_lookup_hotspot.py`, `bench_instrument_search.py`, `bench_session_memory.py`, `bench_startup.py <mode>`, `bench_voice.py`, `test_resource_limits.py`, `diag_slow_query.py`.
