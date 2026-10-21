r"""Run upstream LiveTalking (app.py) with ARIA's Piper TTS plugin, localhost-only, plus GET /health.

    E:\LiveTalking\env\python.exe -m livetalking_adapter.serve [extra upstream args]

Env knobs: LIVETALKING_DIR (default E:\LiveTalking\src), LT_MODEL, LT_AVATAR, LT_PORT, LT_BATCH,
LT_VOICE (Piper .onnx), LT_BIND (default 127.0.0.1).
Two idempotent text patches are applied to the upstream checkout (see upstream.patch): the TTS
table in BaseAvatar.__init__ is a local dict, so 'piper' cannot be injected at runtime.
"""
import os
import re
import runpy
import sys
from pathlib import Path

ARIA = Path(__file__).resolve().parents[1]
LT = Path(os.environ.get("LIVETALKING_DIR", r"E:\LiveTalking\src"))
PATCHES = [  # (file, marker already present, regex, replacement)
    ("avatars/base_avatar.py", "livetalking_adapter.piper_tts",
     r"([ \t]*)'edgetts': 'tts\.edge',(\r?\n)", r"\g<0>\1'piper': 'livetalking_adapter.piper_tts',\2"),
    ("app.py", "LT_BIND", r"'0\.0\.0\.0', opt\.listenport", "os.environ.get('LT_BIND', '127.0.0.1'), opt.listenport"),
]


def apply_patches():
    for rel, marker, rx, rep in PATCHES:
        p = LT / rel
        s = p.read_bytes().decode("utf-8")
        if marker in s:
            continue
        new, n = re.subn(rx, rep, s, count=1)
        if n != 1:
            raise SystemExit(f"upstream changed: cannot patch {rel} (see livetalking_adapter/upstream.patch)")
        p.write_bytes(new.encode("utf-8"))


def add_health():
    import server.routes as routes
    from aiohttp import web
    orig = routes.setup_routes

    async def health(request):
        from server.session_manager import session_manager
        o = request.app["opt"]
        n = sum(1 for s in session_manager.sessions.values() if s is not None)
        return web.json_response({"ready": True, "model": o.model, "avatar": o.avatar_id, "sessions": n})

    def setup_routes(app):  # runs after models are loaded, so a reachable /health means ready
        app.router.add_get("/health", health)
        orig(app)

    routes.setup_routes = setup_routes


def main():
    if not (LT / "app.py").is_file():
        raise SystemExit(f"LiveTalking not found at {LT} (set LIVETALKING_DIR)")
    os.chdir(LT)
    # spawn children re-import everything: PYTHONPATH carries the paths to them
    paths = [str(LT), str(ARIA)]
    os.environ["PYTHONPATH"] = os.pathsep.join(paths + [os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    sys.path[:0] = paths
    apply_patches()
    from livetalking_adapter.piper_tts import voice_path
    if not voice_path().is_file():
        raise SystemExit(f"Piper voice missing: {voice_path()} (set LT_VOICE)")
    args = ["--config", str(Path(__file__).with_name("livetalking.yaml"))]
    for env, flag in (("LT_MODEL", "--model"), ("LT_AVATAR", "--avatar_id"), ("LT_PORT", "--listenport"), ("LT_BATCH", "--batch_size")):
        if os.environ.get(env):
            args += [flag, os.environ[env]]
    sys.argv = ["app.py", *args, *sys.argv[1:]]
    add_health()
    runpy.run_path(str(LT / "app.py"), run_name="__main__")


if __name__ == "__main__":  # guard: spawn children import this module as __mp_main__
    main()
