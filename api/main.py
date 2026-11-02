"""ARIA API -- FastAPI backend wrapping core/modules/shared/ai (unchanged
business logic) for the React frontend in web/. Replaces
interface/streamlit_app.py, which called the same functions in-process.

Run: python -m api.main   (or: uvicorn api.main:app --reload)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.resource_limits import ResourceLimits
from api import auth
from api.runtime_version import backend_revision

_RUNTIME_REVISION = backend_revision()  # snapshot loaded source, not files edited later

from api.routes import avatar, chat, conversations, feedback, forecast, instruments, live, markets, profile, progress, research, scenario_backtest, transactions, voice

auth.mode()  # reject misspelled modes rather than falling back to private access
_LOOPBACK = ("localhost", "127.0.0.1", "::1", "[::1]", "testserver")
if auth.mode() == "private" and os.getenv("ARIA_BIND_HOST", "127.0.0.1") not in _LOOPBACK and os.getenv("ARIA_ALLOW_OPEN") != "1":
    # Private mode has no login: the owner id is the only credential. Reachable from other machines it is an open door (SEC-04).
    raise RuntimeError("ARIA_AUTH_MODE=private with ARIA_BIND_HOST=%s would be open to the network. Use ARIA_AUTH_MODE=accounts, "
                       "or set ARIA_ALLOW_OPEN=1 if that is intended." % os.getenv("ARIA_BIND_HOST"))
app = FastAPI(title="ARIA API", dependencies=[Depends(auth.authorize)])
app.add_middleware(ResourceLimits)


@app.middleware("http")
async def hide_api_reference(request, call_next):
    """With accounts, the route list (/docs, /redoc, /openapi.json) is for signed-in users only (SEC-07). Private mode keeps it open:
    the launcher checks /openapi.json to recognise ARIA's own API."""
    if auth.mode() == "accounts" and request.url.path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect") and auth.principal(request) is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return await call_next(request)


@app.middleware("http")
async def private_mode_guard(request, call_next):
    """Private mode has no login, so a page on another site (or a DNS-rebinding host name) must not be able to write through the
    visitor's browser: writes need a loopback Host, and a browser Origin that is loopback or the host itself (SEC-04)."""
    if auth.mode() == "private" and os.getenv("ARIA_ALLOW_OPEN") != "1" and request.method not in ("GET", "HEAD", "OPTIONS"):
        from urllib.parse import urlsplit
        host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
        origin = request.headers.get("origin")
        origin_host = urlsplit(origin).hostname if origin and origin != "null" else None
        if host not in _LOOPBACK or (origin is not None and origin_host not in _LOOPBACK):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "This request must come from ARIA on this computer."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_store_personal(request, call_next):
    """Answers that carry personal data are not kept by browsers or proxies."""
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.method == "GET":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://accounts.google.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com; font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; media-src 'self' blob: data:; worker-src 'self' blob:; "
        "connect-src 'self' http://localhost:8010 http://127.0.0.1:8010 https://accounts.google.com https://cdn.jsdelivr.net https://storage.googleapis.com data: blob:; "
        "frame-src 'self' https://accounts.google.com; frame-ancestors 'self'; base-uri 'self'; object-src 'none'")
_CSP_REPORT = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'; base-uri 'none'; "
               "script-src 'sha256-FbkIjM5XrDskHC2ER/ErjgfkR0w9Xn8+kzogAgqiHV4='")  # only the print-on-open line of the downloadable report


@app.middleware("http")
async def security_headers(request, call_next):
    """Basic hardening headers on every response (SEC-06). No CSP yet: the app loads fonts and the Google sign-in script."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")  # the live meeting and report viewer are same-origin frames
    # Report pages are generated HTML from third-party text: no script at all. Everything else may load what the app itself loads
    # (Google sign-in and fonts, the 3D avatar's libraries on jsDelivr, the lip-sync server on port 8010) and nothing more (SEC-06).
    response.headers.setdefault("Content-Security-Policy", _CSP_REPORT if "/research/reports/" in request.url.path and request.url.path.endswith("/html") else _CSP)
    return response


# The Vite dev server (default :5173) and the built static frontend served
# from this same process both need to reach the API. Private mode keeps
# the existing non-cookie behavior;
# account mode permits credentials only from its configured exact origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[auth.origin()] if auth.mode() == "accounts" else ["*"],
    allow_credentials=auth.mode() == "accounts",
    allow_methods=["*"],
    allow_headers=["*"],
)

def _redact_access_log() -> None:
    """The uvicorn access log would record owner_id/session_id (the private-mode credential) from query strings (SEC-04)."""
    import logging
    import re

    class Redact(logging.Filter):
        def filter(self, record):
            if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
                path = re.sub(r"((?:owner_id|session_id|audio_token)=)[^&\s]+", r"\1***", record.args[2])
                record.args = record.args[:2] + (path,) + record.args[3:]
            return True

    logging.getLogger("uvicorn.access").addFilter(Redact())


_redact_access_log()


def _warm_up() -> None:
    """Load the heavy pieces (orchestrator imports, the Sentence-BERT encoder, NER) in the background at
    startup. Otherwise the first chat message after a restart pays for all of it (~45 s against ~3 s)."""
    import threading
    import time

    from loguru import logger

    from modules.market import live as markets_live

    threading.Thread(target=markets_live.start, name="markets-live-start", daemon=True).start()  # not behind the other warm-ups
    from modules.market import instruments as instrument_catalog

    threading.Thread(target=instrument_catalog.warm, name="instruments-warm", daemon=True).start()  # AMFI file, coin list, stock universe

    def _whisper() -> None:  # the first spoken question otherwise waits several seconds for the speech model to load
        try:
            from ai.speech.stt import _load

            _load()
        except Exception as exc:  # noqa: BLE001 - voice then loads on first use, as before
            logger.debug(f"speech model warm-up skipped: {type(exc).__name__}")

    threading.Thread(target=_whisper, name="whisper-warm", daemon=True).start()
    t = time.time()
    try:
        import core.orchestrator  # noqa: F401  (imports every module pipeline)
        from shared.ner import extract_entities
        from shared.vector_store import _get_encoder

        _get_encoder().encode(["warm up"])
        from shared.understand import _speller

        _speller()
        extract_entities("warm up")
        from shared.news import warm_up as warm_news

        warm_news()
        from ai.speech.live_tts import warm_up as warm_live_voice

        warm_live_voice()
        from modules.equity_research.intelligence import sentiment

        t_fb = time.time()
        sentiment.score(["warm up"])  # loads FinBERT when its weights are installed (no-op otherwise)
        logger.info(f"Sentiment warm-up took {time.time() - t_fb:.1f}s")
        logger.info(f"Warm-up finished in {time.time() - t:.1f}s")
    except Exception as exc:  # a failed warm-up only means the first request loads them instead
        logger.warning(f"Warm-up skipped: {exc}")


@app.on_event("startup")
def _start_warm_up() -> None:
    if os.environ.get("ARIA_WARMUP", "1") != "0":
        import threading

        threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()


app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(feedback.router)
app.include_router(voice.router)
app.include_router(profile.router)
app.include_router(transactions.router)
app.include_router(progress.router)
app.include_router(avatar.router)
app.include_router(research.router)
app.include_router(forecast.router)
app.include_router(scenario_backtest.router)
app.include_router(live.router)
app.include_router(markets.router)
app.include_router(instruments.router)
app.include_router(auth.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "revision": _RUNTIME_REVISION}


# Deployment: when the web app has been built (cd web && npm run build) this process serves it too, so one container is the
# whole product. Mounted last so every /api, /avatar and /embed route above keeps priority. ARIA_SERVE_WEB=0 turns it off.
_WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
if (_WEB_DIST / "index.html").exists() and os.environ.get("ARIA_SERVE_WEB", "1") != "0":
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host=os.getenv("ARIA_BIND_HOST", "127.0.0.1"), port=8000, reload=False)
