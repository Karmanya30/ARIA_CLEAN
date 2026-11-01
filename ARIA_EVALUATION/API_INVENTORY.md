# API inventory

Generated from the live FastAPI schema (`app.openapi()`), 71 operations. `*` marks a required query parameter.

| Method | Path | Parameters | Body | Router file |
|---|---|---|---|---|
| GET | `/api/audio/{token}` | token* |  | voice.py |
| POST | `/api/auth/google` |  | GoogleCredential | api/main.py or other |
| POST | `/api/auth/google/link` |  | GoogleCredential | api/main.py or other |
| POST | `/api/auth/login` |  | Credentials | api/main.py or other |
| POST | `/api/auth/logout` |  |  | api/main.py or other |
| POST | `/api/auth/logout-all` |  |  | api/main.py or other |
| POST | `/api/auth/register` |  | Credentials | api/main.py or other |
| GET | `/api/auth/session` |  |  | api/main.py or other |
| POST | `/api/chat` |  | ChatRequest | chat.py |
| POST | `/api/chat/clear` |  | application/json | chat.py |
| GET | `/api/chat/context` | session_id*, query*, owner_id |  | chat.py |
| GET | `/api/chat/history` | session_id*, owner_id |  | chat.py |
| GET | `/api/health` |  |  | api/main.py or other |
| POST | `/api/instruments/ask` |  | AskRequest | instruments.py |
| GET | `/api/instruments/browse` | type, q, sort, page, page_size, amc, category, plan, option, prices |  | instruments.py |
| GET | `/api/instruments/search` | q, type, limit, market |  | instruments.py |
| GET | `/api/instruments/{instrument_id}/chart` | instrument_id*, range |  | instruments.py |
| GET | `/api/instruments/{instrument_id}/profile` | instrument_id* |  | instruments.py |
| GET | `/api/instruments/{instrument_id}/quote` | instrument_id* |  | instruments.py |
| GET | `/api/instruments/{instrument_id}/sip` | instrument_id*, monthly, years |  | instruments.py |
| GET | `/api/markets/chart` | symbol*, range |  | markets.py |
| GET | `/api/markets/movers` |  |  | markets.py |
| GET | `/api/markets/news` |  |  | markets.py |
| GET | `/api/markets/overview` |  |  | markets.py |
| GET | `/api/markets/quote` | symbol* |  | markets.py |
| GET | `/api/markets/search` | q* |  | markets.py |
| GET | `/api/markets/sectors` |  |  | markets.py |
| GET | `/api/profile` | session_id* |  | profile.py |
| POST | `/api/profile` |  | ProfileRequest | profile.py |
| DELETE | `/api/profile` | session_id* |  | profile.py |
| DELETE | `/api/profile/style` | session_id* |  | profile.py |
| GET | `/api/profile/summary` | session_id* |  | profile.py |
| GET | `/api/progress` | session_id* |  | progress.py |
| POST | `/api/quiz/answer` |  | QuizAnswerRequest | progress.py |
| GET | `/api/research/intelligence` | q*, owner_id |  | research.py |
| GET | `/api/research/reports` | owner_id*, symbol |  | research.py |
| GET | `/api/research/reports/{report_id}` | report_id*, owner_id* |  | research.py |
| DELETE | `/api/research/reports/{report_id}` | report_id*, owner_id* |  | research.py |
| GET | `/api/research/reports/{report_id}/download` | report_id*, owner_id*, format, kind |  | research.py |
| GET | `/api/research/reports/{report_id}/html` | report_id*, owner_id*, kind, print |  | research.py |
| POST | `/api/research/reports/{report_id}/regenerate` | report_id* | OwnerRequest | research.py |
| POST | `/api/research/scenario-backtest` |  | api__routes__scenario_backtest__StartRequest | scenario_backtest.py |
| POST | `/api/research/scenario-backtest/` |  | api__routes__scenario_backtest__StartRequest | scenario_backtest.py |
| GET | `/api/research/scenario-backtest/universe/summary` |  |  | scenario_backtest.py |
| GET | `/api/research/scenario-backtest/{symbol}` | symbol*, forecasts |  | scenario_backtest.py |
| POST | `/api/research/sentiment` |  | SentimentRequest | research.py |
| POST | `/api/research/validation` |  | api__routes__forecast__StartRequest | forecast.py |
| POST | `/api/research/validation/` |  | api__routes__forecast__StartRequest | forecast.py |
| GET | `/api/research/validation/latest` | symbol* |  | forecast.py |
| GET | `/api/research/validation/universe/summary` |  |  | forecast.py |
| GET | `/api/research/validation/universe/{symbol}` | symbol* |  | forecast.py |
| GET | `/api/research/validation/{run_id}` | run_id* |  | forecast.py |
| POST | `/api/research/validation/{run_id}/cancel` | run_id* |  | forecast.py |
| POST | `/api/tavus/end` |  | application/json | avatar.py |
| POST | `/api/tavus/start` | port | TavusStartRequest | avatar.py |
| GET | `/api/transactions` | session_id* |  | transactions.py |
| POST | `/api/transactions` |  | TransactionRequest | transactions.py |
| DELETE | `/api/transactions` | session_id* |  | transactions.py |
| POST | `/api/transactions/import` |  | ImportRequest | transactions.py |
| GET | `/api/transactions/insights` | session_id* |  | transactions.py |
| POST | `/api/transactions/parse` |  | Body_parse_statement_file_api_transactions_parse_post | transactions.py |
| POST | `/api/transactions/sample` |  | SampleRequest | transactions.py |
| POST | `/api/voice/transcribe` |  | Body_transcribe_audio_api_voice_transcribe_post | voice.py |
| GET | `/avatar/face.png` |  |  | live.py |
| GET | `/avatar/glasses.png` |  |  | live.py |
| GET | `/avatar/live` |  |  | live.py |
| GET | `/avatar/model.glb` |  |  | live.py |
| GET | `/avatar/render` | audio_token |  | avatar.py |
| GET | `/embed` | conversation_url* |  | avatar.py |
| POST | `/v1/{session_id}/chat/completions` | session_id*, owner_id | ChatCompletionRequest | avatar.py |
| POST | `/v1/{session_id}/owner/{owner_id}/chat/completions` | session_id*, owner_id* | ChatCompletionRequest | avatar.py |

Not in the OpenAPI schema: `WebSocket /api/live/ws` (api/routes/live.py), the static web app mounted at `/` when `web/dist` exists, and `/avatar/*` assets.

Authorization is an app-wide dependency (`auth.authorize`): see reports/ACCOUNT_AUTHENTICATION.md and the security audit for how private and accounts modes differ.