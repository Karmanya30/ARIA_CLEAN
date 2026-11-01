# Dependency inventory

## Python runtime (requirements.txt, pinned)

- numpy==2.3.1
- scipy==1.16.0
- scikit-learn==1.7.1
- xgboost==3.2.0
- lightgbm==4.6.0
- shap==0.52.0
- torch==2.13.0
- faiss-cpu==1.14.3
- sentence-transformers==5.6.1
- sqlalchemy==2.0.49
- pyarrow==24.0.0
- pydantic==2.13.0
- gymnasium==1.3.0
- stable-baselines3==2.9.0
- groq==1.2.0
- google-genai==2.11.0
- google-auth[requests]==2.56.3  # server-side Google ID-token verification
- cryptography==50.0.0  # RSA verification; local test certificates use the same verifier
- python-dotenv==1.2.2
- yfinance==1.7.0
- requests==2.34.2
- beautifulsoup4==4.14.3
- openai-whisper==20250625
- imageio-ffmpeg==0.6.0
- edge-tts==7.2.8
- piper-tts==1.8.0  # Live Avatar voice (local, free); voice files: python -m ai.speech.live_tts --download
- pyttsx3==2.99
- loguru==0.7.3
- fastapi==0.143.2
- uvicorn==0.34.0
- pyngrok==7.2.3
- python-multipart==0.0.31
- pypdf==6.19.0
- openpyxl==3.1.5
- xlrd==2.0.2  # reads legacy .xls statements (BSD)
- symspellpy==6.10.0  # query spelling correction for routing (MIT); bundles the English frequency dictionary
- editdistpy==0.4.0  # symspellpy edit distance (MIT)

Security constraints: requirements-security.txt. Dev: requirements-dev.txt.

## Web (web/package.json)

**dependencies**: @fontsource/manrope ^5.3.0, @fontsource/sora ^5.3.0, lightweight-charts ^5.2.1, lucide-react ^1.33.0, react ^19.2.8, react-dom ^19.2.8, react-markdown ^10.1.0
**devDependencies**: @playwright/test ^1.64.1, @types/node ^24.13.3, @types/react ^19.2.17, @types/react-dom ^19.2.3, @vitejs/plugin-react ^6.0.4, oxlint ^1.75.0, typescript ~6.0.2, vite ^8.2.0

## Environment variables read by the code (names only, never values)

| Variable | In .env.example | Read in |
|---|---|---|
| `ARIA_APP_ORIGIN` | yes | api/auth.py |
| `ARIA_AUDIT_GOOGLE` | NO | scripts/audit_server.py |
| `ARIA_AUDIT_PORT` | NO | scripts/audit_server.py |
| `ARIA_AUDIT_RUN` | NO | scripts/audit_server.py |
| `ARIA_AUTH_ALLOW_SIGNUP` | yes | api/auth.py |
| `ARIA_AUTH_MODE` | yes | api/auth.py, modules/equity_research/intelligence/pipeline.py, shared/user_store.py |
| `ARIA_BIND_HOST` | yes | api/main.py |
| `ARIA_CONTEXT_DEBUG` | yes | api/routes/chat.py |
| `ARIA_EXPENSIVE_REQUESTS_PER_MINUTE` | yes | api/resource_limits.py |
| `ARIA_FINBERT_DIR` | NO | modules/equity_research/intelligence/sentiment.py |
| `ARIA_FORECAST` | NO | modules/equity_research/intelligence/pipeline.py |
| `ARIA_FORECAST_DEVICE` | NO | modules/equity_research/forecast/jobs.py, modules/equity_research/forecast/models.py, scripts/validate_forecasts.py |
| `ARIA_FORECAST_MODE` | NO | modules/equity_research/forecast/jobs.py |
| `ARIA_INTENT_MIN_CONFIDENCE` | yes | shared/intent_resolver.py |
| `ARIA_INTENT_RESOLVER` | yes | shared/intent_resolver.py |
| `ARIA_INTENT_TIMEOUT_SECONDS` | yes | shared/intent_resolver.py |
| `ARIA_MAX_ACTIVE_REQUESTS` | yes | api/resource_limits.py |
| `ARIA_MAX_REQUEST_BYTES` | yes | api/resource_limits.py |
| `ARIA_MEMORY_SEMANTIC` | yes | scripts/evaluate_context_memory.py, shared/conversation_memory.py |
| `ARIA_MEMORY_SEMANTIC_CANDIDATES` | yes | shared/conversation_memory.py |
| `ARIA_MEMORY_TOKEN_BUDGET` | yes | shared/conversation_memory.py |
| `ARIA_MODEL_CONTEXT_TOKENS` | yes | shared/conversation_memory.py |
| `ARIA_OUTPUT_GUARD_TIMEOUT_S` | NO | core/orchestrator.py |
| `ARIA_PDF_BROWSER` | NO | modules/equity_research/intelligence/report_pdf.py |
| `ARIA_REQUEST_LEASE_SECONDS` | yes | shared/conversation_memory.py |
| `ARIA_RESPONSE_RESERVE_TOKENS` | yes | shared/conversation_memory.py |
| `ARIA_SCENARIO_BACKTEST` | NO | modules/equity_research/intelligence/pipeline.py |
| `ARIA_SENTIMENT` | NO | modules/equity_research/intelligence/sentiment.py |
| `ARIA_SERVE_WEB` | NO | api/main.py |
| `ARIA_TOKENIZER_PATH` | yes | shared/conversation_memory.py |
| `ARIA_WARMUP` | NO | api/main.py |
| `ARIA_WEB_SEARCH` | yes | shared/websearch.py |
| `DB_URL` | NO | config/settings.py, scripts/audit_server.py, shared/user_store.py |
| `DEBATE_GROQ_BEAR` | NO | modules/equity_research/intelligence/agents.py |
| `DEBATE_GROQ_BULL` | NO | modules/equity_research/intelligence/agents.py |
| `DOMAIN_GUARD_CONFIDENCE_THRESHOLD` | NO | shared/domain_guard.py |
| `DOMAIN_GUARD_ENABLED` | NO | shared/domain_guard.py |
| `DOMAIN_GUARD_MODEL` | NO | shared/domain_guard.py |
| `DOMAIN_GUARD_OUTPUT_CHECK` | NO | shared/domain_guard.py |
| `FALLBACK_GROQ_MODEL` | NO | ai/llm/groq_client.py |
| `FFMPEG_DIR` | NO | config/settings.py |
| `FFMPEG_PATH` | NO | config/settings.py |
| `FI_EQUITY_RISK_PREMIUM` | yes | config/settings.py |
| `FI_RISK_FREE_RATE` | yes | config/settings.py |
| `FI_TERMINAL_GROWTH` | yes | config/settings.py |
| `GEMINI_API_KEY` | yes | ai/llm/groq_client.py, config/settings.py |
| `GEMINI_MODEL_NAME` | yes | ai/llm/groq_client.py, config/settings.py |
| `GOOGLE_CLIENT_ID` | yes | api/auth.py, scripts/audit_server.py |
| `GROQ_API_KEY` | yes | ai/llm/groq_client.py, config/settings.py |
| `LIVE_TTS_VOICE` | NO | ai/speech/live_tts.py |
| `LOG_LEVEL` | NO | config/settings.py |
| `MODEL_NAME` | yes | ai/llm/groq_client.py, config/settings.py |
| `MUSETALK_DIR` | NO | scripts/musetalk_server.py |
| `NGROK_AUTHTOKEN` | yes | api/routes/avatar.py |
| `N_CONCEPTS` | NO | config/settings.py |
| `PATH` | NO | ai/speech/stt.py |
| `PROJECT_NAME` | NO | config/settings.py |
| `RETRIEVAL_K` | NO | config/settings.py |
| `RETRIEVAL_THRESHOLD` | NO | config/settings.py |
| `SBERT_DEVICE` | NO | config/settings.py |
| `SBERT_MODEL` | NO | config/settings.py |
| `SECOND_FALLBACK_GROQ_MODEL` | NO | ai/llm/groq_client.py |
| `TAVUS_API_KEY` | yes | api/routes/avatar.py |
| `TAVUS_REPLICA_ID` | yes | api/routes/avatar.py |
| `TTS_RATE` | NO | config/settings.py |
| `TTS_TIMEOUT_SECONDS` | NO | config/settings.py |
| `TTS_VOICE` | NO | ai/speech/live_tts.py, config/settings.py |
| `WHISPER_DEVICE` | NO | config/settings.py |
| `WHISPER_MODEL` | NO | config/settings.py |

## External services

Groq (LLM), Gemini (LLM fallback), Yahoo Finance, Screener.in, AMFI, mfapi.in, CoinGecko, FRED, NSE/BSE listings, 84 RSS feeds, DuckDuckGo/Bing (web-search fallback), Tavus (optional), ngrok (optional), Google sign-in (optional).