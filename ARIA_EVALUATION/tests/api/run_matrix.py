"""Run the endpoint matrix against a live isolated instance and print/write a JSON result.

    python ARIA_EVALUATION/tests/api/run_matrix.py http://127.0.0.1:8012 out.json [cookie_header]

Never point this at a real data directory; use an instance started with DB_URL=sqlite:///<scratch>.db.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from qa_matrix import CASES  # noqa: E402


def materialise(req: dict) -> dict:
    out = {}
    for k, v in req.items():
        if k == "files":
            out[k] = {n: (t[0], t[1]() if callable(t[1]) else t[1], t[2]) for n, t in v.items()}
        else:
            out[k] = v() if callable(v) else v
    return out


def run_case(client: httpx.Client, case: dict, path_of: dict) -> dict:
    method, tmpl = case["op"].split(" ", 1)
    req = materialise(case["req"])
    path = req.pop("path", tmpl)
    t = time.perf_counter()
    try:
        r = client.request(method, path, timeout=60, **req)
        status, text = r.status_code, r.text[:20000]
    except Exception as exc:  # transport failure counts as a failure of the case
        status, text = -1, f"{type(exc).__name__}: {exc}"
    ms = round((time.perf_counter() - t) * 1000)
    leak = any(s in text for s in ("Traceback", 'File "', "sqlalchemy.exc", "site-packages"))
    ok = status in case["ok"] or (case["net"] and status == 503)
    return {"id": case["id"], "op": case["op"], "kind": case["kind"], "status": status, "ok": ok and not leak,
            "leak": leak, "ms": ms, "known": case["known"], "expected": sorted(case["ok"]), "body": text[:200]}


if __name__ == "__main__":
    base, out = sys.argv[1], sys.argv[2]
    headers = {"origin": base}
    if len(sys.argv) > 3:
        headers["cookie"] = sys.argv[3]
    with httpx.Client(base_url=base) as client:
        results = [run_case(client, c, {}) for c in CASES]
    Path(out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    bad = [r for r in results if not r["ok"]]
    print(f"{len(results)} cases, {len(bad)} outside expectation")
    for r in bad:
        print(r["status"], r["id"], r["op"], "expected", r["expected"], "known=" + str(r["known"]), "|", r["body"][:120].replace("\n", " "))
