"""In-process run of qa_matrix.CASES (the same table run_matrix.py uses against a live instance).
Skips `net` cases (they would reach Yahoo/AMFI) and the chat cases that need a model. Rule checked for every case:
status in the expected set, and no stack trace / SQLAlchemy / path leak in the body."""
import os

import pytest
from fastapi.testclient import TestClient

from api.main import app
from qa_matrix import CASES, covered_ops, expected_ops_from_openapi
from run_matrix import materialise

os.environ["ARIA_APP_ORIGIN"] = "http://localhost:8012"  # the matrix sends this Origin to /api/feedback
NEEDS_MODEL = {"chat-valid", "chat-injection", "chat-bad-mode"}
client = TestClient(app, raise_server_exceptions=False)  # a 500 must show up as a status, like in production


@pytest.mark.parametrize("case", [c for c in CASES if not c["net"] and c["id"] not in NEEDS_MODEL], ids=lambda c: c["id"])
def test_case(case):
    method, tmpl = case["op"].split(" ", 1)
    req = materialise(case["req"])
    path = req.pop("path", tmpl)
    r = client.request(method, path, **req)
    leak = [s for s in ("Traceback", 'File "', "sqlalchemy.exc", "site-packages") if s in r.text]
    assert not leak, f"{case['id']}: leaks {leak}"
    assert r.status_code in case["ok"], f"{case['id']} (known={case['known']}): {r.status_code} not in {sorted(case['ok'])}: {r.text[:200]}"


def test_matrix_covers_every_openapi_operation():
    missing = sorted(o for o in expected_ops_from_openapi(app.openapi()) - covered_ops() if "/api/conversations" not in o)
    assert not missing, f"operations without a matrix case: {missing}"
