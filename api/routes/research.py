"""Saved equity research reports: history, viewing, download, regenerate, delete.

Reports are created by the chat pipeline (modules/equity_research/intelligence) and stored by
shared/user_store.py. ARIA has no accounts, so every call carries the device-level ``owner_id``
(a random UUID the frontend keeps in localStorage) and only that owner's reports are visible.
The GET endpoints take it as a query parameter so the same URLs work for an <iframe> and a plain
download link, neither of which can send custom headers.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/research", tags=["research"])

_FORMATS = {
    "html": ("text/html; charset=utf-8", "html"),
    "pdf": ("application/pdf", "pdf"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "json": ("application/json", "json"),
}


class OwnerRequest(BaseModel):
    owner_id: str


def _load(owner_id: str, report_id: str) -> dict[str, Any]:
    from shared.user_store import get_research_report

    report = get_research_report(owner_id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.get("/reports")
def list_reports(owner_id: str, symbol: str | None = None) -> list[dict[str, Any]]:
    from shared.user_store import list_research_reports

    return list_research_reports(owner_id, symbol)


@router.get("/reports/{report_id}")
def get_report(report_id: str, owner_id: str) -> dict[str, Any]:
    return _load(owner_id, report_id)


def _render(report: dict, kind: str | None = None, **kw) -> str:
    from modules.equity_research.intelligence.fund import render_fund_html
    from modules.equity_research.intelligence.report_html import render_html

    return render_fund_html(report, **kw) if report.get("kind") == "fund_analysis" else render_html(report, kind, **kw)


def _kind(kind: str | None) -> str | None:
    from modules.equity_research.intelligence.report_html import KINDS

    if kind and kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(KINDS)}")
    return kind


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def view_report(report_id: str, owner_id: str, kind: str | None = None, print: bool = False) -> HTMLResponse:
    from modules.equity_research.intelligence.report_html import render_html

    return HTMLResponse(_render(_load(owner_id, report_id), _kind(kind), printable=print, autoprint=print))


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, owner_id: str, format: str = "html", kind: str | None = None) -> Response:
    from modules.equity_research.intelligence.report_html import render_html
    from modules.equity_research.intelligence.report_pdf import render_pdf

    if format not in _FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(_FORMATS)}")
    kind = _kind(kind)
    report = _load(owner_id, report_id)
    if format == "pdf":
        pdf = render_pdf(_render(report, kind))
        if pdf is None:
            raise HTTPException(status_code=501, detail="PDF export needs Chrome or Edge installed on the server (or set ARIA_PDF_BROWSER). Download the HTML and use Print > Save as PDF instead.")
    body = {"pdf": lambda: pdf, "html": lambda: _render(report, kind, printable=True), "md": lambda: report["markdown"], "json": lambda: json.dumps(report, indent=2)}[format]()
    media_type, ext = _FORMATS[format]
    meta = report["meta"]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{meta['symbol']}_{kind or report.get('kind') or 'equity_research'}_v{meta['version']}_{meta['created_at'][:10]}")
    return Response(body, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{stem}.{ext}"'})


@router.post("/reports/{report_id}/regenerate")
def regenerate_report(report_id: str, req: OwnerRequest) -> dict[str, Any]:
    """Re-run the analysis for the same company on fresh data and save it as the next version."""
    from modules.equity_research.intelligence.data import Target
    from modules.equity_research.intelligence.pipeline import run_research
    from shared.user_store import current_owner

    old = _load(req.owner_id, report_id)
    if old.get("kind") == "fund_analysis":
        raise HTTPException(status_code=400, detail="Ask ARIA for the fund analysis again to create a new version.")
    symbol = old["company"]["symbol"]
    token = current_owner.set(req.owner_id)
    try:
        result = run_research("", user_id=req.owner_id, target=Target(re.sub(r"\.(NS|BO)$", "", symbol), symbol, old["company"]["name"]), kind=old.get("kind"))
    finally:
        current_owner.reset(token)
    if not result.get("report_id"):
        raise HTTPException(status_code=502, detail="The new report could not be generated or saved.")
    return {"report_id": result["report_id"], "meta": result["report"]["meta"]}


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, owner_id: str) -> dict[str, str]:
    from shared.user_store import delete_research_report

    if not delete_research_report(owner_id, report_id):
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"status": "deleted"}
