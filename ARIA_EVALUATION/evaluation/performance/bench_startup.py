"""Startup / warm-up / model-load timing, each in a FRESH child process (BelowNormal, 2 threads, scratch DB, network refused by proxy + socket block).
usage: bench_startup.py import | warm | sbert-offline-flag | sbert-no-flag
  import            : `import api.main` x3 (ARIA_WARMUP=0): seconds + peak working set
  warm              : the model-loading steps of api.main._warm_up that need no network, each timed (HF_HUB_OFFLINE=1)
  sbert-offline-flag: SentenceTransformer load with HF_HUB_OFFLINE=1
  sbert-no-flag     : SentenceTransformer load WITHOUT the flag while the network is unreachable (the case of a laptop that is offline)
Output: results/startup_<mode>.json"""
import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, ROOT

CHILD = r'''
import os, sys, time, json
sys.path.insert(0, r"%(root)s"); sys.path.insert(0, r"%(here)s")
from common import lower_priority, block_network, peak_rss_mb, rss_mb
lower_priority(); block_network()
from loguru import logger; logger.remove()
mode = sys.argv[1]; out = {}
def step(name, fn):
    t = time.perf_counter()
    try: fn(); out[name] = {"s": round(time.perf_counter() - t, 2), "rss_mb": rss_mb()}
    except Exception as e: out[name] = {"s": round(time.perf_counter() - t, 2), "error": type(e).__name__ + ": " + str(e)[:100]}
if mode == "import":
    step("import_api_main", lambda: __import__("api.main"))
elif mode == "warm":
    step("import_api_main", lambda: __import__("api.main"))
    step("import_core_orchestrator", lambda: __import__("core.orchestrator"))
    from shared.vector_store import _get_encoder
    step("sbert_load", _get_encoder)
    step("sbert_first_encode", lambda: _get_encoder().encode(["warm up"]))
    from shared.understand import _speller
    step("speller", _speller)
    from shared.ner import extract_entities
    step("ner_first_call", lambda: extract_entities("warm up"))
    from modules.equity_research.intelligence import sentiment
    step("finbert_first_score", lambda: sentiment.score(["warm up"]))
    from modules.tutor import retriever
    step("concept_kb_first_search", lambda: retriever.retrieve("what is sip"))
else:
    from sentence_transformers import SentenceTransformer
    step("sbert_load", lambda: SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu"))
out["peak_rss_mb"] = peak_rss_mb()
print("RESULT" + json.dumps(out))
'''


def run(mode, env_extra, timeout):
    import tempfile, shutil
    scratch = tempfile.mkdtemp(prefix="aria_perf_")
    env = dict(os.environ, OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", ARIA_AUTH_MODE="private", ARIA_WARMUP="0", GROQ_API_KEY="", GEMINI_API_KEY="", PYTHONUTF8="1",
               DB_URL=f"sqlite:///{scratch}/perf.db".replace("\\", "/"), HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", **env_extra)
    code = CHILD % {"root": str(ROOT), "here": str(Path(__file__).parent)}
    t = time.perf_counter()
    try:
        p = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-X", "utf8", "-c", code, mode], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=timeout, creationflags=0x00004000)
        line = [l for l in p.stdout.splitlines() if l.startswith("RESULT")]
        r = json.loads(line[0][6:]) if line else {"error": (p.stderr or p.stdout)[-300:]}
    except subprocess.TimeoutExpired:
        r = {"error": f"timeout after {timeout}s"}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    r["wall_s"] = round(time.perf_counter() - t, 1)
    return r


mode = sys.argv[1]
if mode == "import":
    res = [run("import", {"HF_HUB_OFFLINE": "1"}, 300) for _ in range(3)]
elif mode == "warm":
    res = [run("warm", {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}, 600)]
elif mode == "sbert-offline-flag":
    res = [run("sbert", {"HF_HUB_OFFLINE": "1"}, 300) for _ in range(2)]
else:
    res = [run("sbert", {}, 600)]
(RESULTS / f"startup_{mode}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1)[:3000])
