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

Three tabs: **Chat** (all 4 modules, auto-routed, plus a mode selector
for Normal / Conversational (free avatar) / Tavus CVI (paid video call)
— try the example queries if unsure what to ask), **Your Profile**
(Module 1 inputs), **Your Progress** (Module 2 mastery).

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
  equity_research/  Module 4 — screener.in + yfinance
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
