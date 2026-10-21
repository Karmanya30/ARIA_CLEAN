"""Mock of the local avatar engine (port 8010) for testing the web client without a GPU.

Serves the same protocol: GET /health, /replicas (+POST/DELETE/preview) and WebSocket /stream with JPEG frames,
16-bit PCM audio, and state/caption/metrics events. The "voice" is a synthetic tone per word and the mouth opens with
its loudness, so audio/video sync is easy to see.

    python scripts/avatar_mock_engine.py [--port 8010] [--big-endian] [--json-rate] [--unavailable]

Default framing matches avatar_engine/protocol.py (little-endian header, audio payload = u32 sample_rate + PCM).
--big-endian --json-rate give the framing from the original brief (rate announced once in an audio_format event).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import struct
import time
import uuid

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from PIL import Image, ImageDraw

SAMPLE_RATE = 16000
FPS = 25
TICK = 1 / FPS
CHUNK = SAMPLE_RATE // FPS  # 640 samples per frame
LEAD = 0.15  # seconds the server runs ahead of real time

app = FastAPI()
OPTS = argparse.Namespace(little=True, json_rate=False, unavailable=False)
REPLICAS: dict[str, dict] = {"mock-default": {"name": "Mock presenter", "image": None}}


def face(size: int = 320, mouth: float = 0.0, blink: bool = False, t: int = 0, hue: int = 210, label: str = "MOCK") -> bytes:
    img = Image.new("RGB", (size, size), (14, 22, 33))
    d = ImageDraw.Draw(img)
    c = size // 2
    d.ellipse([c - 110, c - 130, c + 110, c + 120], fill=(236, 200, 170), outline=(120, 90, 70), width=3)
    for dx in (-45, 45):
        if blink:
            d.line([c + dx - 18, c - 30, c + dx + 18, c - 30], fill=(40, 30, 30), width=4)
        else:
            d.ellipse([c + dx - 16, c - 46, c + dx + 16, c - 14], fill="white", outline=(40, 30, 30), width=2)
            d.ellipse([c + dx - 7, c - 38, c + dx + 7, c - 22], fill=(40, 60, 90))
    h = 4 + int(mouth * 56)
    d.ellipse([c - 36, c + 40 - h // 2, c + 36, c + 40 + h // 2], fill=(120, 40, 50), outline=(70, 20, 30), width=3)
    # moving sync bar + frame counter so lag between sound and picture is visible
    d.rectangle([10, size - 22, 10 + (t * 6) % (size - 20), size - 12], fill=(62, 207, 142))
    d.text((10, 8), f"{label} f{t}", fill=(200, 215, 230))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def synth(text: str, emotion: str) -> np.ndarray:
    base = {"happy": 220, "empathetic": 150, "serious": 120}.get(emotion, 180)
    parts: list[np.ndarray] = []
    for i, word in enumerate(text.split()):
        n = int(SAMPLE_RATE * min(0.5, 0.06 + 0.035 * len(word)))
        tt = np.arange(n) / SAMPLE_RATE
        f = base * (1 + 0.15 * math.sin(i * 1.7))
        env = np.sin(np.pi * np.arange(n) / n) ** 0.7
        wave = (np.sin(2 * np.pi * f * tt) + 0.4 * np.sin(2 * np.pi * 2 * f * tt)) * env * 0.35
        parts.append(wave)
        parts.append(np.zeros(int(SAMPLE_RATE * 0.045)))
    out = np.concatenate(parts) if parts else np.zeros(CHUNK)
    pad = (-len(out)) % CHUNK
    return np.concatenate([out, np.zeros(pad)])


def pack(kind: int, seq: int, ts: int, payload: bytes) -> bytes:
    if kind == 2 and not OPTS.json_rate:
        payload = struct.pack("<I", SAMPLE_RATE) + payload
    return struct.pack("<BII" if OPTS.little else ">BII", kind, seq, ts) + payload


@app.get("/health")
def health():
    return {"status": "ok", "backend": "mock", "gpu": "none (mock)", "vram_used_mb": 0, "fps": FPS, "replica_default": "mock-default"}


@app.get("/replicas")
def replicas():
    return [{"replica_id": k, "name": v["name"], "preview_url": f"/replicas/{k}/preview"} for k, v in REPLICAS.items()]


@app.post("/replicas")
async def create_replica(file: UploadFile = File(...), name: str = Form("")):
    data = await file.read()
    if len(data) > 60 * 1024 * 1024:
        raise HTTPException(413, "File too large")
    if not (file.content_type or "").startswith(("image/", "video/")):
        raise HTTPException(415, "Upload a photo or a short video")
    await asyncio.sleep(1.2)  # upload "processing" so progress UI is visible
    rid = uuid.uuid4().hex[:8]
    REPLICAS[rid] = {"name": name or file.filename or rid, "image": data if (file.content_type or "").startswith("image/") else None}
    return {"replica_id": rid}


@app.delete("/replicas/{rid}")
def delete_replica(rid: str):
    if rid not in REPLICAS:
        raise HTTPException(404, "No such face")
    del REPLICAS[rid]
    return {"ok": True}


@app.get("/replicas/{rid}/preview")
def preview(rid: str):
    r = REPLICAS.get(rid)
    if not r:
        raise HTTPException(404, "No such face")
    return Response(r["image"] or face(160, 0.3, label=rid[:6]), media_type="image/jpeg")


@app.websocket("/stream")
async def stream(ws: WebSocket, replica_id: str | None = None):
    await ws.accept()
    if OPTS.json_rate:
        await ws.send_text(json.dumps({"type": "audio_format", "sample_rate": SAMPLE_RATE}))
    if OPTS.unavailable:
        await ws.send_text(json.dumps({"type": "state", "value": "unavailable", "reason": "mock engine set to unavailable"}))
    else:
        await ws.send_text(json.dumps({"type": "state", "value": "idle"}))
    speech: dict = {"audio": None, "pos": 0, "emotion": "neutral", "captions": [], "t0": 0}
    seq = 0
    start = time.monotonic()

    async def producer():
        nonlocal seq
        n = 0
        last_state = "idle"
        while True:
            due = start + n * TICK - LEAD
            await asyncio.sleep(max(0.0, due - time.monotonic()))
            ts = int(n * TICK * 1000)
            audio = speech["audio"]
            amp = 0.0
            if audio is not None and speech["pos"] < len(audio):
                chunk = audio[speech["pos"]: speech["pos"] + CHUNK]
                speech["pos"] += CHUNK
                amp = float(np.sqrt(np.mean(chunk ** 2)) * 3.2)
                pcm = (np.clip(chunk, -1, 1) * 32767).astype("<i2").tobytes()
                await ws.send_bytes(pack(2, seq, ts, pcm))
                if last_state != "speaking":
                    last_state = "speaking"
                    await ws.send_text(json.dumps({"type": "state", "value": "speaking"}))
            elif last_state == "speaking":
                last_state = "idle"
                speech["audio"] = None
                await ws.send_text(json.dumps({"type": "state", "value": "idle"}))
            blink = (n % 90) < 4
            await ws.send_bytes(pack(1, seq, ts, face(mouth=min(amp, 1.0), blink=blink, t=n)))
            seq += 1
            n += 1

    task = asyncio.create_task(producer())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            elif kind == "interrupt":
                speech["audio"] = None
            elif kind == "speak" and not OPTS.unavailable:
                t0 = time.monotonic()
                await ws.send_text(json.dumps({"type": "state", "value": "thinking"}))
                await asyncio.sleep(0.25)  # pretend first-byte latency
                text = str(msg.get("text", ""))[:2000]
                audio = synth(text, str(msg.get("emotion", "neutral")))
                now_ms = int((time.monotonic() - start) * 1000)
                # captions positioned on the stream timeline: one per sentence, spread over the audio length
                sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
                total_ms = len(audio) / SAMPLE_RATE * 1000
                for i, s in enumerate(sentences):
                    a = now_ms + total_ms * i / len(sentences)
                    b = now_ms + total_ms * (i + 1) / len(sentences)
                    await ws.send_text(json.dumps({"type": "caption", "text": s, "t_start": int(a) + 170, "t_end": int(b) + 170}))
                speech.update(audio=audio, pos=0, emotion=msg.get("emotion", "neutral"))
                await ws.send_text(json.dumps({"type": "metrics", "ttfb_ms": int((time.monotonic() - t0) * 1000), "fps": FPS, "gen_ms": 12}))
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--big-endian", action="store_true", help="header integers big-endian")
    ap.add_argument("--json-rate", action="store_true", help="announce the sample rate in an audio_format event instead of inline")
    ap.add_argument("--unavailable", action="store_true", help="report state 'unavailable'")
    a = ap.parse_args()
    OPTS.little, OPTS.json_rate, OPTS.unavailable = not a.big_endian, a.json_rate, a.unavailable
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
