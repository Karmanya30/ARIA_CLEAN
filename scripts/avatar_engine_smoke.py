r"""GPU smoke test for the running avatar engine (port 8010): speaks a sentence and a paragraph, records time-to-first-frame,
fps, VRAM and the interrupt latency, and saves a short mp4 (with audio) plus a few frames under data/avatar/samples/.
It only talks to the engine over HTTP/WebSocket: no microphone, no speech recognition.

    .venv\Scripts\python.exe scripts\avatar_engine_smoke.py [--url http://127.0.0.1:8010] [--replica default] [--emotion warm]
Needs `websockets` (in ARIA's .venv). ffmpeg is used for the mp4 if found (PATH or imageio-ffmpeg)."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "avatar" / "samples"
SHORT = "Hello, I am ARIA, your financial companion."
LONG = ("Your portfolio gained two point four percent this quarter, driven mostly by banking and information technology holdings. "
        "I would suggest rebalancing slightly towards debt funds, since market volatility has increased and your goal is only three years away.")


def http_json(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)


def vram_mb() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
        return int(out.split()[0])
    except Exception:
        return -1


async def run_utterance(ws, text: str, emotion: str, interrupt_after: float | None = None) -> dict:
    """Speak and collect everything until the metrics event (or idle after an interrupt)."""
    frames, audio, events = [], [], []
    t_send = time.perf_counter()
    await ws.send(json.dumps({"type": "speak", "text": text, "emotion": emotion}))
    first_speech_frame = None
    speaking = False
    t_int = t_idle = last_audio_rx = None
    peak_vram = vram_mb()
    n_poll = 0
    while True:
        msg = await asyncio.wait_for(ws.recv(), 30)
        now = time.perf_counter()
        if isinstance(msg, bytes):
            typ, seq, ts = struct.unpack_from("<BII", msg)
            if typ == 1:
                frames.append((ts, msg[9:], speaking))
                if speaking and first_speech_frame is None:
                    first_speech_frame = now - t_send
            else:
                sr = struct.unpack_from("<I", msg, 9)[0]
                audio.append((ts, sr, msg[13:]))
                last_audio_rx = now
            n_poll += 1
            if n_poll % 40 == 0:
                peak_vram = max(peak_vram, vram_mb())
            if interrupt_after is not None and t_int is None and first_speech_frame is not None and now - t_send - first_speech_frame > interrupt_after:
                t_int = time.perf_counter()
                await ws.send(json.dumps({"type": "interrupt"}))
            continue
        ev = json.loads(msg)
        events.append(ev)
        if ev.get("type") == "state":
            if ev["value"] == "speaking":
                speaking = True
            if ev["value"] == "idle" and t_int is not None:
                t_idle = now
                audio_after = 0
                t_end = now + 0.5
                while time.perf_counter() < t_end:          # anything still arriving after idle?
                    try:
                        m = await asyncio.wait_for(ws.recv(), 0.1)
                    except asyncio.TimeoutError:
                        continue
                    if isinstance(m, bytes) and m[0] == 2:
                        audio_after += 1
                return {"interrupt_to_idle_ms": round((t_idle - t_int) * 1000), "audio_chunks_after_idle": audio_after,
                        "ttfb_ms_client": round(first_speech_frame * 1000), "events": events}
            if ev["value"] == "unavailable":
                raise SystemExit(f"engine unavailable: {ev.get('reason')}")
        if ev.get("type") == "metrics" and interrupt_after is None:
            speech = [f for f in frames if f[2]]
            span = (speech[-1][0] - speech[0][0]) / 1000 if len(speech) > 1 else 0
            return {"ttfb_ms_client": round(first_speech_frame * 1000), "server_metrics": ev, "speech_frames": len(speech),
                    "client_fps_during_speech": round((len(speech) - 1) / span, 1) if span else 0, "vram_peak_mb": peak_vram,
                    "frames": frames, "audio": audio, "events": events}


def write_sample(name: str, res: dict) -> str | None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    speech = [f for f in res["frames"] if f[2]]
    if not speech:
        return None
    t0 = max(speech[0][0] - 300, 0)
    t1 = speech[-1][0] + 400
    d = SAMPLES / f"{name}_frames"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    vf = [f for f in res["frames"] if t0 <= f[0] <= t1]
    n = int((t1 - t0) / 40)
    j = 0
    for i in range(n):                                  # constant 25 fps from the timestamps
        while j + 1 < len(vf) and vf[j + 1][0] <= t0 + i * 40:
            j += 1
        (d / f"{i:05d}.jpg").write_bytes(vf[j][1])
    sr = res["audio"][0][1]
    pcm = bytearray(b"\x00\x00" * int((t1 - t0) / 1000 * sr))
    for ts, _, data in res["audio"]:
        off = int((ts - t0) / 1000 * sr) * 2
        if off >= 0:
            pcm[off:off + len(data)] = data[:max(0, len(pcm) - off)]
    wav = SAMPLES / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr), w.writeframes(bytes(pcm))
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return str(d)
    mp4 = SAMPLES / f"{name}.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", "25", "-i", str(d / "%05d.jpg"), "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(mp4)], check=True)
    return str(mp4)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--replica", default="default")
    ap.add_argument("--emotion", default="warm")
    ap.add_argument("--tag", default="", help="prefix for the sample file names")
    a = ap.parse_args()
    health = http_json(a.url + "/health")
    print("health:", json.dumps(health))
    if not health.get("ready"):
        raise SystemExit("engine not ready: " + str(health.get("detail")))
    base_vram = vram_mb()
    ws_url = a.url.replace("http", "ws", 1) + f"/stream?replica_id={a.replica}&takeover=1"
    report = {"vram_before_mb": base_vram}
    async with websockets.connect(ws_url, max_size=None) as ws:
        await asyncio.sleep(1.0)
        for name, text in (("short", SHORT), ("paragraph", LONG)):
            r = await run_utterance(ws, text, a.emotion)
            mp4 = write_sample(a.tag + name, r)
            report[name] = {k: v for k, v in r.items() if k not in ("frames", "audio", "events")} | {"sample": mp4}
            print(name, json.dumps(report[name]))
            await asyncio.sleep(1.0)
        r = await run_utterance(ws, LONG, a.emotion, interrupt_after=1.2)
        report["interrupt"] = {k: v for k, v in r.items() if k != "events"}
        print("interrupt", json.dumps(report["interrupt"]))
    report["health_after"] = http_json(a.url + "/health")
    out = SAMPLES / f"{a.tag}smoke_report.json"
    SAMPLES.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print("report:", out)


if __name__ == "__main__":
    asyncio.run(main())
