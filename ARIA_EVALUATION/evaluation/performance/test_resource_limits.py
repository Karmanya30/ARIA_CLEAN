"""Does a long-lived WebSocket consume an admission slot of api/resource_limits.ResourceLimits (so that N open sockets make every HTTP /api call return 503)?
Self-contained: a tiny Starlette app wrapped by the real ResourceLimits (max_active=4, rate limiter off). No ARIA app, no network. Output: results/resource_limits.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RESULTS
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from api.resource_limits import ResourceLimits


async def ws(sock):
    await sock.accept()
    try:
        await sock.receive_text()          # held open until the client closes
    except Exception:
        pass


async def ping(request):
    return JSONResponse({"ok": True})

app = Starlette(routes=[WebSocketRoute("/api/live/ws", ws), Route("/api/ping", ping)])
c = TestClient(ResourceLimits(app, max_active=4, rate=0))
out = {"max_active": 4}
socks = []
try:
    for i in range(4):
        cm = c.websocket_connect("/api/live/ws"); socks.append(cm); cm.__enter__()
    r = c.get("/api/ping"); out["http_with_4_open_websockets"] = r.status_code; out["retry_after"] = r.headers.get("retry-after")
    socks.pop().__exit__(None, None, None)
    out["http_after_closing_one"] = c.get("/api/ping").status_code
finally:
    for s in socks:
        s.__exit__(None, None, None)
print(out)
(RESULTS / "resource_limits.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
