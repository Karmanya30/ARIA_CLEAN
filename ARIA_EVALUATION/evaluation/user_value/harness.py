"""User-value evaluation harness (Phase A). In-process, no network, no LLM provider, scratch SQLite, private auth.
Import this module FIRST: it sets the environment, blocks sockets, and replaces every model backend with a recording stub.
The stub returns STUB_REPLY and records the exact system prompt + prompt the real code would have sent, so we can see what
ARIA adds to a bare question (profile, memory, grounding passages, tone) without generating any prose."""
import ctypes, json, os, socket, sys, time, uuid
SCR = os.environ.get("UV_SCRATCH", r"C:\Users\jtmah\AppData\Local\Temp\claude\e--ARIA\cd7da059-d5af-476e-afeb-f40c54c7f86a\scratchpad")
os.makedirs(SCR, exist_ok=True)
DB = os.path.join(SCR, f"uv_{uuid.uuid4().hex[:8]}.db")
os.environ.update(DB_URL="sqlite:///" + DB.replace("\\", "/"), ARIA_AUTH_MODE="private", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
                  ARIA_MEMORY_SEMANTIC="0", ARIA_WEB_SEARCH="0", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1")
for k in ("GROQ_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)  # belt and braces: no key, no provider call
assert "user_profiles" not in os.environ["DB_URL"]
sys.path.insert(0, r"E:\ARIA")
try:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
except Exception:
    pass

NET_ATTEMPTS: list[str] = []
def _blocked(*a, **k):
    NET_ATTEMPTS.append(str(a[:2])[:100])
    raise OSError("network blocked by user-value harness")
YF_ATTEMPTS: list[str] = []
# yfinance talks through curl_cffi (C sockets), which the Python-level socket guard below cannot stop (found in the first run:
# a few Yahoo quote calls went out). So replace the whole package, and make curl_cffi unimportable.
import types as _types
_yf = _types.ModuleType("yfinance")
def _yf_blocked(*a, **k):
    YF_ATTEMPTS.append("call")
    raise OSError("yfinance blocked by user-value harness")
_yf.__getattr__ = lambda name: (_yf_blocked if not name.startswith("__") else (_ for _ in ()).throw(AttributeError(name)))
sys.modules["yfinance"] = _yf
sys.modules["curl_cffi"] = None
socket.getaddrinfo = _blocked
socket.socket.connect = _blocked
socket.create_connection = _blocked

STUB_REPLY = "[STUB MODEL REPLY - no model was called]"
CALLS: list[dict] = []
from loguru import logger as _lg  # noqa: E402
_lg.remove()
from ai.llm import groq_client as G  # noqa: E402

MODE = os.environ.get("UV_STUB", "ok")  # ok: STUB_REPLY; down: the provider "fails" (shows ARIA's own fallbacks)
def _stub(prompt, system_prompt, model=None):
    CALLS.append({"system": system_prompt, "prompt": prompt, "model": model})
    if MODE == "down":
        raise RuntimeError("stubbed provider down")
    return STUB_REPLY
def _structured(prompt, *, system_prompt, schema, timeout=8.0, max_tokens=1024):
    CALLS.append({"system": system_prompt, "prompt": prompt, "structured": True})
    return None
def _no_client(*a, **k):
    raise RuntimeError("stubbed: no client")
G._BACKENDS = (("groq", _stub), ("gemini", _stub))
G._call_groq = _stub
G._call_gemini = _stub
G._make_groq_client = _no_client
G.generate_structured = _structured
import ai.llm.spoken as _sp  # noqa: E402

from modules.qa import present, pipeline  # noqa: E402
from modules.qa.models import QARequest, ChatMode, Channel  # noqa: E402
present.audio_token = lambda *a, **k: None  # the real one starts a TTS clip (Edge TTS would need the network)
from shared import user_store, conversation_memory as memory  # noqa: E402
from shared.user_store import current_owner  # noqa: E402
from core import session as core_session  # noqa: E402

def seed_profile(owner, **facts):
    tok = current_owner.set(owner)
    try:
        user_store.save_financial_profile(owner, source="eval-synthetic", **facts)
    finally:
        current_owner.reset(tok)

def turn(owner, sid, q, mode="Normal Mode", correct=True, **ctx):
    """One chat turn through modules.qa.pipeline.answer. Returns a compact record."""
    CALLS.clear(); NET_ATTEMPTS.clear(); YF_ATTEMPTS.clear()
    from modules.qa.models import QAContext
    t = time.perf_counter()
    try:
        r = pipeline.answer(QARequest(query=q, session_id=sid, owner_id=owner, mode=ChatMode.parse(mode), correct=correct,
                                      request_id=uuid.uuid4().hex, context=QAContext(**ctx))).to_dict()
        err = None
    except Exception as e:
        r, err = {}, f"{type(e).__name__}: {str(e)[:160]}"
    calls = [dict(c) for c in CALLS]
    resp = r.get("response", "") if isinstance(r.get("response"), str) else ""
    return {"q": q, "owner": owner, "sid": sid, "error": err, "route": r.get("domain"), "response": resp,
            "stub_reply_shown": STUB_REPLY in resp, "llm_calls": len(calls), "calls": calls,
            "grounding": r.get("grounding"), "degraded": r.get("degraded"), "profile_basis": r.get("profile_basis"),
            "tags": r.get("trust") or r.get("trust_tags"), "keys": sorted(r.keys()), "net_attempts": len(NET_ATTEMPTS), "yf_attempts": len(YF_ATTEMPTS),
            "ms": round((time.perf_counter() - t) * 1000), "normalized": (r.get("qa") or {}).get("normalized_query"),
            "corrected": (r.get("qa") or {}).get("corrected"), "spoken": r.get("spoken"), "raw": r}
