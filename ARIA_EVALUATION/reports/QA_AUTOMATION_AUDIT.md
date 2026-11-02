# ARIA QA and automation audit (Phase A)

Date: 2026-11-02. Tree: `main` at d8645d9 plus the other sessions' uncommitted edits (core/intent/arch.py, core/orchestrator.py, benchmark files); nothing in application code was touched by this audit.
Labels: VERIFIED (command/file evidence given), SUSPECTED, RECOMMENDATION, UNTESTED, BLOCKED.

## 1. Summary

* VERIFIED: the repository suite passes in this tree: `1368 passed, 3 deselected` (the 3 are `network`-marked) in 4 min 34 s, with `GROQ_API_KEY` and `GEMINI_API_KEY` blanked, so it does not depend on provider keys. Line coverage of `api, core, modules, shared, ai` is **86 %** (17 990 statements, 2 557 missed; coverage.py, no `pytest-cov`).
* VERIFIED: 15 of the 226 new tests fail on purpose. Each is a reproducible defect (section 4); 211 pass.
* Headline defect: **QA-AUTH-001 (P1)**. In account mode `api.auth.authorize` only inspects a JSON body when the content-type starts with exactly `application/json`. Starlette parses `Application/JSON`, `application/JSON; charset=utf-8` and `application/vnd.api+json` as JSON. A signed-in attacker who knows a victim's account id can overwrite the victim's profile, write transactions into the victim's account, and write chats into the victim's history.
* Other verified defects: 500 on `{"x": NaN}` JSON bodies (QA-003), 500 on `/api/chat/clear` without `session_id` (QA-001), 500 on unknown quiz concept (QA-002), 500 on exporting a conversation with a non-Latin-1 title (QA-004), sign-in throttle that can be used to lock out an owner or every new email (QA-AUTH-002/003), `SyntaxWarning` in `shared/conversation_history.py` (QA-005).
* Process gap: CI runs only `tsc -b` and `vite build` on a PR. Neither the 1368 Python tests nor the Playwright specs run automatically (`.github/workflows/ci.yml`).
* Coverage gaps: `ai/speech/stt.py` 19 %, `core/intent/semantic.py` 29 %, `modules/equity_research/financial_pipeline.py` 26 %, `modules/equity_research/investment.py` 36 %. Real-model and live-network behaviour is not covered by any automated test (BLOCKED by this audit's constraints, UNTESTED).

### Incident to disclose
* VERIFIED: while probing `POST /api/chat` with "hello" (before I added guards) one request reached the real Groq backend and was refused with a 429 (daily token limit), then Edge-TTS tried a network call. That is one request against the quota the benchmark is using. After that every test I wrote runs under `mock_llm`, blank provider keys, and a socket guard that raises on any non-loopback connect (`ARIA_EVALUATION/tests/api/conftest.py`). The repository's own full suite was re-run only with blank keys.
* VERIFIED: the feedback route returned 502 in my first guarded run (an SMTP host is configured in the environment/`.env`; the socket guard stopped the send). The conftests now blank `ARIA_SMTP_HOST`. Name only; no value was read or printed.
* SUSPECTED: `tasks/byqi9v1mg.output` in the session task folder is 3.2 GB. It is not from any command in this audit; some other agent's job is writing unbounded output.

## 2. Test inventory and coverage

### Backend (VERIFIED: `grep -c "def test_"`, `coverage report`)
| Area | Tests | Line coverage |
|---|---|---|
| `tests/equity_research` | 265 | modules/equity_research 85.6 % |
| `tests/finance` | 158 | modules/finance 89.7 % |
| `tests/forecast` | 122 | (inside equity_research) |
| `tests/market` | 46 | modules/market 83.1 % |
| `tests/qa` | 39 | modules/qa 88.7 % |
| `tests/intent` | 22 | core 78.6 % |
| `tests/tutor` | 18 | modules/tutor 92.4 % |
| top-level `tests/test_*.py` (32 files: accounts, chat, conversation history/memory, feedback, resource limits, blocks, audio, live avatar, adversarial...) | about 340 | api 92.0 %, shared 93.1 % |

The sum is below 1368 because parametrised cases expand at run time.

API files: `api/auth.py` 92.7 %, `api/resource_limits.py` 91.8 %, `routes/conversations.py` 98.4 %, `routes/transactions.py` 81.4 % (parse/import error branches), `routes/voice.py` 86.2 %, `api/main.py` 57.7 % (warm-up thread, static mount), `routes/live.py` 91.5 %. `shared/conversation_history.py` 100 %.

Lowest files with at least 40 statements: ai/speech/stt.py 19 %, financial_pipeline 26 %, core/intent/semantic.py 29 %, finance/forecast_model.py 35 %, equity_research/investment.py 36 %, scenario_backtest/report_validation.py 40 %, ai/speech/live_tts.py 41 %, scenario_backtest/robustness.py 53 %, ai/speech/tts.py 56 %, ai/llm/groq_client.py 60 %. These are the paths that need a model, a codec or the network. Raw numbers: scratchpad `cov.json` / `cov_report.txt`.

Caveats: line coverage only (no branch coverage was run); `scripts/`, `config/`, `interface/` are outside `--source`; the tree contains uncommitted edits to `core/intent/arch.py` and `core/orchestrator.py`.

### Frontend
* VERIFIED: `web/e2e` has 11 spec files, about 34 test definitions (many parametrised over UI v1/v2 via `${version}`); `web/e2e-accounts` has 1 file with 3. Workflows covered by `workflows.spec.ts`: explore + drawer, company analysis, research report save/export/delete, news paging, settings, profile persistence, transactions add/import/dedupe/clear, navigation render, error/retry paths. `history.spec.ts` covers save, refresh, second device, rename, pin, search, rating, delete. `live-*`, `voice-*` specs stub `SpeechRecognition`; every spec that loads a page sets it to `undefined` (grep of `e2e/*.ts`), so none uses the real microphone.
* VERIFIED: the browser tests run against `scripts/audit_server.py` (real API and DB under `.audit/`, synthetic LLM/market providers). Good design: deterministic and offline.
* VERIFIED: there is no unit-test runner for `web/src` (no vitest/jest in `package.json` scripts) and `npm run lint` (oxlint) is not in CI.
* UNTESTED here: I ran no browser (constraint). Not covered by any spec I could find: conversation export UI, archive UI, `/api/conversations?archived=true` listing in the UI, markets page filters other than via workflows, mobile viewport for history panel (only resize.spec at desktop widths).

### CI
* VERIFIED (`.github/workflows/ci.yml`): `web` job (npm ci, tsc, build) runs on push to main and every PR. `python` job is `workflow_dispatch` only and needs about 7 training commands first. No Playwright, no lint, no coverage, no dependency audit, no secret scan.

## 3. API endpoint audit

Method: `ARIA_EVALUATION/tests/api/qa_matrix.py` (a table of 179 cases written earlier in Phase A) is now run in-process by `test_endpoint_matrix.py`; `run_matrix.py` runs the same table against a live instance (not run: no server was started). New: `test_conversations_qa.py` for the six `/api/conversations` operations added since the inventory.

* VERIFIED: `test_matrix_covers_every_openapi_operation` passes, so every non-conversation operation has at least one case; conversations are covered by the new file.
* VERIFIED: 160 of 165 in-process matrix tests pass (164 cases plus the OpenAPI parity check; the 3 chat cases that need a model and the 12 `net` cases are skipped). Failures: the defects QA-001..003 (clear, quiz x2, NaN x2). No response body contained a traceback, file path or SQLAlchemy text (the matrix checks this on every case).
* UNTESTED: 12 `net=True` cases (markets, instruments quote/chart/profile/sip, intelligence, ask) and `chat-valid`, `chat-injection`, `chat-bad-mode` (need a real model); `/api/voice/transcribe` with real audio (needs the STT model); WebSocket `/api/live/ws` beyond what `tests/test_live_avatar.py` covers; `/api/research/validation` and `/scenario-backtest` run flows (need the forecast engine).

### Conversations (new endpoints), VERIFIED by `test_conversations_qa.py` (42 tests, 40 pass)
* List: `limit` 0, negative, 1e9 (capped at 100), negative `offset`, `%`, `_`, `\`, SQL-looking and Devanagari `q`, 5 000-character `q`: never 5xx. Non-integer `limit`/`offset`/`archived` returns 422.
* PATCH: empty body 422, whitespace title 422 with no partial effect on `pinned`, title truncated to 120, script text stored verbatim (React escapes it; UNTESTED in browser), archiving clears the pin.
* Rating: `1`, `-1`, `null`, bool/float/str/2/0 never 500; a message id from another conversation 404.
* Paging: `limit` 0/-1/1e9, `before` 0/-3/1e15 never 5xx. Odd ids (`%00`, long, traversal-like) return 404/422.
* Delete is a soft delete; second delete/patch/export then return 404.
* Accounts mode: another account naming the victim as owner gets 403, naming itself gets 404, for PATCH, DELETE, export and rating. Missing/foreign `Origin` on state-changing calls with a valid cookie gets 403 (CSRF defence works). Anonymous gets 401 on every probed route including `/api/markets/overview`, `/avatar/live`, `/api/voice/transcribe`; `/api/health` stays open.
* One behaviour worth a product decision: writing to a deleted chat's session id revives it (documented by an existing test).

### Authentication and authorization
* VERIFIED good: registration/login cookie is HttpOnly, SameSite=Strict, sessions hashed (sha256) at rest, PBKDF2-SHA256 600 000 iterations, constant-time compare, dummy hash for unknown users, 9-session cap per account, Origin check on all non-GET requests, Google nonce + audience + issuer + email_verified checks (code read; Google flow UNTESTED, needs the network).
* VERIFIED good: multipart content-type is matched case-insensitively by Starlette and `authorize` handles it; the three multipart variants tested are refused.
* Defects: section 4 (QA-AUTH-001..004).

### Validation and error responses
Strong Pydantic limits on chat, profile, transactions, feedback, markets, instruments (lengths, ranges, `allow_inf_nan=False`). The defects are where validation is missing or bypassed: `/api/chat/clear` takes `dict[str, str]` and indexes it; `/api/quiz/answer` has no length or membership validation; JSON `NaN` literals crash the 422 response serialiser.

## 4. Defects

### QA-AUTH-001: authorization check can be bypassed by content-type spelling (P1)
* Component: `api/auth.py` `authorize` (lines 322-330 region) vs Starlette/FastAPI body parsing; consumers `api/routes/profile.py`, `transactions.py`, `chat.py`, `modules/qa/pipeline.py:93`.
* Evidence (VERIFIED): `python -m pytest ARIA_EVALUATION/tests/api/test_authz_accounts.py` in accounts mode. Attacker account POSTs `/api/profile` with body `{"session_id": "<victim id>", "monthly_income": 1}` and header `content-type: Application/JSON` (also `application/JSON; charset=utf-8`, `application/vnd.api+json`): HTTP 200 and the victim's `GET /api/profile` now returns `monthly_income = 1`. Same for `POST /api/transactions` (victim gets a row) and for `POST /api/chat?owner_id=<attacker>` with body `owner_id=<victim>`: the conversation appears in the victim's history because `pipeline.py:93` binds `current_owner` to the body value. `text/plain` and a missing content-type are correctly rejected (422).
* Why it matters: the product's account isolation guarantee ("private identifiers cannot select another account") fails for write paths; the victim's financial profile and chat history can be altered. Exploit needs the victim's 128-bit account id, so it is not remotely guessable, which is why this is P1 and not P0.
* Proposed fix: in `authorize`, parse the body whenever one is present (try `await request.json()` regardless of content-type, or lowercase and test `"json" in subtype`), and reject body-bearing requests whose content-type is neither JSON nor multipart/form-data with 415. Defence in depth: in accounts mode ignore `req.owner_id` in `modules/qa/pipeline.py` and use the already-bound `current_owner`.
* Regression risk: low to medium; clients that send unusual content-types (none in `web/src`) would start receiving 415. Rerun `tests/test_accounts.py` and the accounts Playwright spec.
* Not tested for the same class: `/api/quiz/answer`, `/api/chat/clear`, `/api/instruments/ask`, `/api/research/reports/{id}/regenerate` (body `owner_id`), `/api/transactions/import`. UNTESTED, but the root cause is shared.

### QA-AUTH-002: sign-in throttle table cap can refuse every new email (P2)
* Component: `api/auth.py` `_throttle` (4 096-row cap, 15-minute expiry).
* Evidence (VERIFIED, mechanism): `test_login_throttle_table_cap_blocks_every_new_email` pre-fills 4 096 rows; the next login or register for a brand-new email returns 429 "Sign-in is busy". Reaching the cap needs about 273 distinct emails per minute; the per-IP POST limit is 120/min by default, so 3 or more source IPs (or one proxy IP shared by all users, see recommendation R3) are needed. UNTESTED: the real attack rate.
* Why: unauthenticated users can stop all new sign-ins and sign-ups for the length of the attack.
* Fix: cap per source IP and per email separately and evict the oldest rows instead of failing; or throttle only existing accounts.
* Regression risk: low.

### QA-AUTH-003: ten failed logins lock the real owner out for 15 minutes (P2, design trade-off)
* Evidence (VERIFIED): `test_ten_failed_logins_lock_the_real_owner_out`: after 10 wrong passwords from another client the owner's correct login returns 429. The key is the email only.
* Fix: key on (email, source IP) plus a looser per-email ceiling; or exponential delay instead of a hard lock.
* Regression risk: low; changes brute-force economics, so keep the per-email ceiling.

### QA-AUTH-004: login returns 422 for a short wrong password (P3)
* Evidence (VERIFIED): `POST /api/auth/login` with `password: "short"` returns 422 because login reuses the registration schema (`Credentials`, `min_length=12`). Reveals the password policy and gives legacy short passwords no path.
* Fix: a separate login model with only `max_length`. Regression risk: none.

### QA-001: `POST /api/chat/clear` without `session_id` returns 500 (P3)
* Evidence (VERIFIED): `api/routes/chat.py` `clear_chat(req: dict[str, str])` does `req["session_id"]`; probe raises `KeyError: 'session_id'`; matrix case `clear-missing-key`.
* Fix: a Pydantic model `{session_id: str (1..200), owner_id: str | None}`. Regression risk: low (same body shape the UI sends).

### QA-002: `POST /api/quiz/answer` with an unknown concept returns 500; no length limits (P3)
* Evidence (VERIFIED): `api/routes/progress.py` has a bare `QuizAnswerRequest`; unknown id raises `ValueError: 'nope' is not in list` from the tutor; matrix cases `quiz-unknown-concept`, `quiz-huge-concept` (100 000-character id).
* Fix: `Field(min_length=1, max_length=200)` and validate `concept_id` against the concept KB (404/422). Regression risk: low.

### QA-003: JSON `NaN`/`Infinity` literal in a body returns 500 (P3)
* Evidence (VERIFIED): `POST /api/profile` and `POST /api/transactions` with `...:NaN}` raise `ValueError: Out of range float values are not JSON compliant` while FastAPI builds the 422 body (the offending input is echoed in the error). Matrix cases `profile-nan`, `txn-nan`. Any float field on any endpoint is affected.
* Fix: a small exception handler for `RequestValidationError` that drops `input` for non-finite floats, or reject non-finite constants when parsing (`parse_constant`). Regression risk: low.

### QA-004: exporting a conversation whose title contains non-Latin-1 letters returns 500 (P2)
* Component: `api/routes/conversations.py:53-57` and `shared/conversation_history.py` `export` (`slug` built with `str.isalnum()`).
* Evidence (VERIFIED): rename a chat to `निवेश योजना` then `GET /api/conversations/{id}/export` returns 500 (`test_export_with_non_ascii_title_does_not_500`). `isalnum()` keeps Devanagari letters; the `Content-Disposition` header must be latin-1.
* Why it matters: ARIA targets Indian users and handles Hinglish; auto-titles come from the user's first question, so a Hindi first question makes export fail. SUSPECTED for auto-titles (not run, but the title source is the same string).
* Fix: ASCII slug (`ch.isascii() and ch.isalnum()`) with a `filename*=UTF-8''...` RFC 5987 parameter for the real title. Regression risk: low; existing export tests use ASCII names.

### QA-005: invalid escape sequences in `_like` (P3)
* Evidence (VERIFIED): `shared/conversation_history.py:_like` uses `"\%"` and `"\_"` in normal string literals; compiling the file emits `SyntaxWarning: invalid escape sequence` on Python 3.13 (`test_like_escape_has_no_invalid_escape_warning`). A future Python makes it a `SyntaxError`, which would take the whole history feature down.
* Fix: `"\\%"`, `"\\_"` (or raw strings). Regression risk: none; behaviour is identical.

### QA-006: `GET /api/chat/history` creates a conversation row and binds it to the caller (P3, VERIFIED by probe)
* Evidence: a GET with an unknown `session_id` and `owner_id=attacker` returns 200 and a following chat or history call with `owner_id=victim` for the same session id returns 403 "Conversation belongs to another owner" (probe in scratchpad `qa_probe.py`; also the cause of the order-dependent `ins-ask-bad-id` matrix result). The route is outside the POST-only rate limit, so it can also grow the table.
* Fix: make `load()` read-only for unknown ids. Regression risk: low; the writer path (`begin`) still binds on first message.

## 5. Recommendations (not defects)
* R1 (RECOMMENDATION, high value): run the whole Python suite on every PR. Today it is manual because of trained models. Cache the model artefacts (actions/cache keyed on the training scripts) or publish them as a release asset; add a `models` marker for tests that really need them and run the rest on every PR. Evidence it is cheap: the suite takes 4.6 minutes on this laptop at low priority.
* R2: add `pytest-cov` (or `coverage run -m pytest`) with branch coverage and a floor of 85 % on `api/` and `shared/`; upload the XML as an artefact.
* R3: `ResourceLimits` keys its 120 POST/min bucket on the socket peer. Behind a reverse proxy every user shares one bucket (code comment says forwarded headers are ignored on purpose). Configure the trusted proxy (uvicorn `--proxy-headers --forwarded-allow-ips`) or document that the quota belongs to the proxy.
* R4: run Playwright in CI on PRs touching `web/**` or `api/**`: `npx playwright install --with-deps chromium`, `npm run test:e2e` and `npm run test:accounts` against `scripts/audit_server.py`; keep the existing `SpeechRecognition = undefined` init script as a shared fixture. Run the three-viewport live-meeting tests nightly.
* R5: promote `ARIA_EVALUATION/tests/api` and `/workflow` into `tests/` after the defects are fixed (Phase C), keeping the socket guard fixture as an autouse in `tests/conftest.py`. Today `tests/conftest.py` blanks no provider key and blocks no socket; the repo suite relies on mocks being complete (my one real call above shows an unmocked path can reach Groq).
* R6: add schema-driven fuzzing (`schemathesis` or hypothesis against `app.openapi()` in-process, `raise_server_exceptions=False`, assert no 5xx and no traceback). It would have found QA-001..003 automatically.
* R7: add `oxlint`, `tsc -b` already present, plus `pip-audit` and `npm audit --omit=dev` as non-blocking CI steps; add a weekly scheduled run of the `network`-marked tests so upstream data changes surface.
* R8: add a unit-test runner for `web/src` (vitest) for pure helpers (chat block rendering, API client error mapping); today only browser tests cover the frontend.

## 6. Automation infrastructure delivered and proposed

Delivered (all under `ARIA_EVALUATION/tests/`, re-run with `python -m pytest ARIA_EVALUATION/tests/api ARIA_EVALUATION/tests/workflow -q -p no:cacheprovider` from `E:\ARIA`; about 40 s, set `OMP_NUM_THREADS=2`):
* `api/conftest.py`, `workflow/conftest.py`: reuse `tests/conftest.py` (scratch SQLite, private mode, mock_llm), blank provider keys and `ARIA_SMTP_HOST`, `HF_HUB_OFFLINE=1`, block non-loopback sockets, autouse `mock_llm`.
* `api/test_endpoint_matrix.py`: 165 tests (164 cases + OpenAPI parity check).
* `api/test_conversations_qa.py`: 42 tests. `api/test_authz_accounts.py`: 14 tests. `workflow/test_user_workflows.py`: 5 end-to-end API workflows (profile lifecycle; sample transactions, insights, clear, statement parse and import with cross-owner refusal; chat to history, rename, pin, rate, export, second turn, clear, delete; duplicate `request_id`; account register, profile, logout, 401, wrong and right login).
* Result of the last full run (VERIFIED): `15 failed, 211 passed in 37.9 s`; the 15 failures are exactly the defect tests above (QA-AUTH-001 x5, QA-AUTH-002/003/004, QA-001, QA-002 x2, QA-003 x2, QA-004, QA-005).
* The failing tests are left failing deliberately so the fix PRs can turn them green. If CI should stay green meanwhile, mark them `xfail(strict=True)` with the defect id.

Proposed layering: (1) PR gate, no models: fast unit + API contract + this matrix + a Playwright smoke (about 6 min); (2) nightly: full suite with models, full Playwright at 3 viewports, schemathesis, coverage trend; (3) weekly: `network` tests and the live benchmarks, never on PRs because of free-tier quotas.

## 7. Not tested, and why
* Any real LLM, STT, TTS, FinBERT or embedding behaviour: forbidden/blocked (benchmark is using the quota). Chat quality, citation grounding and latency are for the AI/RAG audit.
* All `net=True` endpoints (Yahoo, AMFI, news RSS) and the `network` tests: no network allowed.
* Live instance run of `run_matrix.py` (headers, real HTTP framing, CORS preflight, static mount, real 12 MB body limits over a socket): no server was started; in-process only. The 12 MB limit was exercised in-process through the ASGI middleware.
* Browser/Playwright, mobile viewports, accessibility, microphone paths: no browser per the constraints; Playwright coverage is described from source only.
* Google sign-in end to end, SMTP delivery: need the network / real credentials.
* Concurrency and load (parallel writers on SQLite, `max_active` 503 path under real load), and Postgres (only SQLite scratch DBs used).
* Branch coverage, mutation testing: not measured.
* Body-`owner_id` bypass on `/api/quiz/answer`, `/api/instruments/ask`, `/api/research/reports/*/regenerate`, `/api/transactions/import`: same root cause as QA-AUTH-001, not individually exercised.
* The earlier-listed environment problem: the first combined test run that included the unguarded real `hello` chat call hung for more than 10 minutes and was killed; with the guards in place the same files run in under 40 s. Cause not isolated (SUSPECTED: waiting on the blocked LLM/TTS network path).
