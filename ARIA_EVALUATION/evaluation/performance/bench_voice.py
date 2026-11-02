"""Voice latency (local engines only; no network, no microphone: the audio is synthesised by Piper from fixed text).
 1. Piper TTS: load time, per-sentence synthesis latency and real-time factor.
 2. Whisper base.en on CPU: model load, transcription latency of those clips (timing only; accuracy is not scored here).
 3. Event-loop blocking: POST /api/voice/transcribe is `async def` and calls the blocking transcribe(); while one clip is transcribed on the 8016 test server,
    /api/health is polled every 50 ms and its worst latency is recorded.
Run through run_scratch.sh. Output: results/voice.json"""
import http.client, io, json, os, subprocess, sys, tempfile, threading, time, uuid, wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS, ROOT, pct, block_network, lower_priority, rss_mb, peak_rss_mb
os.environ.update(ARIA_WARMUP="0", ARIA_AUTH_MODE="private", HF_HUB_OFFLINE="1", WHISPER_USE_GPU="0")
assert "aria_perf_" in os.environ.get("DB_URL", "")
lower_priority(); block_network()
from loguru import logger; logger.remove()
res = {}
from ai.speech import live_tts
res["piper_available"] = live_tts.available()
SENT = ["Your savings rate is thirty two percent, which is healthy.", "A SIP of ten thousand rupees a month for twenty years can grow to about one crore at twelve percent.",
        "The new tax regime is cheaper for you by about one lakh fifty thousand rupees a year.", "Hello, how can I help you with your money today?",
        "Diversification means spreading your investments so that one bad bet does not sink the whole portfolio."]
t = time.perf_counter(); live_tts.synthesize("Hello."); res["piper_load_plus_first_synth_s"] = round(time.perf_counter() - t, 2)
lat, rtf, clips = [], [], []
for i in range(4):
    for s in SENT:
        t = time.perf_counter(); wav, mime = live_tts.synthesize(s); dt = time.perf_counter() - t
        with wave.open(io.BytesIO(wav)) as w:
            dur = w.getnframes() / w.getframerate()
        lat.append(dt * 1000); rtf.append(dt / dur)
        if i == 0:
            clips.append((s, wav, dur))
res["piper"] = {"n": len(lat), "p50_ms": round(pct(lat, 50)), "p95_ms": round(pct(lat, 95)), "max_ms": round(max(lat)), "rtf_p50": round(pct(rtf, 50), 3), "rtf_p95": round(pct(rtf, 95), 3),
                "audio_s_per_clip": [round(c[2], 1) for c in clips]}
print(res["piper"], flush=True)
from ai.speech import stt
os.environ["WHISPER_USE_GPU"] = "0"
t = time.perf_counter(); stt._load(); res["whisper_load_s"] = round(time.perf_counter() - t, 2); res["whisper_device"] = stt._select_device()
tl = []
for s, wav, dur in clips + clips:
    t = time.perf_counter(); text = stt.transcribe(wav, filename="clip.wav"); tl.append((time.perf_counter() - t) * 1000)
res["whisper_cpu"] = {"n": len(tl), "p50_ms": round(pct(tl, 50)), "p95_ms": round(pct(tl, 95)), "max_ms": round(max(tl)), "clip_s": round(sum(c[2] for c in clips) / len(clips), 1),
                      "sample_transcript_nonempty": bool(text)}
print(res["whisper_cpu"], res["whisper_device"], flush=True)
res["rss_mb_inproc"] = rss_mb()

# ---- 3. event loop blocking on the real app
PORT = 8016
sys.path.insert(0, str(Path(__file__).parent))


def req(method, path, body=None, headers=None, timeout=120):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout); t = time.perf_counter()
    try:
        c.request(method, path, body=body, headers=headers or {}); r = c.getresponse(); r.read(); return r.status, (time.perf_counter() - t) * 1000
    except Exception as e:
        return type(e).__name__, (time.perf_counter() - t) * 1000
    finally:
        c.close()


env = dict(os.environ, STUB_LLM_MS="50")
p = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-X", "utf8", str(Path(__file__).parent / "serve_stub.py")], cwd=ROOT, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x00004000)
try:
    t0 = time.time()
    while time.time() - t0 < 120 and req("GET", "/api/health", timeout=2)[0] != 200:
        time.sleep(0.3)
    boundary = uuid.uuid4().hex
    wavb = clips[1][1]
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"clip.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + wavb + f"\r\n--{boundary}--\r\n".encode()
    hdr = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    req("POST", "/api/voice/transcribe", body, hdr)       # first call loads Whisper inside the server; excluded
    health, stop = [], threading.Event()

    def poll():
        while not stop.is_set():
            s, ms = req("GET", "/api/health", timeout=60); health.append((time.perf_counter(), s, ms)); time.sleep(0.05)
    th = threading.Thread(target=poll); th.start(); time.sleep(0.5)
    t = time.perf_counter(); s, ms = req("POST", "/api/voice/transcribe", body, hdr); stop.set(); th.join()
    during = [h[2] for h in health if h[0] >= t]
    res["event_loop_block"] = {"transcribe_status": s, "transcribe_ms": round(ms), "health_polls_during": len(during), "health_max_ms_during": round(max(during)) if during else None,
                               "health_max_ms_before": round(max([h[2] for h in health if h[0] < t] or [0]))}
    print(res["event_loop_block"], flush=True)
finally:
    p.terminate()
    try:
        p.wait(15)
    except Exception:
        p.kill()
res["peak_rss_mb_inproc"] = peak_rss_mb()
(RESULTS / "voice.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
