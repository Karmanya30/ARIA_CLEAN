# ARIA project discovery (Phase A)

Date: 2026-10-30. Branch `evaluation/pre-launch-audit` (from `main` at `984ffbb`). Everything below was read from the repository or measured on this machine; items I could not confirm are marked **SUSPECTED**. Secret values were never read or printed.

## 1. What ARIA is

A personal financial intelligence assistant for Indian users: a FastAPI backend (`api/`, `core/`, `modules/`, `shared/`, `ai/`) with a React + Vite web app (`web/`) and SQLite storage. Size: about 28,000 lines of Python in application code (`modules` 20.7k, `api` 2.5k, `shared` 2.8k, `ai` 1.4k, `core` 0.6k), 190 TypeScript files in `web/src`, 92 pytest files (1,220 tests), 2 Playwright specs (38 tests).

Four product modules (README): (1) personal finance, (2) tutor with quizzes and progress, (3) market analysis, (4) equity research (fundamentals, live quotes, full research reports, company intelligence). On top: a single answer pipeline (`modules/qa/pipeline.py`) used by every channel, several themes and two UI versions, four chat modes (Normal, Conversational voice disk, Live Avatar (Free, MuseTalk, GPU optional), Tavus CVI), Explore (instrument catalogue), Markets dashboard, accounts mode, report exports.

## 2. Existing, incomplete, broken, duplicate, unused

**Working (verified earlier in this project, 26-27 Oct):** chat pipeline in all four modes, data lookup for any NSE/BSE/AMFI/crypto/commodity name with web-search fallback, profile/transactions/statement import, research reports (generate/list/HTML/PDF/MD/regenerate/delete), tutor quiz loop and Progress, Explore, Markets, accounts sign-in, live avatar websocket, speech-to-text, audio clips, backtest/validation summaries. Full pytest suite and both browser suites pass.

**Incomplete / limited (verified):** gold and silver are Yahoo futures in USD only; renamed funds fall to web search; "I spend 2500 per week" style statements are not saved to the profile; 21 companies still `retry` in the backtest sweep; no Postgres path tested; Docker image never built (no daemon was available); Python CI job never run.

**Absent (verified by grep):** FinRobot as a dependency or runtime component (its role prompts were adapted into `modules/equity_research/intelligence/agents.py`, credited in THIRD_PARTY_NOTICES.md); LBO model; dividend discount model (**SUSPECTED absent, financial agent to confirm**); bond pricing/duration; derivatives pricing; real-estate rent-vs-buy engine (**SUSPECTED**); a metrics/tracing backend; an admin/analytics UI.

**Duplicate:** the web UI exists three times - `web/src/components`, `web/src/versions/v1/components`, `web/src/versions/v2/components` (copies that drift; every UI fix has to be applied three times, as the recent cleanup showed).

**Possibly unused (SUSPECTED, to be confirmed by the QA/product agents):** `interface/avatar/avatar.html`, `models/embeddings`, `models/intent_classifier`, `models/llm`, `models/ner_extractor` (empty folders), `ARIA_Evaluation.ipynb`, older PDFs at repo root, `scripts/data_generation`.

## 3. Observability and single points of failure

* Observability: loguru text logs; one `qa.answer` line per answer with stage timings and LLM call counts; no metrics endpoint, tracing, alerting or error aggregation. **Gap.**
* Single points of failure: one process; SQLite (one writer); Groq with Gemini fallback (both free tiers with request limits); Yahoo Finance and Screener.in scraping for every company answer; no automatic backups; model files are rebuilt, not versioned.

## 4. Where the detail lives

| Document | Content |
|---|---|
| ARCHITECTURE_MAP.md | diagrams of the end-to-end flow and module dependencies |
| FEATURE_INVENTORY.md | feature to code to dependencies to tests traceability matrix |
| API_INVENTORY.md | all 71 HTTP operations (generated from the live schema) |
| DATA_SOURCE_INVENTORY.md | every external source and local store |
| DEPENDENCY_INVENTORY.md | pinned Python and web packages, 69 environment variables (39 undocumented in `.env.example`) |
| reports/ | the eight specialist audits (Phase A baseline) |
