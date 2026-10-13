"""Indian mutual funds from two free sources: AMFI's official daily NAV file (every scheme, its ISIN, AMC, category and
latest NAV) and mfapi.in (full NAV history per scheme). Both are cached under data/instruments/ so a slow or dead
source only costs the freshness, never the answer."""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

import requests
from loguru import logger

DIR = Path(__file__).resolve().parents[2] / "data" / "instruments"
NAVALL_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI_URL = "https://api.mfapi.in/mf/{code}"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ARIA/1.0"}
NAV_TTL, HIST_TTL = 6 * 3600, 6 * 3600  # AMFI publishes once a day; history only moves daily

_lock = threading.Lock()
_funds: list[dict] | None = None
_funds_at = 0.0
_by_code: dict[str, dict] = {}


def http_get(url: str, timeout: float = 15, **kw) -> requests.Response:
    r = requests.get(url, headers=_UA, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def _plan_option(name: str, plan: str = "", option: str = "") -> tuple[str, str]:
    """Normalise to Direct/Regular and Growth/IDCW/Bonus (older AMFI rows only carry these inside the scheme name)."""
    s = f"{plan} {option} {name}".lower()
    p = "Direct" if "direct" in s else "Regular"
    o = "IDCW" if re.search(r"idcw|dividend|payout|reinvest", s) else "Bonus" if "bonus" in s else "Growth"
    return p, o


def parse(text: str) -> list[dict]:
    """NAVAll.txt: ';'-separated scheme rows under a category header line and an AMC name line."""
    funds, amc, cat, kind = [], "", "", ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        if ";" not in line:
            m = re.match(r"(Open Ended|Close Ended|Interval Fund)[^(]*\((.*)\)\s*$", line, re.I)
            if m:
                kind, cat = m.group(1).title(), m.group(2).strip()
            else:
                amc = line
            continue
        f = [x.strip() for x in line.split(";")]
        if len(f) < 6 or not f[0].isdigit():
            continue
        try:
            nav = float(f[-2])
            d = datetime.strptime(f[-1], "%d-%b-%Y").date()
        except ValueError:
            continue  # "N.A." NAVs and malformed rows
        plan, option = _plan_option(f[3], f[4] if len(f) >= 8 else "", f[5] if len(f) >= 8 else "")
        isin = next((x for x in (f[1], f[2]) if x.startswith("INF")), "")
        funds.append({"code": f[0], "isin": isin, "name": f[3], "plan": plan, "option": option, "nav": nav, "date": d.isoformat(),
                      "amc": amc, "category": cat, "kind": kind})
    return funds


def _load(force: bool = False) -> list[dict]:
    """Today's NAV file from disk, else downloaded; the last good copy (any age) when the download fails."""
    global _funds, _funds_at
    with _lock:
        if _funds is not None and not force and time.time() - _funds_at < NAV_TTL:
            return _funds
        path = DIR / "navall.txt"
        fresh = path.exists() and time.time() - path.stat().st_mtime < NAV_TTL
        text = path.read_text("utf-8", errors="replace") if fresh else None
        if text is None:
            try:
                text = http_get(NAVALL_URL, timeout=30).content.decode("utf-8", errors="replace")
                if text.count(";") < 1000:
                    raise ValueError("AMFI file looks truncated")
                DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(text, "utf-8")
            except Exception as exc:
                logger.warning(f"AMFI NAV file unavailable ({type(exc).__name__}): using the last copy if any")
                if _funds is not None:
                    return _funds
                text = path.read_text("utf-8", errors="replace") if path.exists() else ""
        _funds, _funds_at = parse(text), time.time()
        _by_code.clear()
        _by_code.update({f["code"]: f for f in _funds})
        return _funds


def funds() -> list[dict]:
    return _load()


def fund(code: str) -> dict | None:
    _load()
    return _by_code.get(str(code))


def _parse_history(js: dict) -> list[tuple[str, float]]:
    out = []
    for r in js.get("data") or []:
        try:
            out.append((datetime.strptime(r["date"], "%d-%m-%Y").date().isoformat(), float(r["nav"])))
        except (KeyError, ValueError):
            continue
    return sorted(out)


def history(code: str) -> tuple[dict, list[tuple[str, float]], bool]:
    """(meta, [(iso date, nav)] oldest first, stale) from mfapi.in; cached on disk, the old copy is served (stale) if it fails."""
    code = str(code)
    path = DIR / "mfapi" / f"{code}.json"
    js, stale = None, False
    if path.exists() and time.time() - path.stat().st_mtime < HIST_TTL:
        js = json.loads(path.read_text("utf-8"))
    else:
        try:
            js = http_get(MFAPI_URL.format(code=code), timeout=20).json()
            if not js.get("data"):
                raise ValueError("no NAV rows")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(js), "utf-8")
        except Exception as exc:
            logger.warning(f"mfapi {code} failed ({type(exc).__name__})")
            if path.exists():
                js, stale = json.loads(path.read_text("utf-8")), True
    if not js:
        return {}, [], True
    return js.get("meta") or {}, _parse_history(js), stale


def stale_nav(nav_date: str, today: date | None = None) -> bool:
    """A NAV older than 5 days has missed more than a weekend plus a holiday."""
    return ((today or date.today()) - date.fromisoformat(nav_date)).days > 5
