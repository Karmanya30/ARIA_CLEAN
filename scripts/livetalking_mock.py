"""Mock of the LiveTalking service API (port 8020) for developing/testing the ARIA LiveTalking panel without the GPU service.

  python scripts/livetalking_mock.py [--port 8020] [--max-session 2] [--fail] [--delay-offer SECONDS]

With aiortc + aiohttp installed it answers /offer with a real WebRTC session (a synthetic moving square, brighter while
"speaking", plus a tone while speaking). Without aiortc (or with --fail) every offer fails with code -1, which is how the
panel's fallback is verified. Endpoints mirror upstream: POST /offer /human /interrupt_talk /is_speaking, GET /sse /health
/api/admin/sessions. Speaking lasts 0.06 s per character. Test tool only: not part of ARIA's runtime.
"""
import argparse
import asyncio
import json
import math
import time
import uuid

from aiohttp import web

try:
    import numpy as np
    from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from av import AudioFrame, VideoFrame
    HAVE_RTC = True
except ImportError:  # offers will fail: used to check the fallback
    HAVE_RTC = False

SESSIONS: dict[str, "Session"] = {}


class Session:
    def __init__(self, sid):
        self.sid, self.until, self.queues, self.pc = sid, 0.0, [], None

    def speaking(self):
        return time.time() < self.until

    def say(self, text):
        self.until = time.time() + max(0.5, 0.06 * len(text))
        self.emit({"status": "start", "text": text})
        asyncio.get_event_loop().call_later(self.until - time.time(), self._end, self.until)

    def _end(self, until):
        if self.until == until and not self.speaking():
            self.emit({"status": "end"})

    def stop(self):
        was = self.speaking()
        self.until = 0.0
        if was:
            self.emit({"status": "end"})

    def emit(self, ev):
        for q in self.queues:
            q.put_nowait(json.dumps(ev))


def ok(data=None):
    return web.json_response({"code": 0, "msg": "ok", **({"data": data} if data is not None else {})})


def err(msg):
    return web.json_response({"code": -1, "msg": msg})


if HAVE_RTC:
    class Face(VideoStreamTrack):
        def __init__(self, s):
            super().__init__()
            self.s, self.n = s, 0

        async def recv(self):
            pts, tb = await self.next_timestamp()
            self.n += 1
            img = np.full((512, 512, 3), (30, 50, 80), np.uint8)
            x = int(60 + 180 * (1 + math.sin(self.n / 12)))
            img[200:312, x:x + 112] = (60, 200, 140) if self.s.speaking() else (150, 160, 175)
            f = VideoFrame.from_ndarray(img, format="rgb24")
            f.pts, f.time_base = pts, tb
            return f

    class Voice(AudioStreamTrack):
        def __init__(self, s):
            super().__init__()
            self.s, self.t = s, 0

        async def recv(self):
            frame = await super().recv()  # paces and stamps silence
            if self.s.speaking():
                n = frame.samples
                tone = (3000 * np.sin(2 * np.pi * 330 * (self.t + np.arange(n)) / 48000)).astype(np.int16)
                self.t += n
                out = AudioFrame.from_ndarray(np.repeat(tone[None, :], 2, axis=0).T.reshape(1, -1), format="s16", layout="stereo")
                out.sample_rate, out.pts, out.time_base = 48000, frame.pts, frame.time_base
                return out
            return frame


async def offer(request):
    a = request.app["args"]
    if a.delay_offer:
        await asyncio.sleep(a.delay_offer)
    if a.fail or not HAVE_RTC:
        return err("mock: offers disabled")
    if len(SESSIONS) >= a.max_session:
        return err("max session reached")
    p = await request.json()
    sid = uuid.uuid4().hex[:8]
    s = SESSIONS[sid] = Session(sid)
    pc = s.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))  # no STUN: its lookup stalls the answer offline

    @pc.on("connectionstatechange")
    async def _():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            SESSIONS.pop(sid, None)
            await pc.close()

    await pc.setRemoteDescription(RTCSessionDescription(sdp=p["sdp"], type=p["type"]))
    pc.addTrack(Face(s))
    pc.addTrack(Voice(s))
    await pc.setLocalDescription(await pc.createAnswer())
    return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "sessionid": sid})


async def session_of(request):
    p = await request.json()
    return SESSIONS.get(str(p.get("sessionid", ""))), p


async def human(request):
    s, p = await session_of(request)
    if not s:
        return err("session not found")
    if p.get("interrupt"):
        s.stop()
    if p.get("type") == "echo":
        s.say(p["text"])
    return ok()


async def interrupt_talk(request):
    s, _ = await session_of(request)
    if not s:
        return err("session not found")
    s.stop()
    return ok()


async def is_speaking(request):
    s, _ = await session_of(request)
    return ok(s.speaking()) if s else err("session not found")


async def sse(request):
    s = SESSIONS.get(request.query.get("sessionid", ""))
    if not s:
        return err("session not found")
    r = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await r.prepare(request)
    q = asyncio.Queue()
    s.queues.append(q)
    try:
        while True:
            await r.write(f"data: {await q.get()}\n\n".encode())
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        s.queues.remove(q)
    return r


async def admin_sessions(request):
    return ok({"sessions": [{"sessionid": k, "speaking": v.speaking()} for k, v in SESSIONS.items()]})


async def health(request):
    return web.json_response({"ok": True, "mock": True, "rtc": HAVE_RTC, "sessions": len(SESSIONS)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--max-session", type=int, default=2)
    ap.add_argument("--fail", action="store_true")
    ap.add_argument("--delay-offer", type=float, default=0)
    args = ap.parse_args()
    app = web.Application()
    app["args"] = args
    app.add_routes([web.post("/offer", offer), web.post("/human", human), web.post("/interrupt_talk", interrupt_talk),
                    web.post("/is_speaking", is_speaking), web.get("/sse", sse), web.get("/health", health),
                    web.get("/api/admin/sessions", admin_sessions)])
    web.run_app(app, host="127.0.0.1", port=args.port, print=lambda *_: print(f"livetalking mock on :{args.port} rtc={HAVE_RTC}", flush=True))


if __name__ == "__main__":
    main()
