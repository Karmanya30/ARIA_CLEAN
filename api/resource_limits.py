"""Per-worker admission and bounded body buffering before multipart/JSON parsing.

Deployment-wide quotas still belong at the reverse proxy. Forwarded client
headers are deliberately ignored; they are not an authenticated identity.
"""
import asyncio
from collections import OrderedDict
import os
from tempfile import SpooledTemporaryFile
import time

from starlette.responses import JSONResponse


class ResourceLimits:
    def __init__(self, app, *, max_bytes=None, max_active=None, rate=None, body_timeout=30):
        self.app = app
        self.max_bytes = max_bytes if max_bytes is not None else int(os.getenv("ARIA_MAX_REQUEST_BYTES", 12 * 1024 * 1024))
        self.max_active = max_active if max_active is not None else int(os.getenv("ARIA_MAX_ACTIVE_REQUESTS", 16))
        self.rate = rate if rate is not None else int(os.getenv("ARIA_EXPENSIVE_REQUESTS_PER_MINUTE", 120))
        if self.max_bytes <= 0 or self.max_active <= 0 or self.rate < 0:
            raise ValueError("Invalid ARIA resource limits")
        self.body_timeout = body_timeout
        self.active = 0
        self.clients = OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not scope.get("path", "").startswith(("/api/", "/v1/", "/avatar/")):
            return await self.app(scope, receive, send)

        async def reject(status, detail):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1013})
            else:
                await JSONResponse({"detail": detail}, status_code=status,
                                   headers={"Retry-After": "60"} if status in (429, 503) else {})(scope, receive, send)

        # No await between the check and increment: atomic on the ASGI loop.
        if self.active >= self.max_active:
            return await reject(503, "ARIA is busy. Please try again shortly.")
        expensive = scope["type"] == "websocket" or scope.get("method") == "POST"
        if self.rate and expensive:
            peer = (scope.get("client") or ("unknown", 0))[0]
            now = time.monotonic()
            start, count = self.clients.pop(peer, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self.clients[peer] = (start, count + 1)
            if len(self.clients) > 4096:
                self.clients.popitem(last=False)
            if count >= self.rate:
                return await reject(429, "Too many requests. Please try again in a minute.")
        self.active += 1
        try:
            if scope["type"] == "websocket":
                return await self.app(scope, receive, send)
            lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
            try:
                if len(lengths) > 1 or (lengths and int(lengths[0]) < 0):
                    raise ValueError
                if lengths and int(lengths[0]) > self.max_bytes:
                    return await reject(413, "Request is too large.")
            except ValueError:
                return await reject(400, "Invalid Content-Length.")
            # Spool above 1 MB; never pass an unbounded/chunked upload to a parser.
            with SpooledTemporaryFile(max_size=1024 * 1024) as body:
                size = 0
                async def collect():
                    nonlocal size
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return False
                        chunk = message.get("body", b"")
                        size += len(chunk)
                        if size > self.max_bytes:
                            return None
                        body.write(chunk)
                        if not message.get("more_body", False):
                            return True
                try:
                    collected = await asyncio.wait_for(collect(), timeout=self.body_timeout)
                except TimeoutError:
                    return await reject(408, "Upload timed out. Please try again.")
                if collected is None:
                    return await reject(413, "Request is too large.")
                if collected is False:
                    return
                body.seek(0)
                remaining = size
                async def replay():
                    nonlocal remaining
                    if remaining < 0:
                        return await receive()
                    chunk = body.read(64 * 1024)
                    remaining -= len(chunk)
                    more = remaining > 0
                    if not more:
                        remaining = -1
                    return {"type": "http.request", "body": chunk, "more_body": more}
                await self.app(scope, replay, send)
        finally:
            self.active -= 1
