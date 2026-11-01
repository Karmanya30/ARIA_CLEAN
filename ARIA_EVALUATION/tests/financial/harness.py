"""Tiny comparison harness: every check is recorded (id, feature, case, kind, actual, expected, verdict) to JSON."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)


class Rec:
    def __init__(self, name: str, prefix: str):
        self.name, self.prefix, self.rows, self.n = name, prefix, [], 0

    def _add(self, feature, case, kind, actual, expected, ok, note=""):
        self.n += 1
        self.rows.append({"id": f"{self.prefix}-{self.n:03d}", "feature": feature, "case": case, "kind": kind,
                          "actual": _s(actual), "expected": _s(expected), "result": "PASS" if ok else "FAIL", "note": note})
        return ok

    def close(self, feature, case, kind, actual, expected, rel=1e-9, abs_=1e-9, note=""):
        """Numeric comparison against an independent reference."""
        if actual is None or expected is None:
            ok = actual is None and expected is None
        else:
            ok = math.isclose(float(actual), float(expected), rel_tol=rel, abs_tol=abs_)
        return self._add(feature, case, kind, actual, expected, ok, note)

    def eq(self, feature, case, kind, actual, expected, note=""):
        return self._add(feature, case, kind, actual, expected, actual == expected, note)

    def true(self, feature, case, kind, cond, note=""):
        return self._add(feature, case, kind, bool(cond), True, bool(cond), note)

    def raises(self, feature, case, kind, fn, exc, note=""):
        try:
            fn()
        except exc as e:  # noqa: PERF203
            return self._add(feature, case, kind, f"{type(e).__name__}: {str(e)[:80]}", f"raises {exc.__name__}", True, note)
        except Exception as e:
            return self._add(feature, case, kind, f"{type(e).__name__}: {str(e)[:80]}", f"raises {exc.__name__}", False, note)
        return self._add(feature, case, kind, "no exception", f"raises {exc.__name__}", False, note)

    def observe(self, feature, case, kind, value, note=""):
        """Not pass/fail: a recorded observation of behaviour (no oracle exists, or the behaviour is a documented choice)."""
        self.n += 1
        self.rows.append({"id": f"{self.prefix}-{self.n:03d}", "feature": feature, "case": case, "kind": kind,
                          "actual": _s(value), "expected": "-", "result": "OBSERVED", "note": note})

    def save(self):
        (OUT / f"{self.name}.json").write_text(json.dumps(self.rows, indent=1, ensure_ascii=False), encoding="utf8")
        p = sum(r["result"] == "PASS" for r in self.rows)
        f = sum(r["result"] == "FAIL" for r in self.rows)
        o = sum(r["result"] == "OBSERVED" for r in self.rows)
        print(f"{self.name}: {p} pass, {f} fail, {o} observed")
        for r in self.rows:
            if r["result"] == "FAIL":
                print("  FAIL", r["id"], r["feature"], "|", r["case"], "| actual", r["actual"], "| expected", r["expected"])


def _s(x):
    if isinstance(x, float):
        return float(f"{x:.10g}")
    if isinstance(x, (list, tuple)):
        return [_s(i) for i in x]
    if isinstance(x, dict):
        return {k: _s(v) for k, v in x.items()}
    return x if isinstance(x, (int, str, bool)) or x is None else str(x)
