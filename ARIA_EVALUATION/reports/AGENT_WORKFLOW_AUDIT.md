# ARIA agent / workflow audit (Phase A)

Date: 2026-11-02. Working tree of `main` (d8645d9 plus uncommitted edits to `core/orchestrator.py` and `core/intent/arch.py`, which this audit read as they are on disk). Application code was not modified. Everything below was produced offline: no Groq/Gemini/network call, no server, no browser, no microphone, scratch SQLite DB only. Evidence script: `ARIA_EVALUATION/tests/integration/workflow_audit.py` (22 probes, 13 behave as expected-safe, 9 FAIL = findings; run with `OMP_NUM_THREADS=2 .venv\Scripts\python.exe -X utf8 ARIA_EVALUATION\tests\integration\workflow_audit.py`). Earlier routing-accuracy work is in `agent_routing_eval.py` and is not repeated here.

## 1. Summary

ARIA is not a free-roaming multi-agent system. It is one deterministic router/orchestrator (`core/orchestrator.py`) that calls ONE module pipeline per turn (finance, tutor, market, equity research, company intelligence, data lookup, small talk, general model), wrapped in a per-conversation turn ledger (`core/session.py` + `shared/conversation_memory.py`). The only true multi-agent pieces are the bull/bear/judge debate and narrator inside the company-intelligence report, and the optional LangGraph split-and-merge for multi-part questions (variants C/D/E/H).

Headline findings:
* The earlier session-lock/LangGraph deadlock is fixed in production: the graph runs parts sequentially in the calling thread and no call site passes `parallel=True` (VERIFIED, P2/P2b). The hazard still exists latently: `parallel=True` deadlocks on a held session lock (VERIFIED, P2). I found no other thread in the answer path that takes the session lock (VERIFIED by grep, section 5).
* AW-01 (P2): when a variant (B-H) picks a pipeline that raises, the exception is swallowed and the baseline chain runs again, so the same failing, possibly expensive pipeline can be called twice in one turn (VERIFIED, P3b: 2 calls), or the failure is silently replaced by an ungrounded general-model answer (VERIFIED, P3).
* AW-02 (P2): in a multi-part answer, a "Data" part whose lookup found nothing is answered by the general model with no evidence, under a "Data" heading (VERIFIED, P8).
* AW-03 (P2): the main Groq and Gemini calls have no explicit timeout or wall-clock budget; worst case is long and held under the session lock (code VERIFIED; magnitude computed, not measured).
* AW-04 (P2): in the baseline path a module exception is not caught by the orchestrator; it propagates to the HTTP/Live layer (VERIFIED at orchestrator level, P4a). HTTP-level result UNTESTED.
* Smaller: output-guard pool starvation (AW-05), vacuous `numbers_checked` (AW-06), evidence of first part attributed to merged reply (AW-07), unbounded per-session dicts (AW-08), timed-out report threads keep running (AW-09), Live job continues after cancel (AW-10), dead code `forced_label` (AW-11), context vars lost in the intelligence thread pool (AW-12).
* Good: crisis gate makes zero model calls (P10), idempotent replay by `request_id` works and runs the action once under 3-way concurrency (P5a, P4b), different sessions run in parallel (P5c), all variants survive router and LLM being down (P9, P9b), a failed multi-part sub-answer is reported honestly and an `Error:` string never reaches the user (P1c).

## 2. Inventory (VERIFIED from reading the files)

| Component | File | Role | Input -> output | Failure behaviour |
|---|---|---|---|---|
| QA pipeline | `modules/qa/pipeline.py` `answer()` | Single entry for chat, voice, live, avatar. normalise -> precheck -> `execute_turn` -> `_run` -> `_finish` (degrade `Error:` text, `trust.enforce/finalize`) -> `present` | `QARequest` -> `QAResponse` | raises PermissionError/ValueError/NotFound (mapped by routes to 403/409/404); any other exception propagates |
| Turn ledger / lock | `core/session.py` | process-local RLock per session id held for the WHOLE turn; DB ledger (turn row + lease) via `memory.begin/complete/fail` | `execute_turn(session_id, query, action, request_id)` | on exception marks turn `interrupted` and re-raises; same `request_id` replays a complete turn |
| Orchestrator | `core/orchestrator.py` `handle_query -> _handle_query -> _tone_and_handle -> _handle` | crisis gate, generic-company guard, dialogue acts, intent resolver (LLM, optional), tone layer, focus path, follow-up carry, routing | query -> response dict | tone layer, output guard, data lookup, architecture layer each catch their own exceptions; module pipelines are NOT wrapped |
| Rule router | `core/router.py`, `modules/*/pipeline.py` predicates, `shared/intent_classifier.py` | keyword/regex route: finance, tutor, market, equity research, intelligence, concept, quiz, general | text -> label | pure functions |
| Architecture layer | `core/intent/arch.py`, `semantic.py`, `understanding.py`, `taxonomy.py`, `graph.py` | variants A baseline (default), B semantic router fallback, C rule-split + graph, D structured LLM + SR + graph, E rules first then D, H adaptive (model only for unplaced/multi/follow-up/concept; `guard()` limits when it may overrule rules) | query, history -> `Decision(label, clarify, sub_queries)` | `_architecture_route` wraps everything in try/except -> None (baseline runs) |
| Graph | `core/intent/graph.py` | LangGraph plan -> execute(loop) -> verify -> synthesise; per-part retry 1x on exception; no merge LLM call | plan list -> merged response with `parts`, `grounding`, `intent_graph` trace | failed part rendered as "I couldn't complete this part just now, so I won't guess." |
| Tools / modules | `modules/tutor`, `modules/finance`, `modules/market`, `modules/equity_research` (+ `intelligence`: narrator, bull, bear, judge agents), `modules/qa/lookup.py` (catalogue then web search), `modules/qa/focus.py` | one pipeline each | see ARCHITECTURE_MAP | module-specific; intelligence report has a model deadline and template fallback |
| LLM client | `ai/llm/groq_client.py` | `generate_response`: chain groq -> gemini -> groq-small -> groq-qwen, 2 passes, 2 s or hinted sleep on 429/503; daily-quota backends skipped 30 min; returns the string `Error: ...` on total failure. `generate_structured`: Groq only, 8 s timeout, `max_retries=0`, returns None on any failure | | |
| Trust / grounding | `modules/qa/trust.py` | number redaction against fetched data, disclaimers, degrade | | |
| Live avatar | `api/routes/live.py` | websocket; `asyncio.to_thread(pipeline.answer)`, filler lines every 7 s up to 14 times | | pipeline exception -> `None` -> fixed "trouble" line |

Shared state: `_SESSIONS` and `_LOCKS` dicts (process memory), conversation DB (turns, leases), ContextVars (`active_request`, `active_context`, `current_interpretation`, `active_focus`, `current_owner`, `llm_stats`, voice/news blocks). There is no inter-agent message bus; handoff is function call + ContextVars + the session dict.

Routing order inside `_handle` (baseline): interpreted intent (if resolver ran) -> general task -> focus item -> follow-up with evidence -> small talk -> pending finance / finance intent -> missing-subject clarify -> (architecture layer if not A and no pending finance) -> quiz -> data lookup -> intelligence -> equity research -> stock suggestions -> broad market -> finance -> tutor -> market fallback -> concept -> spelling suggestion -> general model.

## 3. Test results (offline probes)

| Probe | Question | Result |
|---|---|---|
| P1a | graph part raises once | retried, ok, 3 handler calls for 2 parts. PASS |
| P1b | all parts fail | honest text, `passed=False`, but `numbers_checked=True` (vacuous). FAIL -> AW-06 |
| P1c | handler returns `Error:` text | part marked failed, text hidden. PASS |
| P1e | merged evidence | `report_id`/`context` of first answered part attached to merged reply. FAIL -> AW-07 |
| P2 | held session lock + graph | sequential finishes; parallel=True hangs (deadlock). Production uses sequential. PASS (documented hazard) |
| P3 | variant B router says market, market pipeline raises once | swallowed; baseline answered with the general model (failure masked). 1 market call |
| P3b | variant agrees with rules (override mode), pipeline always fails | pipeline called 2x, then exception. FAIL -> AW-01 |
| P4a | baseline module exception | propagates out of `handle_query`; turn row status `interrupted`. FAIL -> AW-04 |
| P4b | retry same `request_id` | re-executes; later replay does not run the action. PASS |
| P5a-c | concurrency | identical `request_id` x3: action ran once; same session serialises; different sessions parallel. PASS |
| P5d | per-session dict eviction | none (7 locks, 6 sessions after the test). FAIL -> AW-08 |
| P6 | 6 guard calls with a stuck classifier, pool of 4 | all 6 skipped at the timeout; 2 stayed queued behind stuck workers. FAIL -> AW-05 |
| P7a | all providers 429 | 8 backend calls (2 passes x 4), 2 sleeps of 3.5 s, returns `Error:` string. PASS (bounded, but see AW-03) |
| P7b | daily quota | backends skipped on the next call (4 -> 0 calls). PASS |
| P7c | explicit timeout on main calls | none. FAIL -> AW-03. Installed groq SDK defaults: timeout read=60 s, max_retries=2 |
| P8 | multi-part, lookup finds nothing | general model answer under "Data". FAIL -> AW-02 |
| P9 / P9b | variants B-H with LLM and router down, router raising | no exception; baseline route. PASS |
| P10 | self-harm message | `care` reply, 0 pipelines, 0 model calls. PASS |
| P11 | `arch.forced_label` | defined only, never read or set. FAIL -> AW-11 |

## 4. Defects

Format: id, title, evidence, component, severity, why it matters, fix, regression risk. Label VERIFIED unless noted.

**AW-01 Variant routing re-runs a pipeline that just failed (P2)**
Evidence: `core/orchestrator.py:359-371` (`_architecture_route` catches every exception and returns None) then `_handle` continues into the baseline chain at 216-253. Probe P3b: market pipeline raising, variant B override agreeing with rules -> 2 calls. P3: failure replaced by `_general_reply` (ungrounded).
Component: orchestrator / arch layer. Why: doubles latency and token/data cost on an already failing provider, duplicates side effects (finance profile writes, report persistence, `_queue_forecast`), and can swap a grounded module answer for a model answer. Only affects non-default variants (default A returns None immediately), so it matters when a variant is adopted.
Fix: have `_architecture_route` return a marker on a pipeline exception (or record the label already attempted) so `_handle` does not rerun that label; degrade to an honest "could not complete" reply rather than the general model. Regression risk: low-medium, touches the A/B benchmark path; rerun `evaluation/intent_understanding` offline stubs.

**AW-02 Multi-part "Data" part falls back to the ungrounded general model (P2)**
Evidence: `core/orchestrator.py:359-360` `_run_label(...) or _with_news(text, _general_reply)`; `_run_label("data_lookup")` returns None when neither catalogue nor web search knows the name (line 315-316). Probe P8: part domain `general`, headed "**Data**". Component: orchestrator + graph. Why: `graph.verify` only checks parts that produced a response, so a model-invented company figure is presented as data; contradicts the module's "won't guess" design. Fix: for label `data_lookup` (and `equity_research`/`company_intelligence`) treat None as a failed part (return None to the graph handler -> "couldn't complete"). Regression risk: low.

**AW-03 No timeout or wall-clock budget on the main LLM calls (P2)**
Evidence: `ai/llm/groq_client.py:105-124` (`client.chat.completions.create` without `timeout`), `158-187` Gemini without timeout; `generate_response` loops 4 backends x 2 passes with up to 30 s sleeps (lines 233-251). Probe P7c; installed SDK default read timeout 60 s and 2 SDK retries. Component: LLM client. Why: a hung or slow provider can hold a request (and the per-session lock, and a worker thread) for minutes; Live mode speaks filler lines for at most 14 x 7 s then waits unbounded (`api/routes/live.py` `_ask_pipeline`). Worst case is a computation from these constants, not a measurement (a real timeout test is BLOCKED: needs network). Fix: pass `timeout=` and `max_retries=0` per backend and add an overall deadline to `generate_response` (e.g. 25 s) after which it returns the `Error:` string. Regression risk: medium, long report prompts may need a larger per-call budget; make it configurable.

**AW-04 Baseline module exceptions are not caught at the orchestrator (P2, impact depends on routes)**
Evidence: `_handle` calls pipelines directly (lines 219-253) with no try/except; `modules/market/pipeline.py` contains no `except`. Probe P4a: exception reaches caller, turn marked `interrupted`. `answer_http` (`api/routes/chat.py:46-60`) maps only NotFound/PermissionError/ValueError; `api/main.py` has no generic exception handler (grep). So an unexpected module error is a framework 500, not the degraded reply the `trust.DEGRADED` path was built for. HTTP behaviour UNTESTED (no server run). Component: orchestrator / chat route. Why: the degrade/honesty path covers an `Error:` string from the LLM but not a raised exception. Idempotent retry works (P4b), which limits the harm. Fix: catch Exception around the routed pipeline call in `_handle` (or in `qa.pipeline._run`), log class only, return a `domain=...` degraded response. Regression risk: low; make sure the tests that expect propagation (if any) are updated.

**AW-05 Output-guard pool saturates (P3)**
Evidence: `core/orchestrator.py:382-392`; `Future.result(timeout)` does not stop the worker. Probe P6: after 6 calls with a stuck classifier, 2 tasks were queued. Each stuck worker lasts a full `generate_response` chain (many seconds). Why: during a provider incident every turn adds a classifier call to the same failing provider and the tag silently disappears; extra token burn. Fix: skip the guard when the answer is already degraded, add a circuit breaker (skip for N seconds after a timeout). Regression risk: low (tag is non-blocking).

**AW-06 `numbers_checked` is vacuously True when every part failed (P3)**
Evidence: `core/intent/graph.py:113`, `all(... for r in parts if r.get("ok"))` over an empty set; probe P1b. `passed=False` and `fallback=True` are right. Fix: `bool(ok_parts) and all(...)`. Regression risk: negligible.

**AW-07 Merged reply copies the first part's evidence (P3)**
Evidence: `core/intent/graph.py:116-119`, probe P1e (`report_id` of part 1 on a two-module answer). Why: UI shows a report/context card that supports only one part of the text; `merged["domain"]` also takes the first part's domain, which `qa.pipeline` and `trust.finalize` use for disclaimer/route logic. Fix: namespace per part (`parts[i].report_id`) and keep top-level domain `multi`. Regression risk: low-medium (frontend reads `report_id`).

**AW-08 `_SESSIONS` and `_LOCKS` never evicted (P3)**
Evidence: `core/session.py:7-14` (setdefault, no removal except `clear_session`); probe P5d. Why: slow memory growth on a long-running server with many conversations; the lock is also process-local, so with more than one uvicorn worker the in-process serialisation does not hold (the DB lease then returns `RequestBusy`; multi-worker behaviour UNTESTED). Fix: LRU/TTL on idle sessions; document single-worker requirement or lock via the lease. Regression risk: low.

**AW-09 Timed-out narrator/debate threads keep running (P3)**
Evidence: `modules/equity_research/intelligence/pipeline.py:198-220`: `pool.shutdown(wait=False, cancel_futures=True)` cancels only queued work; a running narrate/debate keeps calling the LLM (up to its own chain) after the report was returned from the template. Also `pool.submit(agents.narrate, ...)` has no `copy_context()` (unlike `agents.py:411`), so ContextVars (`llm_stats`, `current_owner`, news block) are not visible in those threads (SUSPECTED effect: token/latency accounting and news context missing from the narrator; not tested). Fix: cooperative cancel flag checked between LLM calls; submit with `copy_context().run`. Regression risk: low.

**AW-10 Live avatar: cancelling does not stop the pipeline (P3)**
Evidence: `api/routes/live.py:87,97-103` `job.cancel()` on an `asyncio.to_thread` task cannot interrupt the thread; the thread keeps the session lock and finishes, and a following turn on the same session waits for it. Behaviour is standard asyncio semantics (VERIFIED by reading); not exercised (no websocket run). Fix: a per-turn cancel token checked between stages, or bound the wait. Regression risk: medium.

**AW-11 Dead code (P3)** `core/intent/arch.py:55` `forced_label` ContextVar, comment says "set by the graph for one sub-task"; nothing reads or sets it (`git grep`, probe P11). Fix: delete. Risk: none.

**AW-12 Cost multiplier under variants (P3, RECOMMENDATION)** With D/E/H a turn can make: resolver call (`shared/intent_resolver`, up to 8 s) + `understand` call (up to 8 s) + the pipeline's own calls + the output-guard classifier, all serialised under the session lock. Not measured (needs a real model); counted from `_handle_query` and `_architecture_route`. Consider skipping the resolver when the architecture layer will run its own understanding.

## 5. Lock / deadlock review (VERIFIED by reading + probes)

* The lock is held from `execute_turn` for the entire turn (`core/session.py:42-66`). `save_turn`, `get_session`, `clear_session` re-enter it (RLock), safe on the owning thread.
* Worker threads in the answer path and whether they touch the session: `orchestrator._GUARD_POOL` runs `validate_output -> classify_domain -> generate_response` with an explicit system prompt, so no `augment` and no session access; `intelligence/pipeline.py` narrate/debate pool, `agents.debate` pool, `intelligence/data.py` and `fund.py` fetch pools, `investment.py` quote+news pool, `shared/news.py` pool: `grep get_session|save_turn|session_lock|conversation_memory` finds no use in `modules/equity_research/intelligence/*`, `investment.py`, `shared/domain_guard.py`, `shared/news.py`. Live runs the whole `answer()` in one thread (`to_thread`), where it takes the lock itself. No remaining fan-out-vs-lock hazard found.
* Latent hazards: `graph.build(parallel=True)` (probe P2); any future worker that calls `get_session`/`save_turn`/`generate_response` with a default system prompt is safe only for `augment` (reads a ContextVar), not for session functions.
* A pipeline that blocks on a provider holds the lock for that long (AW-03); a second request on the same conversation queues, occupying a threadpool thread (anyio default 40); a burst of messages on one conversation could starve other requests (UNTESTED under load).

## 6. Trace and logging (VERIFIED by reading)

* One structured `qa.answer` log line per turn with stage timings and `llm_calls/llm_ms` (`modules/qa/pipeline.py:104-107`), response carries `qa.latency_ms`.
* Variants: `arch.log` emits `intent_route` with source/label/trace; responses carry `intent_route` and `intent_graph.nodes` (per-node ms, ok). Baseline has no routing trace beyond `domain` and `intent_resolution`; there is no record of WHICH rule fired (RECOMMENDATION: add a `route_reason` field).
* Failure logs record the exception class only in several places (good for secrets), but the `generate_response` warnings print the full provider error text `{e}` (`groq_client.py:244`); provider errors can echo request fragments (SUSPECTED, not checked against real payloads).
* No trace id ties the qa log line, LLM calls and graph nodes together except `request_id` in the DB (RECOMMENDATION).

## 7. Not tested, and why

* Real-model behaviour: structured understanding quality, semantic router thresholds with the real encoder, narrator/debate/judge output, real timeouts and 429 pacing: BLOCKED (no provider calls allowed; free-tier quota in use elsewhere).
* HTTP/websocket behaviour of an uncaught module exception (AW-04) and Live cancellation (AW-10): UNTESTED (no server started).
* Real module pipelines (market, finance, tutor, equity research) run end to end: UNTESTED; they were stubbed, so their internal retries and data-provider failure handling were only read, not exercised.
* Multi-worker deployment and load/concurrency beyond 3 threads: UNTESTED.
* Routing accuracy: not repeated; see `agent_routing_eval.py`. Variants D/E/H decision quality: needs a model; offline benchmark is in `evaluation/intent_understanding`.
* `core/router.py` keyword tables were read for role only, not audited line by line.
