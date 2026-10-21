"""Quick manual check: prepare the default face, lip-sync a wav, composite frames, print timings (no mic, no server)."""
import sys, time, os
sys.path.insert(0, r"E:\ARIA")
import numpy as np, cv2, threading, wave, tempfile, shutil
from pathlib import Path
from avatar_engine import config
from avatar_engine.backend_musetalk import MuseTalkBackend
from avatar_engine.compositor import Scaled, StageOpts, render
from avatar_engine.motion import Pose
from avatar_engine.tts import resample16k
mode = sys.argv[1] if len(sys.argv) > 1 else "half"
wavp = sys.argv[2] if len(sys.argv) > 2 else r"E:\avatar_bench\hello.wav"
t0 = time.time(); b = MuseTalkBackend(vae_mode=mode); b.load(); print("load", round(time.time() - t0, 1), flush=True)
d = Path(r"E:\avatar_bench\rep_" + "default"); d.mkdir(exist_ok=True)
t0 = time.time()
if not (d / "prep.pkl").exists(): print(b.prepare(config.DEFAULT_FACE, d))
print("prepare", round(time.time() - t0, 1), flush=True)
rep = b.load_replica(d, "x")
w = wave.open(wavp); pcm = w.readframes(w.getnframes()); sr = w.getframerate()
wav16 = resample16k(pcm, sr); print("audio s", len(wav16) / 16000)
fps = 25; faces = []; t0 = time.time(); ttfb = None
for batch in b.lipsync(rep, wav16, fps, 0, threading.Event()):
    if ttfb is None: ttfb = time.time() - t0
    faces.extend(list(batch))
tot = time.time() - t0
print(f"mode={mode} frames={len(faces)} first_batch={ttfb:.3f}s total={tot:.2f}s gen_fps={len(faces)/tot:.1f}", b.info(), flush=True)
sc = Scaled(rep, StageOpts())
t0 = time.time(); outs = []
for i, f in enumerate(faces): outs.append(render(sc, 0, Pose(), f, 1.0))
print("composite ms/frame", round((time.time() - t0) * 1000 / len(faces), 1), "kB/frame", round(np.mean([len(o) for o in outs]) / 1024, 1))
sel = np.linspace(8, len(outs) - 8, 6).astype(int)
imgs = [cv2.imdecode(np.frombuffer(outs[i], np.uint8), 1) for i in sel]
cv2.imwrite(rf"E:\avatar_bench\grid_{mode}.jpg", np.hstack(imgs[:6]))
