"""Engine: owns the backend, TTS, replica store, caches and the single live session slot."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from loguru import logger

from . import config
from .backend_base import Backend
from .compositor import ReplicaData, Scaled, StageOpts, render
from .motion import Pose
from .replicas import DEFAULT_ID, ReplicaStore
from .tts import Tts


class Engine:
    def __init__(self, backend: Backend, tts: Tts | None = None, root=None, default_face=None):
        self.backend = backend
        self.tts = tts or Tts()
        self.store = ReplicaStore(root or config.REPLICA_DIR, self._prepare, default_face if default_face is not None else config.DEFAULT_FACE)
        self.mouth_fps = config.MOUTH_FPS
        self.session = None
        self.session_lock = threading.Lock()
        self.ready = False
        self.status = "starting"
        self.error: str | None = None
        self.fps = 0.0
        self.gen_fps = 25.0
        self.dropped = 0
        self.last_metrics: dict = {}
        self.speak_tokens: dict[str, tuple[float, dict]] = {}
        self.tts_pool = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self.gen_pool = ThreadPoolExecutor(1, thread_name_prefix="lipsync")
        self.render_pool = ThreadPoolExecutor(2, thread_name_prefix="render")
        self._reps: OrderedDict[str, ReplicaData] = OrderedDict()
        self._scaled: OrderedDict[tuple, Scaled] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ startup
    def start_async(self) -> None:
        threading.Thread(target=self.start, name="engine-start", daemon=True).start()

    def start(self) -> None:
        t0 = time.time()
        try:
            self.status = "loading models"
            self.gpu_call(self.backend.load)
            self.status = "preparing default replica"
            self.store.ensure_default()
            self.status = "warming up"
            self.tts.warm_up()
            self.gpu_call(self._warm)
            self.ready, self.status = True, "ready"
            logger.info(f"engine ready in {time.time() - t0:.1f}s (backend={self.backend.name}, gen {self.gen_fps:.1f} fps)")
        except Exception as exc:
            logger.exception("engine failed to start")
            self.status, self.error = "error", str(exc)

    def _warm(self) -> None:
        try:
            rep = self.get_replica(DEFAULT_ID)
        except Exception:
            return
        wav = np.zeros(int(16000 * 1.2), np.float32)
        face, n, dt = None, 0, 0.0
        for _ in range(2):          # the second pass is the steady-state speed
            t0, n = time.time(), 0
            for b in self.backend.lipsync(rep, wav, self.mouth_fps, 0, threading.Event()):
                n += len(b)
                face = b[0]
            dt = time.time() - t0
        if n:
            self.gen_fps = n / dt
        sc = self.get_scaled(DEFAULT_ID, StageOpts(config.OUT_W, config.OUT_H))
        render(sc, 0, Pose(), face, 1.0)

    def gpu_call(self, fn, *a):
        """All GPU work runs on one dedicated thread: PyTorch/cuDNN keep per-thread handles and workspaces, so hopping
        between threads wastes VRAM (and under a memory cap it triggered spurious out-of-memory retries)."""
        return self.gen_pool.submit(fn, *a).result()

    def note_gen(self, n: int, seconds: float) -> None:
        if seconds > 0 and n > 0:
            self.gen_fps = 0.7 * self.gen_fps + 0.3 * (n / seconds)

    # ------------------------------------------------------------------ replicas
    def _prepare(self, src, dest) -> dict:
        meta = self.gpu_call(self.backend.prepare, src, dest)
        rep = self.backend.load_replica(dest, dest.name)
        sc = Scaled(rep, StageOpts(512, 512))
        jpg = render(sc, 0, Pose(), None, 0)
        (dest / "preview.jpg").write_bytes(jpg)
        return meta

    def get_replica(self, rid: str) -> ReplicaData:
        with self._lock:
            if rid in self._reps:
                self._reps.move_to_end(rid)
                return self._reps[rid]
        self.store.get(rid)                       # 404 if unknown
        rep = self.backend.load_replica(self.store.path(rid), rid)
        with self._lock:
            self._reps[rid] = rep
            while len(self._reps) > 3:
                old = next((k for k in self._reps if k != DEFAULT_ID), None)
                if old is None:
                    break
                del self._reps[old]
        return rep

    def get_scaled(self, rid: str, opts: StageOpts) -> Scaled:
        key = (rid, *opts.key())
        with self._lock:
            sc = self._scaled.get(key)
        if sc is None:
            sc = Scaled(self.get_replica(rid), opts)
            with self._lock:
                self._scaled[key] = sc
                while len(self._scaled) > 4:
                    self._scaled.popitem(last=False)
        sc.o.quality = opts.quality
        return sc

    def forget_replica(self, rid: str) -> None:
        with self._lock:
            self._reps.pop(rid, None)
            for k in [k for k in self._scaled if k[0] == rid]:
                del self._scaled[k]

    # ------------------------------------------------------------------ misc
    def health(self) -> dict:
        info = self.backend.info() if self.ready else {}
        default = None
        try:
            default = self.store.get(DEFAULT_ID)["id"]
        except Exception:
            pass
        return {"status": "ok" if self.ready else ("error" if self.error else "starting"), "ready": self.ready, "detail": self.error or self.status,
                "backend": self.backend.name, "vae_mode": getattr(self.backend, "vae_mode", None), "gpu": info.get("gpu"),
                "vram_used_mb": info.get("vram_used_mb", 0), "process_vram_mb": info.get("process_vram_mb", 0), "fps": round(self.fps, 1),
                "gen_fps": round(self.gen_fps, 1), "mouth_fps": self.mouth_fps, "replica_default": default,
                "session_active": self.session is not None, "voices": self.tts.voices(), "default_voice": self.tts.resolve(None),
                "last_metrics": self.last_metrics, "dropped_ticks": self.dropped}

    def new_speak_token(self, payload: dict) -> str:
        import uuid
        now = time.time()
        for k in [k for k, (t, _) in self.speak_tokens.items() if t < now - 30]:
            del self.speak_tokens[k]
        tok = uuid.uuid4().hex[:12]
        self.speak_tokens[tok] = (now, payload)
        return tok
