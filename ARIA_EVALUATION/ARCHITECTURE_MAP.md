# ARIA architecture map

## End-to-end flow

```mermaid
flowchart TD
  U[User browser: React app, 4 chat modes, Explore, Markets, Research, Progress, Profile] -->|/api/*| API[FastAPI api/main.py: ResourceLimits, CORS, auth.authorize]
  U -->|WebSocket /api/live/ws| LIVE[api/routes/live.py]
  API --> CHAT[api/routes/chat.py] --> QA[modules/qa/pipeline.py]
  LIVE --> QA
  QA --> UND[understand: spelling, Hinglish, crisis, small talk - shared/understand.py, human_state.py]
  UND --> CTX[context: conversation memory, profile, focus - shared/conversation_memory.py, modules/qa/focus.py]
  CTX --> ORC[core/orchestrator.py routing]
  ORC -->|quiz / concept| TUT[modules/tutor: retriever SBERT+FAISS, DKT, DQN, quiz]
  ORC -->|data question, unlisted name| LK[modules/qa/lookup.py] --> INST[modules/market/instruments catalogue] --> SCR[Screener.in statements]
  LK -->|not found| WEB[shared/websearch.py DuckDuckGo/Bing]
  ORC -->|fundamentals, research, intelligence| EQ[modules/equity_research: financial_pipeline, intelligence, forecast, scenario_backtest]
  ORC -->|market-wide| MK[modules/market: analyzer, live, news]
  ORC -->|personal finance| FIN[modules/finance: engine, tax, sip_emi, risk XGBoost, spend LSTM, statement import]
  ORC -->|everything else| GEN[general model reply]
  TUT & LK & EQ & MK & FIN & GEN --> LLM[ai/llm/groq_client.py: Groq then Gemini fallback]
  QA --> TR[ground and trust: modules/qa/trust.py strips figures not in fetched data, adds disclaimers]
  TR --> PS[persist: SQLite via shared/user_store.py, chat turns, memory]
  PS --> PR[present: spoken rewrite + audio clip - modules/qa/present.py, ai/speech]
```

## Module dependency layers (imports run downward)

```
web/src (components, v1/, v2/, api.ts)
   |  HTTP / WebSocket
api/routes/*  ->  api/auth.py, api/resource_limits.py, api/audio_store.py
   |
modules/qa  (pipeline, lookup, focus, trust, present)
   |
core/orchestrator, core/router, core/session
   |
modules/{tutor, finance, market, equity_research}   shared/{company_resolver, news, websearch, understand, intent_*, conversation_memory, vector_store, user_store}
   |
ai/llm (groq_client, prompt_templates, spoken)   ai/speech (stt Whisper, live_tts Piper/Edge)   config/{settings, paths}
   |
External: Groq, Gemini, Yahoo, Screener.in, AMFI, mfapi, CoinGecko, FRED, NSE/BSE, RSS feeds, DuckDuckGo/Bing, Tavus, Google sign-in
Storage: SQLite (chat, profile, transactions, learning, reports, audio, auth) + data/ caches + models/ (rebuilt by training scripts)
```

## Offline / batch pipelines

`scripts/scenario_backtest_universe.py` (resumable sweep over ~4,600 NSE/BSE companies, results in `data/scenario_backtest`), `scripts/scenario_report_validation.py` (report-level validation, robustness), `scripts/make_summary_pdf.py`, `scripts/validate_universe.py` (price-forecast sweep), training scripts for the finance and tutor models.

## Runtime shapes

Private mode (default, no login, client-supplied owner id), accounts mode (cookie sessions, optional Google), Docker (API serves the built web app on port 8000), development (Vite on 5173 proxying to 8000).
