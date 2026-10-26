"""Grounding and trust rules shared by every answer, whatever the channel or mode.

* Numbers in an answer must come from the data that was fetched for it (`ungrounded`, `enforce`).
* "Data unavailable" is stated honestly, never papered over.
* One not-investment-advice line and one accuracy caveat, reusing ARIA's existing disclaimer wording.
* Trust tags (`trust`) travel with every response so the UI and the tests can see what was checked.
"""
from __future__ import annotations

import json
import re
from typing import Any

from modules.equity_research.intelligence.report import DISCLAIMER_STRIP  # the strip text shown at the top of every page

DISCLAIMER_LINE = "This is not investment advice."
ACCURACY_CAVEAT = ("ARIA's scores, valuations and forecasts are model estimates with measured, limited accuracy "
                   "(see the validation section of the research report); verify before acting.")
DEGRADED = "I couldn't reach my language model just now, so I won't guess. Please ask again in a moment."
UNVERIFIED = "Note: {n} statement(s) with figures that are not in the data ARIA fetched were left out."

# Domains where the answer can read as advice: they carry the disclaimer line. Chit-chat, tutoring and clarifications do not.
ADVICE_DOMAINS = {"equity_research", "investment", "market", "instrument", "news", "finance"}
_VALUATION = re.compile(r"\b(fair value|target|forecast|valuation|score|rating|undervalued|overvalued|upside)\b", re.I)

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_OK_INTS = {12, 24, 52, 100, 365}
_UNITS = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "crores": 1e7,
          "million": 1e6, "billion": 1e9, "trillion": 1e12}
_UNIT_RE = re.compile(r"\s*(thousand|lakhs?|lac|crores?|million|billion|trillion|k)\b", re.I)


def _nums(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def ungrounded(reply: str, source: str, lenient: bool = False) -> list[float]:
    """Numbers in `reply` that match nothing in `source`. Rounded values, lakh/crore/million/billion scalings and small
    calendar numbers are allowed. `lenient` (routes whose prompts allow one-decimal rounding) widens the rounding band."""
    allowed = _nums(source)
    reply = _INDEX_NAME.sub(r"\1", reply)  # "Nifty 50" is a name, not a figure
    reply = _FISCAL_YEAR.sub("FY", reply)  # "FY23-24" / "2023-24" is a period label, not a figure
    rel, floor = (0.012, 0.06) if lenient else (0.006, 0.011)
    close = lambda x: any(abs(x - f) <= max(floor, rel * abs(f)) for f in allowed)  # noqa: E731
    bad = []
    for match in _NUM.finditer(reply):
        n = float(match.group().replace(",", ""))
        if n == int(n) and (n <= 31 or n in _OK_INTS or 1900 <= n <= 2100) and not (lenient and n <= 31 and _claim_like(reply, match)):
            continue
        unit = _UNIT_RE.match(reply[match.end():])
        # "473,080 crore" quoted from data that already says crore matches as written; "4.7 lakh" matches the scaled value
        if close(n) or (unit and close(n * _UNITS[unit.group(1).lower()])):
            continue
        bad.append(n)
    return bad


_FISCAL_YEAR = re.compile(r"\b(?:FY|F\.Y\.?)\s*\d{2,4}\s*[-‐-―−/]\s*\d{2,4}\b|\b(?:19|20)\d{2}\s*[-‐-―−/]\s*\d{2}\b", re.I)
_INDEX_NAME = re.compile(r"\b(nifty|sensex|bse|cnx)[\s-]*(?:50|100|200|500|30)\b", re.I)
_CLAIM_AFTER =re.compile(r"\s*(?:%|×|x\b|times\b|per ?cent|percent)|[-‐-―−]\d", re.I)
_CLAIM_BEFORE = re.compile(r"\d[-‐-―−]$")


def _claim_like(reply: str, match: re.Match) -> bool:
    """A small number that is a percentage, multiple or range ("about 20-22x", "40%") is a claim, not a calendar number."""
    return bool(_CLAIM_AFTER.match(reply[match.end():match.end() + 14]) or _CLAIM_BEFORE.search(reply[max(0, match.start() - 2):match.start()]))


def failed(text: Any) -> bool:
    """generate_response() returns 'Error: ...' when every LLM backend is down; that must never reach a user or a speaker."""
    return not isinstance(text, str) or not text.strip() or text.lstrip().lower().startswith("error")


def _evidence(resp: dict[str, Any]) -> tuple[str | None, bool]:
    """(fetched data this answer must be built from, lenient). None = no structured evidence to check against
    (chit-chat, tutoring, personal-finance tools whose inputs are the user's own numbers)."""
    d = resp.get("domain")
    if d in ("market", "investment") and resp.get("context"):
        return json.dumps(resp["context"], default=str, ensure_ascii=False), True
    if d == "equity_research" and (resp.get("normalized_data") or resp.get("value") is not None):
        keep = {k: resp.get(k) for k in ("company", "metric", "value", "normalized_data", "context", "report", "fund_report") if resp.get(k) is not None}
        return json.dumps(keep, default=str, ensure_ascii=False), True
    return None, False


_LABEL = re.compile(r"^(\s*(?:[-*•]\s+)?(?:\*\*)?[A-Z][A-Za-z ]{2,24}:(?:\*\*)?\s*)(.*)$")


def _redact(text: str, source: str, lenient: bool) -> tuple[str, list[float]]:
    """Drop each sentence that holds a number not found in `source` (keeping "Insight:"-style labels), and say so once."""
    removed: list[float] = []
    dropped = 0
    lines = []
    for line in text.split("\n"):
        m = _LABEL.match(line)
        head, body = (m.group(1), m.group(2)) if m else ("", line)
        parts = [p for p in re.split(r"(?<=[.!?])\s+", body) if p]
        good = []
        for p in parts:
            if bad := ungrounded(p, source, lenient):
                removed.extend(bad)
                dropped += 1
            else:
                good.append(p)
        if len(good) == len(parts):
            lines.append(line)
        elif good:
            lines.append(head + " ".join(good))
        elif head:
            lines.append(head.rstrip() + " no figure that ARIA could verify.")
    if not dropped:
        return text, removed
    kept = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return kept + f"\n\n{UNVERIFIED.format(n=dropped)}", removed


def enforce(resp: dict[str, Any]) -> dict[str, Any]:
    """The invented-numbers guard for every channel. Returns the `grounding` tag; edits resp["response"] when it must.

    Instrument and headline answers were already checked (with a retry and a facts-only fallback) while they were
    written, and carry their own tag. For the other fetched-data routes (market, live quote, fundamentals) a sentence
    holding an untraceable number is replaced by a plain notice. Personal-finance tool answers are only tagged: their
    inputs are the user's own figures."""
    if isinstance(resp.get("grounding"), dict):
        return resp["grounding"]
    text = resp.get("response")
    if failed(text):
        return {"numbers_checked": False, "passed": False, "fallback": True, "unavailable": ["language model"]}
    source, lenient = _evidence(resp)
    if source is None:
        if resp.get("domain") == "finance" and resp.get("engine") is not None:
            src = json.dumps({"engine": resp.get("engine"), "profile": resp.get("profile_basis"), "q": resp.get("query")}, default=str)
            return {"numbers_checked": True, "passed": not ungrounded(text, src, True), "fallback": False, "unavailable": [], "mode": "tag"}
        return {"numbers_checked": False, "passed": True, "fallback": False, "unavailable": []}
    fixed, removed = _redact(text, source, lenient)
    if removed:
        resp["response"] = fixed
    return {"numbers_checked": True, "passed": not removed, "fallback": False, "unavailable": [], "removed_numbers": removed[:8]}


def finalize(resp: dict[str, Any]) -> dict[str, Any]:
    """Add the disclaimer line / accuracy caveat to the written answer where it can read as advice, and the trust tags."""
    text = resp.get("response") if isinstance(resp.get("response"), str) else ""
    domain = resp.get("domain")
    advice = domain in ADVICE_DOMAINS and len(text) > 40 and not resp.get("missing_field") and not resp.get("ui_action") \
        and (domain != "finance" or resp.get("engine") is not None or resp.get("intent"))
    if advice and "not investment advice" not in text.lower():
        text += f"\n\n{DISCLAIMER_LINE}"
    valuation = bool(resp.get("report_id") or resp.get("report")) or (domain in ("equity_research", "investment", "instrument") and bool(_VALUATION.search(text)))
    if advice and valuation and "limited accuracy" not in text.lower():
        text += f"\n{ACCURACY_CAVEAT}"
    if text != resp.get("response") and text:
        resp["response"] = text
    resp["trust"] = {"disclaimer": DISCLAIMER_LINE, "strip": DISCLAIMER_STRIP, "accuracy_caveat": ACCURACY_CAVEAT,
                     "advice_domain": bool(advice), "grounding": resp.get("grounding")}
    return resp
