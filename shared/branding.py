"""Self-contained ARIA branding for downloadable HTML and browser-rendered PDFs."""
import base64
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def mark_data_uri() -> str:
    path = Path(__file__).resolve().parents[1] / "web/public/brand/aria-mark-128.png"
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""  # Missing optional artwork must not make a financial report unavailable.


def report_brand() -> str:
    mark = mark_data_uri()
    image = f'<img src="{mark}" alt="" width="44" height="44" style="object-fit:contain">' if mark else ""
    return (f'<div class="aria-report-brand" role="img" aria-label="ARIA" '
            f'style="display:flex;align-items:center;gap:12px;margin-bottom:20px">{image}'
            '<div><div style="font-size:22px;letter-spacing:.22em;font-weight:600">ARIA</div>'
            '<div style="font-size:9px;letter-spacing:.1em;opacity:.8">AI FOR REAL INSIGHTS &amp; ANALYSIS</div></div></div>')
