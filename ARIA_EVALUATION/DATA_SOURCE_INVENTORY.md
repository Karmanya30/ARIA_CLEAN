# Data source inventory

Health column = state observed on 26 Oct 2026 (`scripts/audit_connections.py` and direct probes); the performance and AI agents re-measure latency and freshness.

| Source | Type | Used by | Access method | Freshness / limits | Risk | Health 26 Oct |
|---|---|---|---|---|---|---|
| Yahoo Finance (yfinance + chart API) | prices, history, fundamentals fallback, symbol search | quotes, charts, lookup, forecast, backtest | unofficial library / endpoints | ~15 min delay; no SLA; rate limits | terms of use, breakage | OK |
| Screener.in | yearly statements, ratios, shareholding | fundamentals, comparison, reports, backtest | HTML scraping, 20 s timeout, 2 concurrent in sweeps | company-dependent staleness (one consolidated page ended in 2015) | terms of use, layout changes | OK |
| AMFI NAVAll.txt + mfapi.in | mutual fund NAV and history | Explore, lookup | public file / API | daily NAV | low | OK |
| CoinGecko | crypto market data | Explore, lookup | public API | rate limited | low | OK |
| FRED (INDIRLTLT01STM) | India 10-year yield | Explore | CSV | monthly | slow responses | one 15 s timeout, then OK |
| NSE EQUITY_L / Nifty 500 list, BSE bhavcopy | listings universe | catalogue, sweeps | public CSV | daily | BSE list API blocked (bhavcopy fallback used) | OK |
| 84 RSS feeds (ET, Mint, BS, Hindu BL, CNBC, BBC, Reuters-style, RBI, Fed...) | news headlines | news tab, grounding context, intelligence | RSS, 5 s timeout, 10 min cache | minutes to hours | feed removals | 84/84 reachable |
| Google News RSS search | company headlines | intelligence, instrument news | RSS | hours | switch off with FI_NEWS_RSS=0 | OK |
| DuckDuckGo HTML / Bing results | web search fallback | modules/qa/lookup.py | HTML scraping, 8 s timeout, 10 min cache | live | terms of use; question text leaves the server; untrusted text | OK |
| Groq | LLM | all generation | API key | free-tier limits | outage / quota | OK |
| Gemini | LLM fallback | all generation | API key | free-tier limits | outage / quota | OK |
| Tavus, ngrok | video avatar, tunnel | Tavus mode | API key, token | credits | cost, latency | not tested (no keys in this audit) |
| Google sign-in | identity | accounts mode | OAuth client id | - | config | adapter tested; live consent untested |
| Local: SQLite | chat, profile, transactions, learning state, reports, auth | everything | SQLAlchemy | - | single writer, no backups | OK |
| Local: `data/instruments`, `data/forecast_universe`, `data/forecast_cache`, `data/scenario_backtest` | caches and sweep results | Explore, forecast, validation pages | files (git-ignored) | rebuilt on demand | stale caches, a corrupt file earlier | OK |
| Local: `models/` (XGBoost, LSTM, DKT, DQN; FinBERT optional; Piper voice) | trained / downloaded models | finance, tutor, sentiment, voice | files (git-ignored, rebuilt by scripts) | - | not versioned | OK |
| Local: `data/raw/concepts_kb/concepts.json` | 50 curated finance concepts | tutor retrieval | committed | hand-authored | coverage of 50 topics only | OK |

Known coverage gaps to evaluate in Phase B: India and international news completeness and deduplication, company/ticker extraction in headlines, historical versus current data labelling, market-session awareness (the answer says "as of" a date but not whether the market is open).
