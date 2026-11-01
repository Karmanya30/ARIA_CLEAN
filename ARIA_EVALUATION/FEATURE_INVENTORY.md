# Feature inventory and traceability matrix

Test column: existing automated coverage found by file name and earlier runs; real coverage percentages come from the QA agent (reports/TEST_COVERAGE_REPORT.md). "E2E" = Playwright spec in `web/e2e`.

| # | Feature | Implementation | Dependencies | Inputs -> outputs | Existing tests |
|---|---|---|---|---|---|
| 1 | One answer pipeline for every channel | modules/qa/pipeline.py, present.py | orchestrator, trust, user_store | question + mode/channel -> answer, grounding tag, audio | tests/qa/test_unified_pipeline.py |
| 2 | Query understanding (typos, Hinglish, text-speak, crisis, small talk) | shared/understand.py, human_state.py, dialogue.py | symspell, SBERT | text -> normalised text, tone plan | test_understand.py, test_human_state.py, test_dialogue.py |
| 3 | Intent routing | core/router.py, orchestrator.py, shared/intent_classifier.py, intent_resolver.py | LLM (resolver, optional) | text -> module | test_router.py, test_intent_*.py, tests/intent_evaluation_cases.json |
| 4 | Conversation memory | shared/conversation_memory.py, vector_store.py | SBERT, SQLite | turns -> relevant context | test_conversation_memory.py |
| 5 | Grounding / no invented numbers | modules/qa/trust.py | fetched evidence | answer text -> redacted text + tag | tests/qa/test_trust.py, test_lookup.py |
| 6 | Data lookup for any listed name; web-search fallback | modules/qa/lookup.py, shared/websearch.py | instruments catalogue, Screener, DDG/Bing | name + metric -> facts-based answer | tests/qa/test_lookup.py |
| 7 | Instrument catalogue, quotes, charts, profile, SIP simulation, ask | modules/market/instruments.py, instrument_chat.py | Yahoo, AMFI, mfapi, CoinGecko, FRED | id -> quote/chart/stats | tests/market/test_instruments.py, E2E explore |
| 8 | Markets dashboard, news, movers, sectors | modules/market/live.py, analyzer.py, shared/news.py | Yahoo, 84 RSS feeds | - -> snapshots | test_markets_live.py, test_news.py, E2E |
| 9 | Fundamentals Q&A and company comparison | modules/equity_research/financial_pipeline.py, screener_adapter.py, data_normalizer.py | Screener.in | company + metric -> figures | tests/equity_research |
| 10 | Research report (valuation, scenarios, debate, audit, PDF/HTML) | modules/equity_research/intelligence/* | Yahoo, Screener, news, LLM | company -> report | tests/equity_research, E2E |
| 11 | Company intelligence score, sentiment (FinBERT) | intelligence/lenses.py, sentiment.py | FinBERT weights (optional) | company / text -> score, tone | test_api_intelligence.py |
| 12 | Price forecast validation engine | equity_research/forecast/* | Yahoo prices | symbol -> validated forecast or refusal | tests/forecast (185) |
| 13 | Historical scenario backtest + report-level validation | equity_research/scenario_backtest/*, scripts | Screener, Yahoo | universe -> accuracy tables | tests/equity_research |
| 14 | Personal finance engine (snapshot, health score, goals, retirement, tax compare, SIP affordability, what-if) | modules/finance/engine.py, tax.py, sip_emi_calc.py | profile | profile -> numbers | tests/finance |
| 15 | Risk profile (XGBoost), spend forecast (LSTM), anomaly, budget optimiser | finance/risk_model.py, forecast_model.py, anomaly.py, budget_optimize.py | trained models (rebuilt) | transactions -> flags/forecast | tests/finance |
| 16 | Transactions: manual, sample, statement import (CSV/XLSX/PDF) | api/routes/transactions.py, finance/statement_import.py, shared/statement_store.py | pypdf, openpyxl | file -> rows | tests/finance, test_audit_regressions.py |
| 17 | Profile form and summary | api/routes/profile.py, finance/schemas.py | - | form -> profile | tests/finance, E2E |
| 18 | Tutor: concept explanation (TAXAL), quiz, mastery, Progress | modules/tutor/*, api/routes/progress.py | SBERT+FAISS, DKT LSTM, DQN | question -> lesson + quiz | tests/tutor, test_api_progress.py, tests/tutor/test_quiz_requests.py |
| 19 | Chat modes: Normal, Conversational voice disk, Live Avatar (Free), Tavus | web/src/components/chat, api/routes/live.py, avatar.py, interface/avatar | Piper/Edge TTS, Whisper, MuseTalk (GPU), Tavus API | speech/text -> speech | test_live_avatar.py, test_api_avatar.py, test_tavus_recovery.py, E2E voice-toggle |
| 20 | Speech to text, audio clips | api/routes/voice.py, ai/speech/stt.py, api/audio_store.py | Whisper, ffmpeg | audio -> text; token -> wav | test_audio_persistence.py |
| 21 | Accounts (email, Google), session security | api/auth.py, shared/user_store.py | cryptography, google-auth | credentials -> cookie | test_accounts.py, E2E accounts |
| 22 | Resource limits, request leases | api/resource_limits.py, conversation_memory | - | requests -> 413/429 | test_resource_limits.py |
| 23 | Report library and exports | web research tab, api/routes/research.py | reportlab-like PDF module | report id -> HTML/PDF/MD | E2E |
| 24 | Themes, UI versions, disclaimers | web/src/theme.ts, DisclaimersPage | - | - | E2E |
| 25 | Deployment (Docker, compose, CI web job) | Dockerfile, docker-compose.yml, .github/workflows/ci.yml, docs/DEPLOYMENT.md | Docker | - | web CI job passed; image never built |

## Features users would expect but that are absent (to be confirmed by the product and quant agents)

LBO and DDM valuation, bond pricing/duration, derivatives, portfolio-level analytics (holdings upload, correlation, portfolio volatility), real-estate rent-vs-buy and rental yield engine, goal-based planning wizard beyond the profile form, price alerts, export of chat, multi-language UI.
