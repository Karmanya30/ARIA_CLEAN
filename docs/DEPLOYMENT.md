# Deploying ARIA

One container runs the API and the built web app. Start with a private staging copy for a handful of testers before any public launch.

## Before you start

* **Run exactly one container.** The database is SQLite (a single file); two copies writing to it will corrupt it. If you need several instances or many simultaneous users, move to Postgres first (set `DB_URL`; the code has not been audited for SQLite-only SQL, so run the tests against it).
* **Use accounts mode for anything reachable from the internet.** The default (`private`) has no login: whoever can open the page can use it. Accounts mode needs an HTTPS address.
* **Questions leave the server.** They go to Groq/Gemini (the language model), to Yahoo Finance, Screener.in, AMFI, CoinGecko and news feeds, and, only for names ARIA's own lists lack, to DuckDuckGo/Bing (turn off with `ARIA_WEB_SEARCH=0`). Screener.in and the search pages are read by scraping, which can be rate-limited or restricted by their terms of use; check them before running this for the public.

## Steps

1. **Server**: any Linux VM with Docker, about 4 GB RAM and 10 GB disk. Point a domain at it.
2. **Get the code**: `git clone https://github.com/Karmanya30/ARIA_CLEAN.git && cd ARIA_CLEAN`
3. **Configure**: `cp .env.example .env` and set at least

   | Variable | Value |
   |---|---|
   | `GROQ_API_KEY`, `GEMINI_API_KEY` | your keys (Gemini is the fallback) |
   | `ARIA_AUTH_MODE` | `accounts` |
   | `ARIA_APP_ORIGIN` | the public address, e.g. `https://aria.example.com` (must be HTTPS) |
   | `GOOGLE_CLIENT_ID` | optional, for Google sign-in |
   | `ARIA_AUTH_ALLOW_SIGNUP` | `0` to close sign-up once your testers have accounts |
   | `ARIA_WEB_SEARCH` | `0` to keep questions off search engines |

   `.env` is git-ignored; keep it that way.
4. **Build and start**: `docker compose up -d --build`. The build trains the small finance and tutor models (a few minutes) and installs CPU-only PyTorch. The first start also warms the language and speech models and can take a couple of minutes; check `docker compose logs -f`.
5. **HTTPS**: put a reverse proxy in front of port 8000. With Caddy the whole config is

   ```
   aria.example.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```

   The Live Avatar page uses a WebSocket (`/api/live/ws`); Caddy and nginx (with the upgrade headers) both pass it through.
6. **Check**: open the address, create an account, ask "What is the PE ratio of Suzlon Energy?", open Progress after a quiz, generate a research report. `curl https://aria.example.com/api/health` should return `{"status":"ok",...}`.

## Optional extras

* **FinBERT sentiment** (better headline scoring): download the weights into `models/nlp/finbert` as in the README, then rebuild. Without them a keyword read is used.
* **Photoreal Live Avatar (MuseTalk)** needs an NVIDIA GPU and a separate environment; it is not part of this image. The other chat modes work without it.
* **Tavus video mode** needs `TAVUS_API_KEY`, a replica id and a public tunnel address; leave it unset and that mode simply will not connect.

## Operations

* **Data**: the database and saved audio clips are in the `aria-data` volume (`/var/aria`). Back it up: `docker run --rm -v ARIA_CLEAN_aria-data:/d -v "$PWD":/b alpine tar czf /b/aria-backup.tgz -C /d .` (the volume name is the compose project name plus `_aria-data`; see `docker volume ls`).
* **Update**: `git pull && docker compose up -d --build`. The volume is kept.
* **Logs**: `docker compose logs -f aria`. Each answer logs one `qa.answer` line with stage timings.
* **Market, news and instrument caches** live inside the container and are rebuilt on demand; a restart simply refetches.
* **Large research caches** (the all-NSE/BSE backtest results) are not shipped. The Research validation pages show whatever has been generated on that server; run `scripts/scenario_backtest_universe.py` there if you want them.

## Known limits

* Free data sources can be late or wrong; ARIA labels the date and says when something is unavailable.
* The Dockerfile and the Python CI job were written without a Docker daemon, so your first build is their first test. If a pinned package has no Linux wheel, the build log names it.
* Not load-tested. The free Groq/Gemini tiers have request limits that real traffic will hit.
* ARIA is an education and research tool, not a SEBI-registered adviser; the disclaimers page must stay visible.
