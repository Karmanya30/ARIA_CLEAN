"""HTTP + WebSocket API of the avatar engine (default port 8010).

   GET  /health                  status, backend, gpu, vram, fps, default replica
   POST /replicas (multipart)    file=<photo|video>, name=<label>  -> replica meta
   GET  /replicas | DELETE /replicas/{id} | GET /replicas/{id}/preview
   POST /speak                   {text, voice?, emotion?, replica_id?} -> {id, stream_url}
   WS   /stream?replica_id=&speak_id=&w=&h=&framing=&bg=&takeover=1
Run:  python -m avatar_engine.server   (use the MuseTalk environment's python, see scripts/start_avatar_engine.bat)"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from . import config
from .compositor import FRAMINGS, StageOpts
from .engine import Engine
from .replicas import DEFAULT_ID, ReplicaError
from .session import Session

MAX_UPLOAD = 80 * 1024 * 1024


class SpeakBody(BaseModel):
    text: str
    voice: str | None = None
    emotion: str | None = None
    style: dict | str | None = None
    replica_id: str = DEFAULT_ID



def make_backend():
    if config.BACKEND == "fake":
        from .backend_fake import FakeBackend
        return FakeBackend()
    from .backend_musetalk import MuseTalkBackend
    return MuseTalkBackend()


def create_app(engine: Engine | None = None, autostart: bool = True) -> FastAPI:
    eng = engine or Engine(make_backend())

    @asynccontextmanager
    async def lifespan(app):
        if autostart:
            eng.start_async()
        yield
        if eng.session:
            await eng.session.close()

    app = FastAPI(title="ARIA avatar engine", lifespan=lifespan)
    app.state.engine = eng
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ReplicaError)
    async def _replica_error(_, exc: ReplicaError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/health")
    def health():
        return eng.health()

    # ---------------------------------------------------------------- replicas
    @app.get("/replicas")
    def list_replicas():
        return eng.store.list()

    @app.post("/replicas")
    async def create_replica(file: UploadFile | None = File(None), image: UploadFile | None = File(None), name: str | None = Form(None)):
        file = file or image
        if file is None:
            raise HTTPException(400, "upload a photo or short video as multipart field 'file' (or 'image')")
        if not eng.ready:
            raise HTTPException(503, f"engine not ready ({eng.status})")
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "upload too large (max 80 MB)")
        meta = await asyncio.get_running_loop().run_in_executor(None, eng.store.create, file.filename or "", data, name)
        return meta

    @app.delete("/replicas/{rid}")
    def delete_replica(rid: str):
        if eng.session and eng.session.rid == rid:
            raise HTTPException(409, "replica is in use by the live session")
        eng.store.delete(rid)
        eng.forget_replica(rid)
        return {"deleted": rid}

    @app.get("/replicas/{rid}/preview")
    def preview(rid: str):
        p = eng.store.preview_path(rid)
        if not p.exists():
            raise HTTPException(404, "no preview")
        return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    # ---------------------------------------------------------------- speech
    @app.post("/speak")
    def speak(body: SpeakBody):
        if not body.text.strip():
            raise HTTPException(400, "text is empty")
        eng.store.get(body.replica_id)
        tok = eng.new_speak_token({"type": "speak", **body.model_dump(exclude={"replica_id"}), "_rid": body.replica_id})
        return {"id": tok, "stream_url": f"/stream?speak_id={tok}&replica_id={body.replica_id}", "expires_s": 30}

    @app.websocket("/stream")
    async def stream(ws: WebSocket, replica_id: str = DEFAULT_ID, speak_id: str | None = None, w: int = config.OUT_W, h: int = config.OUT_H,
                     framing: str = "bust", bg: str = "original", takeover: int = 0):
        await ws.accept()

        async def refuse(reason: str, code: int = 1013):
            await ws.send_text(json.dumps({"type": "state", "value": "unavailable", "reason": reason}))
            await ws.close(code)

        if not eng.ready:
            return await refuse(f"engine not ready: {eng.error or eng.status}")
        try:
            eng.store.get(replica_id)
        except ReplicaError as exc:
            return await refuse(str(exc), 1008)
        with eng.session_lock:
            old = eng.session
        if old is not None and not takeover:
            return await refuse("busy: another live session is active (reconnect with takeover=1 to replace it)")
        if old is not None:
            await old.send_json({"type": "state", "value": "unavailable", "reason": "replaced by a newer session"})
            await old.close()
        opts = StageOpts(min(max(w, 128), 1024), min(max(h, 128), 1024), framing if framing in FRAMINGS else "bust", bg, config.JPEG_QUALITY)
        sess = Session(eng, ws, replica_id, opts)
        eng.session = sess
        try:
            await sess.start()
            if speak_id and speak_id in eng.speak_tokens:
                _, payload = eng.speak_tokens.pop(speak_id)
                await sess.handle(payload)
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("text"):
                    try:
                        msg = json.loads(m["text"])
                    except ValueError:
                        continue
                    if isinstance(msg, dict):
                        await sess.handle(msg)
                if sess.closed:
                    break
        except WebSocketDisconnect:
            pass
        except ReplicaError as exc:
            await sess.send_json({"type": "state", "value": "unavailable", "reason": str(exc)})
        except Exception as exc:
            logger.exception("stream failed")
            await sess.send_json({"type": "state", "value": "unavailable", "reason": f"engine error: {exc}"})
        finally:
            await sess.close()
            if eng.session is sess:
                eng.session = None
            try:
                await ws.close()
            except Exception:
                pass

    @app.get("/demo", response_class=HTMLResponse)
    def demo():
        return (Path(__file__).parent / "demo.html").read_text("utf-8")

    return app


def main() -> None:
    import uvicorn
    config.LOG_DIR.mkdir(exist_ok=True)
    logger.add(config.LOG_DIR / "avatar_engine.log", rotation="10 MB", retention=3, encoding="utf-8")
    for s in (sys.stdout, sys.stderr):
        getattr(s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace")
    uvicorn.run(create_app(), host="127.0.0.1", port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
