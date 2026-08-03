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
narrated by Groq (`llama-3.3-70b-versatile`), automatically falling back
to Google Gemini if Groq errors or rate-limits (`ai/llm/groq_client.py`).
Conversational Mode adds a free, self-hosted-in-browser 3D avatar
(TalkingHead + HeadAudio, see `interface/avatar/`) with no paid API.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # add -r requirements-dev.txt to also get pytest

cp .env.example .env
# edit .env: set GROQ_API_KEY (console.groq.com) and GEMINI_API_KEY
# (aistudio.google.com/apikey) -- both have free tiers, no card needed
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

```bash
streamlit run interface/streamlit_app.py
```

Three tabs: **Chat** (all 4 modules, auto-routed — try the example
queries if unsure what to ask), **Your Profile** (Module 1 inputs),
**Your Progress** (Module 2 mastery).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests that need a trained model or the concept index (see "Train the
models" above) skip themselves with a clear reason if that artifact isn't
present yet, rather than failing. The LLM is always mocked — no test ever
makes a real Groq/Gemini call.

## Deploying (Streamlit Community Cloud)

1. Push this repo to GitHub (already done if you're reading this from
   the repo).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, "New app", point it at this repo and
   `interface/streamlit_app.py`.
3. In the app's **Settings → Secrets**, add:
   ```toml
   GROQ_API_KEY = "..."
   GEMINI_API_KEY = "..."
   ```
4. **Important**: the trained models (Module 1/2) and the FAISS concept
   index are gitignored, so they won't exist on a fresh deploy. Either
   run the training commands above and temporarily commit the
   `models/`/`data/vector_store/` output for the deploy, or add a
   one-time startup step that runs them (e.g. in a `packages.txt`/build
   hook) — this isn't automated yet, see the roadmap doc for follow-up.

## Repo layout

```
ai/llm/          Groq+Gemini client, prompt templates (shared by all 4 modules)
ai/speech/       Whisper STT, edge-tts/pyttsx3 TTS
core/            Router (which module handles a query) + orchestrator + session state
modules/
  finance/       Module 1 — models, calculators, orchestrator, train/
  tutor/         Module 2 — models, retriever, quiz, orchestrator, train/
  market/        Module 3 — real index/sector data
  equity_research/  Module 4 — screener.in + yfinance
shared/          SQLite user store, vector store, NER, company resolver
interface/       Streamlit app + the avatar (TalkingHead/HeadAudio)
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
- **All models are small and CPU-only on purpose**: the target
  deployment (Streamlit Community Cloud) has no GPU. Every trained
  model here (XGBoost, tiny LSTMs, Isolation Forest, tiny DQN) trains
  in minutes on a laptop CPU.
- **Real data over mocks**: Module 3/4 use real yfinance/screener.in
  data; Module 1/2's synthetic training data is disclosed as synthetic
  (standard practice when real consumer/student data isn't available),
  not silently faked at inference time.

See `ARIA Requirements.pdf` for the original BTP report spec this
implementation is scoped against.
