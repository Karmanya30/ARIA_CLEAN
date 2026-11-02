import base64
import hashlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import _CSP_REPORT, app


def test_every_response_has_a_content_security_policy():
    h = TestClient(app).get("/api/health").headers
    assert "frame-ancestors 'self'" in h["content-security-policy"] and "object-src 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"


def test_report_csp_allows_only_the_print_script_it_ships():
    src = Path("modules/equity_research/intelligence/report_html.py").read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", src).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in _CSP_REPORT  # change the script and this fails, instead of silently breaking print-on-open


def test_private_mode_writes_from_other_sites_are_refused():
    c = TestClient(app)
    body = {"session_id": "x" * 36, "monthly_income": 1}
    assert c.post("/api/profile", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/profile", json=body, headers={"Host": "evil.example"}).status_code == 403
    assert c.post("/api/profile", json=body, headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_basic_hardening_headers_are_sent():
    r = TestClient(app).get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
