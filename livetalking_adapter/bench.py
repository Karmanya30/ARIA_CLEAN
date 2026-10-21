r"""LiveTalking benchmark client (aiortc, run in E:\LiveTalking\env). Talks only to the service over HTTP/WebRTC;
no microphone, no speech recognition. Server must already run (scripts\start_livetalking.bat, LT_MODEL/LT_BATCH select the arm).

    E:\LiveTalking\env\python.exe livetalking_adapter\bench.py --label wav2lip-b8 --runs 5 [--base http://127.0.0.1:8020]

Per run, three sessions: short sentence (first audio/video), 16 s paragraph (fps, freezes, lip-sync lag), interruption.
Times are client-side arrival times on localhost (aiortc jitter buffer included; lip-sync lag is therefore arrival-time lag).
Output: one JSON line per label appended to --out, and a markdown row on stdout."""
import argparse, asyncio, json, statistics, subprocess, threading, time
import aiohttp, numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration

SHORT = "Hello, I am ARIA, your financial companion."
LONG = ("Your portfolio gained two point four percent this quarter, driven mostly by banking and information technology holdings. "
        "I would suggest rebalancing slightly towards debt funds, since market volatility has increased and your goal is only three years away.")


_VOICE = None
_CACHE = {}
def wav(text):
    import io, wave
    global _VOICE
    if text not in _CACHE:
        from piper import PiperVoice
        _VOICE = _VOICE or PiperVoice.load("E:/ARIA/models/tts/piper/en_US-kristin-medium.onnx")
        b = io.BytesIO()
        with wave.open(b, "wb") as w: _VOICE.synthesize_wav(text, w)
        _CACHE[text] = b.getvalue()
    return _CACHE[text]


class Vram:
    """Polls whole-card memory (per-process numbers are N/A under WDDM)."""
    def __init__(self):
        self.peak = self.now(); self.stop = False
        threading.Thread(target=self._run, daemon=True).start()
    @staticmethod
    def now():
        try:
            o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
            return int(o.split()[0])
        except Exception:
            return -1
    def _run(self):
        while not self.stop:
            self.peak = max(self.peak, self.now()); time.sleep(0.4)


class Session:
    def __init__(self, base):
        self.base = base; self.a = []; self.v = []; self.sid = None; self.pc = None; self.http = None; self.tasks = []

    async def open(self):
        self.http = aiohttp.ClientSession()
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.pc.addTransceiver("audio", direction="recvonly"); self.pc.addTransceiver("video", direction="recvonly")
        @self.pc.on("track")
        def on_track(t):
            self.tasks.append(asyncio.ensure_future(self._pump(t)))
        await self.pc.setLocalDescription(await self.pc.createOffer())
        async with self.http.post(self.base + "/offer", json={"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}) as r:
            ans = await r.json()
        if "sdp" not in ans: raise RuntimeError(f"offer rejected: {ans}")
        self.sid = ans["sessionid"]
        await self.pc.setRemoteDescription(RTCSessionDescription(ans["sdp"], ans["type"]))

    async def _pump(self, track):
        while True:
            try: f = await track.recv()
            except Exception: return
            t = time.perf_counter()
            if track.kind == "audio":
                x = f.to_ndarray().astype(np.float32)
                self.a.append((t, float(np.sqrt((x ** 2).mean()))))
            else:
                self.v.append((t, roi(f.to_ndarray(format="gray"))))

    async def post(self, path, **body):
        async with self.http.post(self.base + path, json={"sessionid": self.sid, **body}) as r:
            return await r.json()

    async def close(self):
        for t in self.tasks: t.cancel()
        await self.pc.close(); await self.http.close()


# Mouth ROI = lower half of the face box (coords.pkl, frame 0) as fractions of the 576x768 avatar frame.
ROI = (237 / 768, 316 / 768, 220 / 576, 328 / 576); ROI_WH = (54, 40)
REFS = None
AVATAR = "E:/LiveTalking/src/data/avatars/wav2lip256_avatar1"

def roi(g):
    import cv2
    h, w = g.shape
    c = g[int(ROI[0] * h):int(ROI[1] * h), int(ROI[2] * w):int(ROI[3] * w)]
    return cv2.resize(c, ROI_WH, interpolation=cv2.INTER_AREA).astype(np.float32)

def load_refs():
    """The idle video is the avatar's own recorded loop (full_imgs); speech frames differ from the nearest idle frame in the mouth."""
    import cv2, glob
    global REFS
    fs = sorted(glob.glob(AVATAR + "/full_imgs/*.png"))
    REFS = np.stack([roi(cv2.resize(cv2.imread(f, 0), (576, 768))) for f in fs]).reshape(len(fs), -1)


def activity(v, idle_n):
    """Mouth activity per frame = distance of the mouth ROI to the nearest idle-loop frame (~0 while idle, larger while speaking)."""
    x = np.stack([f for _, f in v]).reshape(len(v), -1)
    d = np.array([np.abs(REFS - r).mean(1).min() for r in x])
    return d, d[:idle_n]


def analyse(s, t0, speak_s, tail=1.0):
    ta = np.array([t for t, _ in s.a]); ra = np.array([r for _, r in s.a])
    tv = np.array([t for t, _ in s.v])
    idle_a = ra[ta < t0]; thr = max(150.0, 5 * (idle_a.max() if len(idle_a) else 0))
    loud = np.where((ta > t0) & (ra > thr))[0]
    out = {"first_audio_s": None, "first_video_s": None, "fps": None, "freezes": None, "lag_ms": None, "speech_s": None}
    if not len(loud): return out
    t_a1 = ta[loud[0]]; out["first_audio_s"] = t_a1 - t0
    t_aend = ta[loud[-1]]; out["speech_s"] = t_aend - t_a1
    n_idle = int((tv < t0).sum())
    if n_idle < 5: return out
    act, idle_act = activity(s.v, n_idle)
    vthr = idle_act.mean() + 6 * idle_act.std() + 1.0
    mv = np.where((tv > t0) & (act > vthr))[0]
    out["_dbg"] = [round(float(vthr),2), round(float(act.max()),2), n_idle, len(tv)]
    if len(mv): out["first_video_s"] = tv[mv[0]] - t0
    w = (tv >= t_a1) & (tv <= t_aend)
    if w.sum() > 3:
        tw = tv[w]; out["fps"] = (len(tw) - 1) / (tw[-1] - tw[0])
        out["freezes"] = int((np.diff(tw) > 0.2).sum())
    # lip-sync lag: resample audio envelope and mouth activity to 100 Hz, cross-correlate within +-0.5 s
    if t_aend - t_a1 > 3:
        g = np.arange(t_a1, t_aend, 0.01)
        ea = np.interp(g, ta, ra); em = np.interp(g, tv, act)
        ea = np.convolve(ea, np.ones(5) / 5, "same"); em = np.convolve(em, np.ones(5) / 5, "same")
        ea = (ea - ea.mean()) / (ea.std() + 1e-9); em = (em - em.mean()) / (em.std() + 1e-9)
        cc = lambda k: float(np.mean(ea[max(0, -k):len(ea) - max(0, k)] * em[max(0, k):len(em) - max(0, -k)]))
        best = max(range(-50, 51), key=cc)
        out["lag_ms"] = best * 10; out["lag_corr"] = round(cc(best), 2)  # positive: video activity trails the audio
    return out


async def one(base, text, interrupt_after=None, feed="audio"):
    s = Session(base)
    if feed == "audio": wav(text)  # synthesise before the clock starts
    await s.open()
    try:
        while len(s.v) < 40: await asyncio.sleep(0.05)
        await asyncio.sleep(1.5)  # idle baseline
        t0 = time.perf_counter()
        if feed == "echo":
            r = await s.post("/human", type="echo", text=text, interrupt=True)
        else:  # pre-synthesised Piper wav: isolates the avatar pipeline from TTS (which adds ~0.2 s with the Piper plugin)
            fd = aiohttp.FormData(); fd.add_field("sessionid", str(s.sid)); fd.add_field("file", wav(text), filename="a.wav", content_type="audio/wav")
            async with s.http.post(s.base + "/humanaudio", data=fd) as rr: r = await rr.json()
        if r.get("code", 0) != 0: raise RuntimeError(f"feed: {r}")
        res = {}
        if interrupt_after is None:
            await asyncio.sleep(2 + (16 if text is LONG else 5)); await asyncio.sleep(2)
            res = analyse(s, t0, 0)
        else:
            await asyncio.sleep(interrupt_after)
            ti = time.perf_counter(); await s.post("/interrupt_talk")
            await asyncio.sleep(2.0)
            ta = np.array([t for t, _ in s.a]); ra = np.array([r for _, r in s.a])
            thr = max(150.0, 5 * ra[ta < t0].max())
            after = np.where((ta > ti) & (ra > thr))[0]
            res["interrupt_s"] = (ta[after[-1]] - ti) if len(after) else 0.0  # last loud audio frame after the request
            res["interrupt_s"] = max(0.0, res["interrupt_s"])
        return res
    finally:
        await s.close()


def stat(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None, None
    return round(statistics.median(xs), 3), round(xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))], 3)


async def main():
    global AVATAR
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020"); ap.add_argument("--label", required=True)
    ap.add_argument("--feed", choices=["audio", "echo"], default="audio"); ap.add_argument("--avatar", default=AVATAR, help="avatar dir whose full_imgs are the idle loop"); ap.add_argument("--runs", type=int, default=5); ap.add_argument("--out", default="bench_results.jsonl")
    a = ap.parse_args()
    AVATAR = a.avatar; load_refs(); vram = Vram(); base_v = vram.now()
    short, long_, intr = [], [], []
    for i in range(a.runs):
        short.append(await one(a.base, SHORT, feed=a.feed)); long_.append(await one(a.base, LONG, feed=a.feed)); intr.append(await one(a.base, LONG, interrupt_after=3.0, feed=a.feed))
        print(f"run {i+1}: short {short[-1]} long {long_[-1]} int {intr[-1]}", flush=True)
    vram.stop = True
    res = {"label": a.label, "runs": a.runs, "vram_peak_mb": vram.peak, "vram_idle_mb": base_v}
    for k, rs in (("first_audio_s", short), ("first_video_s", short), ("fps", long_), ("freezes", long_), ("lag_ms", long_), ("lag_corr", long_), ("interrupt_s", intr)):
        res[k] = stat([r.get(k) for r in rs])  # (median, p90)
    print(json.dumps(res))
    with open(a.out, "a") as f: f.write(json.dumps(res) + "\n")

if __name__ == "__main__":
    asyncio.run(main())
