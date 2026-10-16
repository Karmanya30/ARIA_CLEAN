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

from api.routes import avatar, chat, forecast, instruments, live, markets, profile, progress, research, scenario_backtest, transactions, voice

auth.mode()  # reject misspelled modes rather than falling back to private access
app = FastAPI(title="ARIA API", dependencies=[Depends(auth.authorize)])
app.add_middleware(ResourceLimits)

# The Vite dev server (default :5173) and the built static frontend served
# from this same process both need to reach the API; a public ngrok tunnel
# (Tavus mode only) adds an extra origin the browser sees requests come
# back through. Private mode keeps the existing non-cookie behavior;
# account mode permits credentials only from its configured exact origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[auth.origin()] if auth.mode() == "accounts" else ["*"],
    allow_credentials=auth.mode() == "accounts",
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host=os.getenv("ARIA_BIND_HOST", "127.0.0.1"), port=8000, reload=False)
