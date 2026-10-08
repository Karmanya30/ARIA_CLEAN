"""Routing accuracy per intent for the typo / text-speak / Hinglish table in tests/test_understand.py (pipelines are stubs; no model,
network or microphone). Run: python scripts/understand_report.py"""
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("ARIA_WARMUP", "0")
os.environ.setdefault("FI_NEWS_RSS", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_understand import ROWS, route_label  # noqa: E402

score = defaultdict(lambda: [0, 0])
for query, want in ROWS:
    got = route_label(query)[0]
    score[want][0] += got == want
    score[want][1] += 1
    if got != want:
        print(f"MISS want={want} got={got}")  # the label only: message text is never printed
for intent, (ok, n) in sorted(score.items()):
    print(f"{intent:24} {ok}/{n}")
total = sum(v[0] for v in score.values()), sum(v[1] for v in score.values())
print(f"{'ALL':24} {total[0]}/{total[1]} = {total[0] / total[1]:.0%}")
