"""Replica store on disk: data/avatar/replicas/<id>/{meta.json, source.<ext>, preview.jpg, prep.pkl}.
The backend does the heavy part (face detection, crop, landmarks, latents) via `prepare(source, dir) -> extra_meta`
and writes its own cache files into `dir`; the store only owns ids, metadata and cleanup."""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

DEFAULT_ID = "default"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ReplicaError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class ReplicaStore:
    def __init__(self, root: Path, prepare: Callable[[Path, Path], dict], default_source: Path | None = None):
        self.root, self.prepare, self.default_source = Path(root), prepare, default_source
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, rid: str) -> Path:
        if not _ID.match(rid or ""):
            raise ReplicaError("invalid replica id", 400)
        return self.root / rid

    def get(self, rid: str) -> dict:
        meta = self.path(rid) / "meta.json"
        if not meta.exists():
            raise ReplicaError(f"replica '{rid}' not found", 404)
        return json.loads(meta.read_text("utf-8"))

    def list(self) -> list[dict]:
        out = []
        for m in sorted(self.root.glob("*/meta.json")):
            try:
                out.append(json.loads(m.read_text("utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda r: (r["id"] != DEFAULT_ID, r.get("created", 0)))

    def create(self, filename: str, data: bytes, name: str | None = None, rid: str | None = None) -> dict:
        ext = Path(filename or "").suffix.lower()
        if ext not in IMAGE_EXT | VIDEO_EXT:
            raise ReplicaError("upload a photo (png/jpg/webp) or a short video (mp4/mov/webm)")
        if not data:
            raise ReplicaError("empty upload")
        rid = rid or uuid.uuid4().hex[:10]
        d = self.path(rid)
        d.mkdir(parents=True, exist_ok=True)
        src = d / f"source{ext}"
        src.write_bytes(data)
        try:
            extra = self.prepare(src, d)
        except Exception as exc:  # no face, unreadable file, ...: leave nothing half-made behind
            shutil.rmtree(d, ignore_errors=True)
            raise ReplicaError(f"could not build replica: {exc}") from exc
        meta = {"id": rid, "replica_id": rid, "preview_url": f"/replicas/{rid}/preview", "name": name or Path(filename).stem[:60], "kind": "video" if ext in VIDEO_EXT else "photo",
                "created": int(time.time()), "source": src.name, **extra}
        (d / "meta.json").write_text(json.dumps(meta), "utf-8")
        return meta

    def delete(self, rid: str) -> None:
        if rid == DEFAULT_ID:
            raise ReplicaError("the default replica cannot be deleted", 400)
        self.get(rid)
        shutil.rmtree(self.path(rid), ignore_errors=True)

    def ensure_default(self) -> dict | None:
        try:
            return self.get(DEFAULT_ID)
        except ReplicaError:
            if not self.default_source or not self.default_source.exists():
                return None
            m = self.create(self.default_source.name, self.default_source.read_bytes(), name="ARIA (default)", rid=DEFAULT_ID)
            return m

    def preview_path(self, rid: str) -> Path:
        self.get(rid)
        return self.path(rid) / "preview.jpg"
