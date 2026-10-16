"""Fingerprint backend source without importing configuration or opening a DB."""
import hashlib
from pathlib import Path


def backend_revision(root: Path | None = None) -> str:
    root = root or Path(__file__).resolve().parents[1]
    paths = [path for folder in ("ai", "api", "config", "core", "modules", "shared")
             for path in (root / folder).rglob("*.py") if "__pycache__" not in path.parts]
    paths.extend(path for name in ("requirements.txt", "requirements-security.txt") if (path := root / name).is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
