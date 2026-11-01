"""Fails if any Semantic Router example utterance equals a benchmark query (case/punctuation-insensitive)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.intent.taxonomy import ROUTE_EXAMPLES  # noqa: E402

norm = lambda t: re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()
bench = {norm(json.loads(l)["query"]) for l in (Path(__file__).parent / "benchmark_v1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
hits = [(r, u) for r, us in ROUTE_EXAMPLES.items() for u in us if norm(u) in bench]
print(f"{sum(len(v) for v in ROUTE_EXAMPLES.values())} route examples, {len(bench)} benchmark queries, exact overlaps: {len(hits)}")
for h in hits:
    print("  OVERLAP", h)
sys.exit(1 if hits else 0)
