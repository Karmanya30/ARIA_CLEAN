r"""End-to-end check: offer/answer, POST /human echo, measure first audio/video and interrupt time.
    E:\LiveTalking\env\python.exe livetalking_adapter\smoke.py [http://127.0.0.1:8020]
Uses only the network (no microphone)."""
import asyncio
import json
import sys
import time

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020"
TEXT = "Hello, I am Aria. This is a short test of the local live talking avatar. It should keep speaking for a while so we can interrupt it."
st = {"a": 0, "v": 0, "audio_t": [], "last_loud": 0.0, "vt": []}


async def pump(track, kind):
    while True:
        f = await track.recv()
        now = time.time()
        if kind == "audio":
            x = f.to_ndarray().astype(np.float32)
            if np.abs(x).mean() > 30:  # int16 scale; silence frames are ~0
                st["a"] += 1; st["last_loud"] = now; st["audio_t"].append(now)
        else:
            st["v"] += 1; st["vt"].append(now)


async def post(s, path, body):
    async with s.post(BASE + path, json=body) as r:
        return await r.json()


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get(BASE + "/health") as r:
            print("health", await r.json())
        pc = RTCPeerConnection()
        pc.addTransceiver("audio", direction="recvonly"); pc.addTransceiver("video", direction="recvonly")
        tasks = []

        @pc.on("track")
        def on_track(t):
            tasks.append(asyncio.ensure_future(pump(t, t.kind)))
        await pc.setLocalDescription(await pc.createOffer())
        ans = await post(s, "/offer", {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
        sid = ans["sessionid"]
        await pc.setRemoteDescription(RTCSessionDescription(sdp=ans["sdp"], type=ans["type"]))
        await asyncio.sleep(3)
        v0 = st["v"]
        print("idle video frames in 3s:", v0)
        t0 = time.time()
        print("human", await post(s, "/human", {"sessionid": sid, "text": TEXT, "type": "echo", "interrupt": True}))
        while not st["audio_t"] and time.time() - t0 < 20:
            await asyncio.sleep(0.005)
        print(f"time to first audio: {st['audio_t'][0] - t0:.2f}s" if st["audio_t"] else "NO AUDIO")
        await asyncio.sleep(3)
        t1 = time.time()
        await post(s, "/interrupt_talk", {"sessionid": sid})
        await asyncio.sleep(2)
        print(f"interrupt: last loud audio {max(st['last_loud'] - t1, 0):.2f}s after request (includes jitter buffer)")
        print("audio frames", st["a"], "video frames", st["v"], "speaking after:", await post(s, "/is_speaking", {"sessionid": sid}))
        for t in tasks: t.cancel()
        await pc.close()


asyncio.run(main())
