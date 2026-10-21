"""One live avatar session (a WebSocket): a fixed-rate render loop that always sends a frame (idle or speaking) and the
speech pipeline that feeds it.

   speak -> split_text -> [Piper TTS (CPU thread) -> lip-sync batches (GPU thread)] -> pieces
   render loop (25 fps, wall clock): idle pose + (when a piece is playing) the generated mouth + the matching audio slice

Everything a piece needs for playback is timestamped on the stream clock (ms since the session started), so the browser
schedules audio and frames from the same clock. A piece starts as soon as the frames generated so far, played at real
time, will stay ahead of generation (so with a fast GPU the first frames leave right after the first batch)."""
from __future__ import annotations

import asyncio
import collections
import json
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from loguru import logger

from . import config, protocol
from .backend_base import GpuOom
from .chunking import split_text
from .compositor import Scaled, StageOpts, pingpong, render
from .motion import PRESETS, IdleMotion
from .tts import resample16k

MOUTH_LADDER = (25, 20, 15, 12)
TAIL = 0.25          # seconds of mouth fade-out after the last word


@dataclass
class Piece:
    text: str
    pcm: bytes
    sr: int
    utt: "Utterance"
    fps: int
    base_start: int
    dur: float = 0.0
    faces: list = field(default_factory=list)
    n: int = 0
    done: bool = False
    failed: bool = False
    gen_t0: float = 0.0
    t0: float | None = None       # stream-clock start (s)
    sent_samples: int = 0
    last: bool = False
    underrun: int = 0
    first: object = None          # asyncio.Event set when the first batch (or the end) is ready


@dataclass
class Utterance:
    text: str
    voice: str | None
    emotion: str
    rate: float | None
    t_recv: float                  # monotonic
    cancel: threading.Event = field(default_factory=threading.Event)
    first_frame_ms: float | None = None
    pieces: int = 0
    gen_ms: list = field(default_factory=list)
    underruns: int = 0


class Session:
    def __init__(self, engine, ws, replica_id: str, opts: StageOpts):
        self.e, self.ws, self.rid, self.opts = engine, ws, replica_id, opts
        self.loop = asyncio.get_running_loop()
        self.t_start = time.monotonic()
        self.send_lock = asyncio.Lock()
        self.seq = 0
        self.state = None
        self.mood = "neutral"
        self.listening = False
        self.motion = IdleMotion()
        self.mouth_fps = engine.mouth_fps
        self.queue: collections.deque[Piece] = collections.deque()
        self.cur: Piece | None = None
        self.last_end = 0.0
        self.vid_ofs = 0
        self.utts: asyncio.Queue = asyncio.Queue()
        self.utt: Utterance | None = None
        self.pending_gen = 0          # utterances accepted but not finished generating
        self.tasks: list[asyncio.Task] = []
        self.closed = False
        self.fps_marks = collections.deque(maxlen=50)
        self.scaled: Scaled | None = None
        self.rep = None
        self.energy = 0.0

    # ------------------------------------------------------------------ helpers
    def now(self) -> float:
        return time.monotonic() - self.t_start

    async def send_json(self, obj: dict) -> None:
        if self.closed:
            return
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(obj))
            except Exception:
                self.closed = True

    async def send_bin(self, data: bytes) -> None:
        if self.closed:
            return
        async with self.send_lock:
            try:
                await self.ws.send_bytes(data)
            except Exception:
                self.closed = True

    async def set_state(self, value: str, **extra) -> None:
        if value != self.state:
            self.state = value
            await self.send_json({"type": "state", "value": value, **extra})

    async def _scaled(self) -> Scaled:
        self.rep = await self.loop.run_in_executor(None, self.e.get_replica, self.rid)
        self.scaled = await self.loop.run_in_executor(None, self.e.get_scaled, self.rid, self.opts)
        return self.scaled

    # ------------------------------------------------------------------ public API (called by the server)
    async def start(self) -> None:
        await self._scaled()
        self.motion.set_mood(self.mood)
        await self.set_state("idle")
        self.tasks = [asyncio.create_task(self._render_loop()), asyncio.create_task(self._speech_worker())]

    async def close(self) -> None:
        self.closed = True
        self.interrupt(reason=None)
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "ping":
            await self.send_json({"type": "pong", "t": msg.get("t"), "server_ms": int(self.now() * 1000)})
        elif t == "speak":
            text = str(msg.get("text") or "").strip()
            if not text:
                return
            style = msg.get("style") if isinstance(msg.get("style"), dict) else {}
            emo = str(msg.get("emotion") or self.mood)
            u = Utterance(text[:4000], msg.get("voice"), emo if emo in PRESETS else "neutral", style.get("rate"), time.monotonic())
            self.mood, self.listening = u.emotion, False
            self.motion.set_mood(self.mood)
            self.pending_gen += 1
            await self.set_state("thinking")
            await self.utts.put(u)
        elif t == "interrupt":
            self.interrupt(reason="interrupted")
            await self.set_state("idle", reason="interrupted")
        elif t in ("listening", "listen"):
            on = bool(msg.get("value", msg.get("on", True)))
            if on and self.cur is None and not self.queue and self.pending_gen == 0:
                self.listening = True
                self.motion.set_mood(self.mood, listening=True)
                await self.set_state("listening")
            elif not on and self.listening:
                self.listening = False
                self.motion.set_mood(self.mood)
                await self.set_state("idle")
        elif t == "configure":
            if msg.get("emotion") in PRESETS:
                self.mood = msg["emotion"]
                self.motion.set_mood(self.mood, self.listening)
            o = self.opts
            n = StageOpts(int(msg.get("width") or o.w), int(msg.get("height") or o.h), str(msg.get("framing") or o.framing),
                          str(msg.get("background") or o.bg), o.quality)
            n.w, n.h = min(max(n.w, 128), 1024), min(max(n.h, 128), 1024)
            if n.key() != o.key():
                self.opts = n
                self.scaled = await self.loop.run_in_executor(None, self.e.get_scaled, self.rid, n)
        elif t == "state" and msg.get("value") in ("listening", "idle"):
            await self.handle({"type": "listening", "value": msg["value"] == "listening"})

    def interrupt(self, reason: str | None = "interrupted") -> None:
        """Stop everything now: queued utterances, generation, and playback."""
        while not self.utts.empty():
            try:
                self.utts.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self.utt:
            self.utt.cancel.set()
        for p in list(self.queue) + ([self.cur] if self.cur else []):
            p.utt.cancel.set()
        self.queue.clear()
        self.cur = None
        self.pending_gen = 0
        self.last_end = 0.0

    # ------------------------------------------------------------------ speech pipeline
    async def _speech_worker(self) -> None:
        while True:
            u: Utterance = await self.utts.get()
            self.utt = u
            try:
                await self._run_utterance(u)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("utterance failed")
                await self.send_json({"type": "error", "message": f"speech failed: {exc}"})
            finally:
                self.pending_gen = max(0, self.pending_gen - 1)
                self.utt = None

    async def _run_utterance(self, u: Utterance) -> None:
        texts = split_text(u.text)
        e = self.e
        synth = lambda tx: self.loop.run_in_executor(e.tts_pool, e.tts.synth, tx, u.voice, u.emotion, u.rate)
        next_base = pingpong(int((self.now() + 0.4) * 25) + self.vid_ofs, len(self.rep.frames)) if len(self.rep.frames) > 1 else 0
        fut = synth(texts[0])
        try:
            for i, tx in enumerate(texts):
                pcm, sr = await fut
                fut = None
                if u.cancel.is_set():
                    return
                logger.info(f"piece {i}: tts ready {(time.monotonic() - u.t_recv) * 1000:.0f} ms after speak, {len(pcm) / 2 / sr:.2f}s audio")
                wav16 = resample16k(pcm, sr)
                if len(wav16) < 1600:       # nothing to say
                    if i + 1 < len(texts):
                        fut = synth(texts[i + 1])
                    continue
                p = Piece(tx, pcm, sr, u, self.mouth_fps, next_base, dur=len(pcm) / 2 / sr)
                p.n = int(len(wav16) / 16000 * p.fps)
                p.first = asyncio.Event()
                next_base += int(np.ceil(p.dur * 25))
                u.pieces += 1
                p.last = i == len(texts) - 1 and self.utts.empty()
                self.queue.append(p)
                gen = asyncio.ensure_future(self._generate(p, wav16))
                if i + 1 < len(texts):      # the next clause is synthesised once this one's first frames exist (CPU contention otherwise)
                    await p.first.wait()
                    fut = synth(texts[i + 1])
                await gen
                if p.failed or u.cancel.is_set():
                    return
        finally:
            if fut is not None:
                fut.cancel()

    async def _generate(self, p: Piece, wav16: np.ndarray) -> None:
        e = self.e
        for attempt in range(3):
            p.faces.clear()
            p.gen_t0 = time.monotonic()
            try:
                try:
                    await self.loop.run_in_executor(e.gen_pool, self._gen_thread, p, wav16)
                finally:
                    p.first.set()
                p.done = True
                logger.info(f"piece done: {len(p.faces)} frames in {(time.monotonic() - p.gen_t0) * 1000:.0f} ms ({len(p.faces) / max(time.monotonic() - p.gen_t0, 1e-3):.1f} fps)")
                return
            except GpuOom as exc:
                msg = e.backend.downgrade()
                if self.mouth_fps > MOUTH_LADDER[-1]:
                    self.mouth_fps = MOUTH_LADDER[MOUTH_LADDER.index(self.mouth_fps) + 1] if self.mouth_fps in MOUTH_LADDER else 15
                p.fps = self.mouth_fps
                p.n = int(len(wav16) / 16000 * p.fps)
                await self.send_json({"type": "notice", "message": f"GPU memory low: {msg or 'frame rate lowered'} (mouth {p.fps} fps)"})
                logger.warning(f"GPU OOM, downgrading: {msg}; {exc}")
        p.failed = True
        self.queue.clear()
        await self.set_state("unavailable", reason="GPU out of memory")

    def _gen_thread(self, p: Piece, wav16: np.ndarray) -> None:
        e = self.e
        t_prev = p.gen_t0
        for batch in e.backend.lipsync(self.rep, wav16, p.fps, p.base_start, p.utt.cancel):
            now = time.monotonic()
            per = (now - t_prev) * 1000 / max(len(batch), 1)
            e.note_gen(len(batch), now - t_prev)
            t_prev = now
            p.utt.gen_ms.append(per)
            if not p.faces:
                logger.info(f"first batch {len(batch)} frames after {(now - p.gen_t0) * 1000:.0f} ms (gpu thread started)")
                self.loop.call_soon_threadsafe(p.first.set)
            p.faces.extend(list(batch))
            if p.utt.cancel.is_set():
                return

    # ------------------------------------------------------------------ render loop
    def _can_start(self, p: Piece) -> bool:
        if p.done or len(p.faces) >= p.n:
            return True
        if not p.faces:
            return False
        rate = max(self.e.gen_fps, 1.0)
        remaining = p.n - len(p.faces)
        return len(p.faces) / p.fps >= remaining / rate + 0.08

    async def _render_loop(self) -> None:
        dt = 1.0 / config.DISPLAY_FPS
        n = 0
        t_prev = self.now()
        try:
            while not self.closed:
                T = self.now()
                target = n * dt
                if T < target:
                    await asyncio.sleep(target - T)
                    T = self.now()
                elif T - target > 0.25:       # fell behind (slow client / CPU): resync instead of bursting
                    n = int(T / dt)
                    self.e.dropped += 1
                n += 1
                await self._tick(T, max(T - t_prev, 1e-3))
                t_prev = T
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("render loop crashed")
            await self.set_state("unavailable", reason=f"render error: {exc}")
            self.closed = True

    async def _tick(self, T: float, dt: float) -> None:
        # ---- start the next piece when it can play without running dry
        if self.cur is None and self.queue and self._can_start(self.queue[0]):
            p = self.queue.popleft()
            p.t0 = self.last_end if 0 <= T - self.last_end < 0.12 else T     # gapless when it follows a piece closely
            self.cur = p
            if len(self.rep.frames) > 1:
                self.vid_ofs = p.base_start - int(p.t0 * 25)
            await self.send_json({"type": "caption", "text": p.text, "t_start": int(p.t0 * 1000), "t_end": int((p.t0 + p.dur) * 1000)})
        p = self.cur
        face, gain, speaking, first = None, 1.0, False, False
        if p is not None:
            tau = T - p.t0
            upto = min(int(tau * p.sr), len(p.pcm) // 2)
            if upto > p.sent_samples:           # audio slice up to now (the last slice of a piece is flushed here too)
                audio = p.pcm[p.sent_samples * 2:upto * 2]
                ts = p.t0 + p.sent_samples / p.sr
                p.sent_samples = upto
                x = np.frombuffer(audio, np.int16).astype(np.float32) / 32768
                self.energy = float(min(np.sqrt(np.mean(x * x)) * 4.0, 1.0)) if len(x) else 0.0
                await self.send_bin(protocol.pack_audio(self.seq, int(ts * 1000), audio, p.sr))
            if tau < p.dur + (TAIL if p.last else 0):
                speaking = True
                first = p.utt.first_frame_ms is None
                if first:
                    await self.set_state("speaking")
                j = tau * p.fps
                j0, nf = int(j), len(p.faces)
                if j0 >= nf - 1 and not p.done:
                    p.underrun += 1
                    p.utt.underruns += 1
                    j0, frac = max(nf - 1, 0), 0.0
                else:
                    j0, frac = min(j0, max(nf - 1, 0)), j - j0
                if nf:
                    face = p.faces[min(j0, nf - 1)]
                    if p.fps < config.DISPLAY_FPS and frac > 0.05 and j0 + 1 < nf:
                        face = cv2.addWeighted(face, 1 - frac, p.faces[j0 + 1], frac, 0)
                gain = min(1.0, tau / 0.12)
                if p.last:
                    gain = min(gain, max(0.0, (p.dur + TAIL - tau) / TAIL))
            else:
                self.last_end = p.t0 + p.dur
                self.cur = None
                if p.last and p.utt.first_frame_ms is not None:
                    await self._finish_metrics(p.utt)
        if not speaking:
            self.energy = 0.0
            if self.cur is None and not self.queue and self.pending_gen == 0 and self.state in ("speaking", "thinking"):
                await self.set_state("idle")
        k = pingpong(int(T * 25) + self.vid_ofs, len(self.rep.frames)) if len(self.rep.frames) > 1 else 0
        pose = self.motion.step(T, dt, speaking, self.energy)
        jpg = await self.loop.run_in_executor(self.e.render_pool, render, self.scaled, k, pose, face, gain)
        self.seq += 1
        await self.send_bin(protocol.pack_video(self.seq, int(T * 1000), jpg))
        if first:
            p.utt.first_frame_ms = (time.monotonic() - p.utt.t_recv) * 1000
        self.fps_marks.append(T)
        if len(self.fps_marks) > 10 and self.seq % 50 == 0:
            self.e.fps = (len(self.fps_marks) - 1) / max(self.fps_marks[-1] - self.fps_marks[0], 1e-3)

    async def _finish_metrics(self, u: Utterance) -> None:
        gen = float(np.mean(u.gen_ms)) if u.gen_ms else 0.0
        m = {"type": "metrics", "ttfb_ms": round(u.first_frame_ms or 0), "fps": round(self.e.fps, 1), "gen_ms": round(gen, 1),
             "mouth_fps": self.mouth_fps, "underruns": u.underruns}
        self.e.last_metrics = m
        await self.send_json(m)
        # slow generation: step the lip-sync rate down for the next utterance
        if u.underruns > 4 and self.mouth_fps in MOUTH_LADDER[:-1]:
            self.mouth_fps = MOUTH_LADDER[MOUTH_LADDER.index(self.mouth_fps) + 1]
            await self.send_json({"type": "notice", "message": f"generation too slow, mouth rate lowered to {self.mouth_fps} fps"})
