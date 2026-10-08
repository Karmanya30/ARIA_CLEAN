"""Send the table in tests/test_understand.py to a running API (POST /api/chat) and print domain + corrected_query.
Run: python scripts/live_understand.py [http://127.0.0.1:8000]"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_understand import ROWS  # noqa: E402

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
for i, (query, want) in enumerate(ROWS):
    body = json.dumps({"query": query, "session_id": f"live-understand-{i}", "owner_id": "live-understand"}).encode()
    req = urllib.request.Request(base + "/api/chat", body, {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=180))
    print(f"want={want:22} got={r.get('domain'):20} corrected={r.get('corrected_query')!r} | {query}")
