"""HTML -> PDF using a locally installed Chromium-family browser in headless mode.
No Python dependency; returns None when no browser is found so the API can say so plainly."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_CANDIDATES = ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")
_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def find_browser() -> str | None:
    override = os.getenv("ARIA_PDF_BROWSER")
    return override or next((p for p in (*(shutil.which(n) for n in _CANDIDATES), *_PATHS) if p and Path(p).exists()), None)


def render_pdf(html: str, timeout: int = 90) -> bytes | None:
    exe = find_browser()
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "r.html", Path(tmp) / "r.pdf"
        src.write_text(html, encoding="utf-8")
        try:
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}", src.as_uri()],
                           capture_output=True, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return out.read_bytes() if out.exists() and out.stat().st_size > 0 else None
