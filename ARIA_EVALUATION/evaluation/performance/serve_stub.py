"""Test server on 127.0.0.1:8016 ONLY: the real FastAPI app, scratch DB (from env), private auth, provider calls replaced by a stub that sleeps
STUB_LLM_MS and returns canned text (or raises, STUB_MODE=down), outbound network blocked. Adds /__stats (call counter) for the harness.
Started and stopped by http_load.py; never run against production data."""
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import block_network, lower_priority
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove(); logger.add(sys.stderr, level="ERROR")  # keep output small
import ai.llm.groq_client as G
MODE, DELAY = os.environ.get("STUB_MODE", "ok"), float(os.environ.get("STUB_LLM_MS", "300")) / 1000
STATS = {"llm_calls": 0}
CANNED = ("Here is a clear explanation. " * 20).strip()


def make(name):
    def f(prompt, system_prompt, model=None):
        STATS["llm_calls"] += 1
        if MODE == "down":
            raise RuntimeError("invalid api key (stub)")
        time.sleep(DELAY)
        return CANNED
    return f


G._BACKENDS = (("groq", make("groq")), ("gemini", make("gemini"))); G._call_groq = make("groq-alt")
from api.main import app


@app.get("/__stats")
def stats():
    return STATS


import uvicorn
uvicorn.run(app, host="127.0.0.1", port=8016, log_level="warning", access_log=False)
