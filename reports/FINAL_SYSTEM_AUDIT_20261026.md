# ARIA final system audit (26 Oct 2026, branch `audit/system-review-20261016`)

Scope: every data pipeline, every connection between parts, every external source, then the whole platform tested end to end.
Method: read the code paths, probed every live source, ran 40+ real questions through `POST /api/chat`, called every GET route,
ran the Python suite, the web build and both browser suites. Nothing here is a claim about answer quality beyond what is stated.

## 1. Architecture and connections (as verified in code)

```
Browser (React, web/)  --/api, /avatar, /embed-->  Vite dev proxy or built static files  -->  FastAPI (api/main.py, port 8000)
                                                                                              |  middleware: ResourceLimits, CORS, auth.authorize
  routers: chat, voice, profile, transactions, progress, avatar (Tavus + Live Avatar page), research, forecast,
           scenario_backtest, live (WebSocket), markets, instruments, auth
                                                                                              v
modules/qa/pipeline.py   understand -> context -> answer -> ground -> trust -> persist -> present   (one pipeline, every channel)
   answer = core/orchestrator.py routing:
     small talk / crisis / dialogue acts -> fixed or short replies
     NEW  data question about a name outside the 45 hard-coded companies -> modules/qa/lookup.py
            -> instrument catalogue (NSE/BSE universe + AMFI funds + crypto + commodities) -> quote + Screener statements
            -> else web search (shared/websearch.py), snippets are the only allowed evidence
     company intelligence / research reports / fundamentals (Screener.in) / live quote (yfinance) -> modules/equity_research
     market-wide questions -> modules/market (indices, sectors, news)
     personal finance -> modules/finance (profile, statements, SIP/EMI/tax engines)
     concepts -> modules/tutor (retrieval + quiz)
     everything else -> general model reply with conversation memory
   ground/trust: modules/qa/trust.py removes sentences holding numbers that are not in the fetched data, adds the disclaimer
Storage: SQLite via SQLAlchemy (`DB_URL`): chat_conversations/turns/embeddings/leases, financial_profiles, transactions,
         learning_state, conversation_style, research_reports, forecast_runs, audio_artifacts, auth_*, statement_previews.
         Files: data/instruments (AMFI, CoinGecko), data/forecast_universe, data/forecast_cache, data/scenario_backtest.
```

Chat modes: Normal, Conversational, Live Avatar (Free, MuseTalk on port 8010), Tavus CVI. (Local Avatar and LiveTalking were removed at the owner's request.)

## 2. External sources: live health on 26 Oct 2026

| Source | Used for | Result |
|---|---|---|
| Yahoo Finance (quotes, history, search) | prices, stats, fundamentals fallback | OK |
| Screener.in | yearly statements, ratios, shareholding | OK (consolidated page, standalone fallback) |
| AMFI NAVAll + mfapi.in | mutual fund NAV and history | OK |
| CoinGecko | crypto market data | OK |
| FRED (India 10Y yield) | G-sec yield | one probe timed out at 15 s, then answered in 0.4 s with curl; the code has a 12 h cache and degrades quietly |
| NSE EQUITY_L / Nifty 500 list, BSE | stock universe | OK |
| 84 RSS news feeds (`shared/news.py`) | headlines for every module | 84 of 84 reachable, parsed, newest item under 96 h |
| Groq, Gemini | language model, fallback | OK (synthetic probe) |
| DuckDuckGo HTML, Bing | new web-search fallback | OK |

## 3. Problems found and fixed in this audit

1. **Figures were being deleted from every fundamentals answer** (real bug). The equity-research reply did not carry its statements as evidence, so the number check in `modules/qa/trust.py` removed every figure ("Insight: no figure that ARIA could verify"). Fixed in `modules/equity_research/pipeline.py`; regression test added.
2. **Fiscal-year labels such as "FY23-24" were treated as unverified numbers** and their sentences removed. Fixed in `trust.py`.
3. **Only 45 hard-coded companies were understood.** Any other name (Kaynes, Suzlon, Ola Electric, a fund, gold, bitcoin) fell to the model with no data and got "no recorded information" or an invented number (a gold price of 55,800 rupees per 10 g was returned). New `modules/qa/lookup.py` resolves names (typo tolerant, fund-aware) against the instrument catalogue and answers from fetched facts. Direct answers for price, NAV, P/E, market cap, revenue, profit, borrowings.
4. **Data not found now searches the web** (`shared/websearch.py`, DuckDuckGo then Bing, no key). Only the returned snippets may be used, the source links are shown, and `ARIA_WEB_SEARCH=0` turns it off (the question text leaves the computer when it is on).
5. **Company figures defaulted to standalone accounts** (Infosys revenue 148,819 vs the 178,650 consolidated headline). Chat answers now use consolidated figures where they exist and always label the basis.
6. **Two-company questions** ("compare revenue of Infosys and Wipro") answered for one company. Now a side-by-side table from Screener data, no model text.
7. **"Show me the NAV of ..." was answered with a supportive "I hear you" reply**; the tone layer now ignores data questions.
8. **Concept questions ("What is inflation?") returned a news briefing**; they now go to the tutor. "Who is the CEO of Infosys?" no longer returns an empty valuation template.
9. **A corrupt price-cache file (an interrupted write) crashed every later run for that symbol** (GGDPROP.BO). Cache reads now treat a corrupt file as a miss and download again; test added.
10. **Browser test harness was broken** by the earlier pipeline refactor (`scripts/audit_server.py` patched removed attributes). Repaired; SpeechRecognition is disabled in both browser specs so no test can listen to the real microphone.
11. **A stale Screener page was presented as current**: Tata Elxsi's consolidated page stops in 2015, so "revenue" came back as 2012-2015. `get_screener_data` now uses the standalone page when it is more recent (test added).
12. Bing tracking links in web-search sources are unwrapped to the real address.
13. Dividend per share, dividend yield, EPS and book value added to stock quotes (the dividend-yield question had no data).

## 4. Test results

* Python suite: 1216 passed, 0 failed (the count includes the new `tests/qa/test_lookup.py` and a cache test).
* Web build and type check: clean.
* Browser suites: 34 of 34 (workflows, voice toggle) and 4 of 4 (accounts) pass.
* API route sweep: 37 GET routes called against live data; every non-2xx was a parameter I left out, plus `markets/quote` for a non-existent symbol, which correctly returns 503 with a stale-data body.
* 40+ real questions through `/api/chat`: the data questions above now return grounded answers; an unknown company ("Zorblax Industries") now says the data is not available instead of inventing it.

## 5. Known limits (not fixed, and why)

* Gold and silver come from Yahoo futures in US dollars; ARIA states the unit and does not convert to Indian retail prices.
* A fund that was renamed (for example "SBI Bluechip", now a Large Cap fund) is not in AMFI under the old name; the question falls to web search.
* Web snippets can be wrong or off-topic (the "Zorblax" search returned unrelated documents). The answer says the data is unavailable and still lists the links it looked at.
* About 143 BSE companies and recent listings have too little price history for the forecast and backtest pipelines; they are reported as `no results/cache`, not guessed.
* Free sources can be late or wrong; the checks only catch what they can see.
* Port 8010 still has an avatar engine process started by an earlier launcher run; stop it by closing that window.
