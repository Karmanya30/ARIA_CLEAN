# One question pipeline

Goal: every question asked anywhere in ARIA goes through the same pipeline, `modules/qa/pipeline.py: answer()`.
Endpoints are thin adapters; the chat *mode* and the *channel* only change presentation.

## 1. Map before the change (what existed)

Every place a user question or utterance was answered, or an LLM answer was generated for a user:

| Entry point | Input | Understanding | Answered by | Context attached | Persistence | Trust / disclaimer | Errors | Mode difference |
|---|---|---|---|---|---|---|---|---|
| `POST /api/chat` (5 modes) | `query`, `session_id`, `mode`, `owner_id`, `correct`, `adapt_tone` | `shared.understand.normalize` (typo / text-speak / Hinglish), crisis check, dialogue acts, small talk, intent resolver, keyword router | `core.orchestrator.handle_query` -> finance / tutor / market / equity research / company intelligence / general | session memory (`conversation_memory.context_for`), finance profile, tone profile, live news for time-sensitive questions | `core.session.execute_turn` + `save_turn` (per owner, replay by `request_id`) | output guard (LLM domain check) only; no disclaimer text; no number check | module-specific; raw `Error: ...` strings could reach the user | `mode` ignored except `"Live Avatar"` skipped the output guard; TTS clip made for every mode in the adapter |
| `POST /api/chat` with `system_context` (news chip) | same + a news preamble | only the crisis check; the router, normaliser, dialogue acts were **bypassed** | direct `generate_response` with a private prompt | memory `augment` | `execute_turn` | none | "I'm sorry, I couldn't generate..." | none |
| `GET /api/chat/history`, `/context`, `POST /clear` | session, owner | n/a | n/a (read / clear; clear also ends Tavus) | n/a | n/a | n/a | 403 on a foreign owner | none |
| `POST /api/instruments/ask` | `id`, `question`, `session_id`, `history` | **none** (no normaliser, no crisis, no small talk, no tone) | `modules/market/instrument_chat.ask`: its own prompt, facts from quote / profile / SIP / saved report / news | the instrument facts, client `history` (last 3 turns) | `execute_turn` + `save_turn`, session `"<chat session>:<instrument>"` | **the only place with the invented-numbers guard**, facts-only fallback, "This is not investment advice." | model dead -> facts-only summary | none |
| Live Avatar (Free) `WS /api/live/ws` | `text`, `session_id`, `owner_id` | small talk: none; else the orchestrator | small talk: **its own system prompt streamed from the LLM**; else `handle_query(mode="Live Avatar")` then a streamed spoken rewrite; on failure a **direct ungrounded LLM stream** | memory `augment` | manual `memory.begin/complete`; the saved response was the *spoken* text with domain `live_avatar` | none | `TROUBLE` apology | spoken style, fillers, no output guard |
| Tavus CVI `POST /v1/{sid}[/owner/{oid}]/chat/completions` | OpenAI-style messages | the orchestrator | `handle_query(mode="Normal Mode")` + `spoken_version` | memory | `save_turn` inside the orchestrator | none | fixed apology | spoken style |
| `GET /api/research/intelligence?q=` | `q`, `owner_id` | none (raw `q` to the company resolver) | `company_intelligence` (no model) | owner (saved reports) | none | none | 404 | none |
| `POST /api/research/reports/{id}/regenerate`, report generation inside chat | report id / company | n/a | `run_research` (LLM agents, own validators and ledger) | owner | saved report versions | report DISCLAIMER and strip inside the report | 502 | none |
| `POST /api/voice/transcribe` | audio | speech-to-text only; the text is then sent through `/api/chat` or the live socket | `ai.speech.stt` | n/a | n/a | n/a | 502 | n/a |
| `GET /api/markets/*` | none | no LLM | snapshots / yfinance | n/a | n/a | n/a | stale flag | n/a |
| Market chips ("Why is the market moving today?") | text | go to the Chat tab, then `/api/chat` | as `/api/chat` | | | | | |
| News modal questions (`NewsFeed`) | headline + question | in v1 / v2 the headline was **pasted into the question text**; the root copy used `system_context` | see `system_context` row | | | | | |
| Profile / progress / transactions / forecast / scenario endpoints | forms, files | no free-text question, no LLM answer | engines (XGBoost, LSTM, DQN ...) | n/a | n/a | n/a | n/a | n/a |

Downstream, inside the orchestrator's modules, the model is called by: finance narration (`modules/finance/pipeline.py`, `orchestrator.py`),
tutor (`explainer.py`, `quiz.py`, `pipeline.py`), market (`modules/market/pipeline.py`), equity research (`investment.py`,
`financial_pipeline.py`, `intelligence/agents.py`), small talk / support / general (`core/orchestrator.py`), domain guard
(`shared/domain_guard.py`), intent resolver, spoken rewrite and audio script. They are all reached *through* the entry points above,
and all call `ai.llm.groq_client.generate_response` (Groq -> Gemini -> two smaller Groq models, one retry on 429 / 503), which is where
retries, timeouts and the dead-backend cool-down live.

Front end call sites: `web/src/api.ts` (and the copies in `versions/v1`, `versions/v2`): `sendMessage` (Chat tab, news modal),
`askInstrument` (Explore drawer "Ask ARIA"), `companyIntel`; the Live Avatar page `interface/avatar/live.html`
and the Tavus embed talk to the WebSocket / callback directly.

## 2. After the change

```
                  POST /api/chat (5 modes, chips, any context)      POST /api/instruments/ask
                  WS /api/live/ws          POST /v1/{sid}/chat/completions (Tavus)
                  GET /api/research/intelligence  ──(lookup)──┐
                                    │                          │
                                    ▼                          ▼
                       QARequest(query, mode, channel, session_id, owner_id, context, ...)
                                    │
        modules/qa/pipeline.py  answer()
          1 understand   normalise (spelling / text-speak / Hinglish), kept for display / history
          2 context      owner + conversation memory, finance profile, focus (instrument / news item / company / report), market snapshot
          3 answer       core.orchestrator.handle_query: crisis -> dialogue acts -> small talk -> intent -> module;
                         with a focus: modules/qa/focus.py facts-bound answer (same crisis / small talk / tone / persistence)
          4 ground       modules/qa/trust.py: numbers must be in the fetched data; degraded replies, never raw errors
          5 trust        one "not investment advice" line, one accuracy caveat, trust tags (`trust`, `grounding`, `qa`)
          6 persist      core.session.execute_turn: per owner and session, replay by request_id
          7 present      modules/qa/present.py: spoken rewrite for the avatar modes, background audio clip
          log            one line per answer: `qa.answer channel=.. mode=.. route=.. stages={..} total_ms=..`
```

Files:

* `modules/qa/models.py` - `ChatMode` (the four mode strings, one enum), `Channel`, `QAContext`, `QARequest`, `QAResponse` (ChatResponse-compatible, extra fields allowed), `Focus`.
* `modules/qa/pipeline.py` - `answer(req)`; `lookup(req, fetch)` for the deterministic company-intelligence endpoint; `understand()`.
* `modules/qa/focus.py` - context providers and the single grounded answer loop (`grounded_answer`) used by the instrument drawer and the news item chips.
* `modules/qa/trust.py` - `ungrounded()`, `enforce()` (invented-numbers guard for every fetched-data route), `finalize()` (disclaimer, accuracy caveat, tags), `DEGRADED`.
* `modules/qa/present.py` - the only place a mode matters.
* `core/orchestrator.py` - reads the focus (`active_focus`), uses it for instruments / news items, resolves "it" for a company page, runs the output guard for every mode with a bounded wait.
* adapters: `api/routes/chat.py` (`answer_http`), `instruments.py`, `live.py`, `avatar.py`, `research.py`.
* front end: `api.ask({query, sessionId, mode, channel, context, history})` in `web/src/api.ts` and the v1 / v2 copies; `sendMessage` and `askInstrument` are wrappers over it.
* `modules/market/instrument_chat.py` is now only the instrument *facts provider* (`gather`, `direct_answer`, `plain_summary`); its prompt, retry loop and disclaimer logic moved into the shared modules.

Rules every channel now gets:

| Concern | Rule (same everywhere) |
|---|---|
| Understanding | `shared.understand.normalize` (never alters amounts), crisis -> fixed care reply, dialogue acts and small talk handled before any module, `correct=false` = as typed |
| Context | owner-scoped conversation memory, finance profile, tone, the focus (instrument / news item / company / report), live news and the market snapshot when loaded; client `history` only when the server has none |
| Grounding | instrument and news-item answers: numbers must come from the facts (one retry naming the offenders, then a facts-only summary); market / live-quote / fundamentals answers: a sentence holding a number that is in no fetched data is replaced by a plain notice; personal-finance tool answers are tagged only (their inputs are the user's own figures); unavailable data is stated, never guessed |
| Disclaimer | "This is not investment advice." appended to advice-like domains (instrument, news, market, investment, equity research, finance tools); the accuracy caveat is appended when valuation, score, target or forecast language or a report is involved; both strings are also in `trust` on every response |
| Safety | output guard runs for every mode (bounded wait `ARIA_OUTPUT_GUARD_TIMEOUT_S`, default 3 s), skipped when no model text is involved |
| Errors | raw `Error: ...` text is replaced by `trust.DEGRADED`; an unknown instrument is a 404, a foreign conversation 403, a reused `request_id` for another message 409 |
| Retries, timeouts, cache | one LLM chain (`generate_response`: Groq -> Gemini -> two smaller Groq models, one retry on 429 / 503); the instrument and company caches in `modules/market/instruments.py` and `shared/news.py` apply to all channels |
| Metrics | `qa.answer` log line + `response.qa.latency_ms` (`understand_ms`, `answer_ms`, `trust_ms`, `total_ms`) |
| Mode | `Normal`, `Conversational`: written answer + background audio clip; `Live Avatar`, `Tavus`: additionally a server-made `spoken` version; the written `response` is identical in all five |

## 3. Entry points: before / after

| Entry point | Before | After |
|---|---|---|
| `POST /api/chat`, all 5 modes | orchestrator, mode ignored (except one skip) | `pipeline.answer`, channel `chat`, mode in `ChatMode` |
| `POST /api/chat` + `system_context` / `context.headline` | bypassed router and normaliser, private prompt | `pipeline.answer`, channel `market_chip`, same understanding / persistence, headline as untrusted facts, number guard |
| `POST /api/chat` + `context.instrument_id` | n/a | same as `/api/instruments/ask` |
| `POST /api/chat` + `context.company` / `report_id` | n/a | resolves "it" / "this company" for the page in focus |
| `POST /api/instruments/ask` | own prompt and guard, no normalisation | adapter: `pipeline.answer`, channel `instrument`, focus `instrument_id` |
| `WS /api/live/ws` | own small-talk prompt, own persistence, ungrounded fallback | adapter: `pipeline.answer` (mode Live, channel avatar); fillers and chunking only |
| Tavus callback | orchestrator + spoken rewrite | adapter: `pipeline.answer` (mode Tavus, channel avatar), reads `spoken` |
| `GET /api/research/intelligence` | raw `q`, no tags | `pipeline.lookup` (normalised `q`, owner scope, trust tags, log line) |
| Report regenerate / generation | `run_research` | unchanged (report engine with its own audit); reached from chat through the pipeline |
| Front end | `sendMessage`, `askInstrument`, hand-built news preambles | `api.ask(...)` (all three trees), news item as `context.headline` |
