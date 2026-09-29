"""ARIA API -- FastAPI backend wrapping core/modules/shared/ai (unchanged
business logic) for the React frontend in web/. Replaces
interface/streamlit_app.py, which called the same functions in-process.

Run: python -m api.main   (or: uvicorn api.main:app --reload)
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import avatar, chat, profile, progress, research, transactions, voice

app = FastAPI(title="ARIA API")

# The Vite dev server (default :5173) and the built static frontend served
# from this same process both need to reach the API; a public ngrok tunnel
# (Tavus mode only) adds an extra origin the browser sees requests come
# back through -- allow_origins="*" is fine here since there's no cookie
# auth anywhere in this app to leak.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(profile.router)
app.include_router(transactions.router)
app.include_router(progress.router)
app.include_router(avatar.router)
app.include_router(research.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
