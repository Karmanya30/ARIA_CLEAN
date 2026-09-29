# ARIA

AI-powered personal finance assistant, financial tutor, market analyst, and
equity researcher — a BTP (Bachelor's Technology Project) at IIIT Sri City.

## The 4 modules

| # | Module | What it does | Key models |
|---|---|---|---|
| 1 | Personal Finance | Risk profile, budget, SIP plan, tax, spend forecast, fraud flags | XGBoost, LSTM, Isolation Forest, Linear Programming |
| 2 | Intelligent Tutor | Explains ~50 financial concepts, adapts to what you already know, quizzes you | Sentence-BERT + FAISS, DKT (LSTM), DQN |
| 3 | Market Analysis | Real Nifty/Sensex/sector trend data | none — real data + LLM narration |
| 4 | Equity Research | Company fundamentals (screener.in) + live price/news (yfinance) | none — real data + LLM narration |

All four are auto-routed from one chat box (see `core/router.py`) and
narrated by Groq (`openai/gpt-oss-120b`), automatically falling back
to Google Gemini if Groq errors or rate-limits (`ai/llm/groq_client.py`).
Conversational Mode adds a free, self-hosted-in-browser 3D avatar
(TalkingHead + HeadAudio, see `interface/avatar/`) with no paid API.
Tavus CVI Mode adds a paid, real-time WebRTC video call with the same
avatar for anyone with a Tavus API key.

## Architecture

A FastAPI backend (`api/`) wraps the existing business logic in
`core/`, `modules/`, `shared/`, and `ai/` unchanged, and serves it to a
React + TypeScript frontend (`web/`). Everything runs in a single
process — no subprocess management, no orphaned background processes.

```
web/ (React + Vite, :5173 in dev)  --/api, /avatar, /embed-->  api/ (FastAPI, :8000)
                                                                    |
                                                                    v
                                                core / modules / shared / ai
                                                (unchanged BTP logic)
```

### Equity research reports (Module 4)

Ask for a full report -- *"equity research report on Reliance"*, *"DCF valuation of TCS"*,
*"is HDFC Bank overvalued"* -- and Module 4 runs its financial-intelligence layer
(`modules/equity_research/intelligence/`): consolidated multi-year statement analysis,
deterministic valuation (DCF for companies, DDM + justified P/B for banks, peer multiples),
a bull/bear/judge debate, a verification gate, and a provenance ledger. Numbers are computed
by code; the LLM only writes prose and cites evidence ids (any figure it types itself is
removed and reported). The chat shows the usual 4-section summary plus an expandable report.

Every report is **saved** (SQLite, same database as the profile) as a new version per company, listed
in the **Research reports** tab, re-openable later, downloadable (HTML -- print to PDF --, Markdown, or
all-data JSON) and regenerable on fresh data (`/api/research/reports`, `.../{id}/html`, `.../download`,
`.../regenerate`). ARIA has no accounts, so history belongs to a device-level id kept in the browser's
`localStorage`; clearing site data or switching browsers starts a new history.
The document separates ACTUAL, CALCULATED, ESTIMATE, ASSUMPTION, SOURCE TEXT and AI INTERPRETATION, shows
actual vs forecast columns, a WACC x terminal-growth grid, bull/base/bear scenarios, a seeded Monte Carlo
interval, and lists what the data sources cannot provide (segments, geography, industry size, precedent deals) instead of guessing.

**Report types.** The same saved report can be viewed as an *equity research report*, a *financial model report*,
a *valuation report* or a *DuPont and ratio analysis* (ask for e.g. "dupont analysis of TCS", "financial model of
ITC", "valuation report on Infosys", or pick the type in the Research reports tab). Every type ends with an
"Important disclosures" page (nature of the report, no analyst certification, conflicts of interest, how the stance
is defined with the real thresholds, sources and dates, AI use, verification findings, limitations, risk warning).
Extra content: DuPont ROE decomposition with a factual driver note, common-size statements, working-capital cycle,
ROIC, gross margin and current/quick ratio (when the sources report them), an Altman Z-score (Yahoo balance sheet +
screener.in EBIT/sales; refused when the two sources disagree on total assets or report in different currencies),
eight quarters of shareholding pattern with the promoter pledge screener.in flags (risk flag at 25% pledged or a 2pp
promoter sell-down), key management with age and pay, the company ranked against its listed peers with its share of
the peer set's revenue (not an industry market share), exit-multiple and LBO cross-checks (a buyer borrowing 3x EBITDA
at risk-free + 3% and exiting after 5 years at its entry multiple: the price that still earns 20% a year; neither is
blended into the fair value), and sourced Wikipedia background on the company and industry (CC BY-SA 4.0, labelled
unverified).

**Mutual funds.** "mutual fund analysis of Parag Parikh Flexi Cap" builds a descriptive report from mfapi.in NAV
history: CAGR vs a Nifty 50 total-return proxy (the UTI Nifty 50 Index Fund's NAV; the price index is the fallback,
and debt funds get no equity benchmark), its rank and quartile among the same-plan Growth schemes of its AMFI category
(from AMFI's daily NAV file; categories above 150 schemes are skipped), calendar-year and rolling returns, volatility,
Sharpe/Sortino (annualised by how often the scheme publishes NAV), drawdown, beta/alpha and SIP XIRR. Unit
restructurings (a face-value change shows as a one-day 100x jump) are rescaled out of the history and noted. Schemes
are looked up in AMFI's full list of active schemes, so closed legacy plans are not picked. It does not rate funds and
does not have holdings, expense ratio or AUM (not in the public data).

**PDF.** `Download PDF` renders the report with a locally installed Chrome or Edge in headless mode (set
`ARIA_PDF_BROWSER` to point at a specific browser). Without one the API answers 501 and the HTML's *Save as PDF /
Print* button does the same job.
Valuation inputs risk-free rate / equity risk premium / terminal growth are **configured
assumptions** (`FI_*` in `.env`, see `.env.example`), not live data. Ideas adapted from
FinRobot (Apache-2.0) -- see `THIRD_PARTY_NOTICES.md`. Not investment advice.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # add -r requirements-dev.txt to also get pytest

cp .env.example .env
# edit .env: set GROQ_API_KEY (console.groq.com) and GEMINI_API_KEY
# (aistudio.google.com/apikey) -- both have free tiers, no card needed
# Tavus CVI Mode is optional: also set TAVUS_API_KEY, TAVUS_REPLICA_ID,
# and NGROK_AUTHTOKEN if you want the paid video-call avatar mode.

cd web && npm install && cd ..
```

## Train the models (once)

Module 1 and Module 2's real trained models aren't committed to the repo
(they're gitignored — regenerate them locally, same as the PDF's own
"models/ is gitignored" convention):

```bash
# Module 1 — personal finance
python -m scripts.generate_synthetic_transactions
python -m modules.finance.train.train_xgb_risk
python -m modules.finance.train.train_lstm_spend

# Module 2 — tutor
python -m scripts.build_concept_kb
python -m scripts.generate_kt_sequences
python -m modules.tutor.train.train_lstm_kt
python -m modules.tutor.train.train_dqn_teacher
```

Each finishes in well under 5 minutes on a laptop CPU — no GPU needed
anywhere in this project.

## Run it

Two processes, both from the repo root:

```bash
# Terminal 1 — API backend
uvicorn api.main:app --reload --port 8000

# Terminal 2 — frontend
cd web && npm run dev
```

Open the URL Vite prints (`http://localhost:5173`). The dev server
proxies `/api`, `/avatar`, and `/embed` through to the backend on
`:8000`, so both must be running.

Five tabs: **Chat** (all 4 modules, auto-routed, plus a mode selector
for Normal / Conversational (free avatar) / Tavus CVI (paid video call)
— try the example queries if unsure what to ask), **Research reports**
(saved equity research, see above), **Your Profile** (Module 1 inputs),
**Your Progress** (Module 2 mastery) and **Settings**.

**Settings → Appearance** switches between two UI themes, applied
instantly and remembered per browser (`localStorage`, key `aria_theme`):
*Classic* (default: left sidebar, cool blue) and *Vitara* (warm ivory,
top navigation bar, pill controls, deep-green accent). A theme is just a
`[data-theme='…']` block of the design tokens in `web/src/styles/`
(`tokens.css`, `theme-vitara.css`) plus a few layout rules, so adding or
tuning one means editing that one CSS file and listing it in
`web/src/theme.ts`. Generated report documents carry their own styling
and look the same in every theme.

### Production build

```bash
cd web && npm run build   # outputs web/dist
```

Serve `web/dist` from any static host (or point FastAPI's own static
file serving at it) and point it at the deployed `api/main:app`
process; there's no dev-only proxy needed once the frontend calls an
absolute API URL instead of Vite's relative proxy.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests that need a trained model or the concept index (see "Train the
models" above) skip themselves with a clear reason if that artifact isn't
present yet, rather than failing. The LLM is always mocked — no test ever
makes a real Groq/Gemini call.

The frontend has no separate test suite yet; typecheck it with:

```bash
cd web && npx tsc -b --noEmit
```

## Repo layout

```
api/             FastAPI backend -- routes wrapping core/modules/shared/ai for the React frontend
web/             React + TypeScript frontend (Vite)
ai/llm/          Groq+Gemini client, prompt templates (shared by all 4 modules)
ai/speech/       Whisper STT, edge-tts/pyttsx3 TTS
core/            Router (which module handles a query) + orchestrator + session state
modules/
  finance/       Module 1 — models, calculators, orchestrator, train/
  tutor/         Module 2 — models, retriever, quiz, orchestrator, train/
  market/        Module 3 — real index/sector data
  equity_research/  Module 4 — screener.in + yfinance; intelligence/ = research reports (valuation, debate, audit)
shared/          SQLite user store, vector store, NER, company resolver
interface/avatar/  The 3D avatar (TalkingHead/HeadAudio) + Tavus embed page, served by api/routes/avatar.py
config/          Paths, runtime settings, model hyperparameters
scripts/         One-off generators (synthetic data, concept KB, KT sequences)
tests/           pytest suite, mirrors the modules/ layout
```

## Why these choices (short version)

- **Groq + Gemini, not local FinGPT**: the original BTP plan specced a
  self-hosted 7B LLM. That needs ~14GB VRAM and doesn't survive public
  deployment on free hosting. Groq (fast, free tier) with a Gemini
  fallback (more stable free tier) gets the reliability without the
  GPU requirement.
- **All models are small and CPU-only on purpose**: every trained
  model here (XGBoost, tiny LSTMs, Isolation Forest, tiny DQN) trains
  in minutes on a laptop CPU, with no GPU required anywhere.
- **Real data over mocks**: Module 3/4 use real yfinance/screener.in
  data; Module 1/2's synthetic training data is disclosed as synthetic
  (standard practice when real consumer/student data isn't available),
  not silently faked at inference time.
- **FastAPI + React over Streamlit**: Streamlit's per-run rerender model
  and lack of first-class real-time audio/video control made a
  natural-feeling conversational avatar impractical. A real backend/
  frontend split gives the avatar (both the free TalkingHead mode and
  the paid Tavus WebRTC mode) proper control over audio playback and
  UI state, and runs as a single process — no subprocess/orphaned-
  process management to get wrong.

See `ARIA Requirements.pdf` for the original BTP report spec this
implementation is scoped against.
