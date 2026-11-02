"""Hidden per-reply cost: every written (non-avatar) reply starts a background audio clip (modules/qa/present.audio_token -> ai/llm/audio_script
(one LLM call) -> ai/speech/tts (Edge-TTS network, pyttsx3 fallback)). This script counts those background calls with a STUB model and a STUB synthesiser
(no provider, no network, no audio), for several reply paths, in 'Normal Mode'. Output: results/background_audio.json"""
import json, os, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, block_network, lower_priority
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove()
import ai.llm.groq_client as G
import ai.speech.tts as T
CALLS, TTS = [], []
CANNED = "Here is a clear explanation. " * 20


def make(name):
    def f(prompt, system_prompt, model=None):
        CALLS.append((time.perf_counter(), len(system_prompt or "") + len(prompt)))
        return CANNED
    return f


G._BACKENDS = (("groq", make("groq")), ("gemini", make("gemini"))); G._call_groq = make("alt")
import ai.llm.audio_script as AS
AUDIO_SCRIPT = []
_orig = AS.generate_audio
AS.generate_audio = lambda p, *a, **k: (AUDIO_SCRIPT.append(len(p)), CANNED)[1]
T.synthesize = lambda text, *a, **k: (TTS.append(len(text)), None)[1]
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app)
out = []
for name, q, mode in [("smalltalk_warm", "hello", "Normal Mode"), ("smalltalk", "hello", "Normal Mode"), ("general", "recommend a good movie", "Normal Mode"), ("tutor", "what is the sharpe ratio", "Normal Mode"),
                      ("finance_calc", "how much sip do i need to reach 1 crore in 20 years", "Normal Mode"), ("finance_tax", "old vs new tax regime for me", "Normal Mode")]:
    for _ in range(2):
        CALLS.clear(); TTS.clear(); AUDIO_SCRIPT.clear()
        t = time.perf_counter()
        r = c.post("/api/chat", json={"query": q, "session_id": "ba-" + uuid.uuid4().hex[:6], "owner_id": "ba-owner", "request_id": uuid.uuid4().hex, "mode": mode})
        sync_ms = (time.perf_counter() - t) * 1000
        at_return = len(CALLS)
        time.sleep(2.0)   # let the background audio worker finish
        b = r.json()
        out.append({"path": name, "status": r.status_code, "reply_ms": round(sync_ms), "llm_calls_before_reply_returned": at_return, "llm_calls_total_after_2s": len(CALLS),
                    "background_llm_calls": len(CALLS) - at_return, "audio_script_llm_calls": len(AUDIO_SCRIPT), "audio_script_prompt_chars": sum(AUDIO_SCRIPT), "tts_calls": len(TTS), "tts_chars": sum(TTS), "has_audio_token": bool(b.get("audio_token"))})
        print(out[-1], flush=True)
(RESULTS / "background_audio.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
