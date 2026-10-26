"""Last-resort web search for facts ARIA's own sources do not hold (an unlisted company, a rate, a price outside Yahoo/AMFI).

No API key: DuckDuckGo's HTML endpoint, then Bing's result page. Only title, snippet and link are read, never the article page.
The results are UNTRUSTED text: callers pass them to the model as information only (modules/qa/focus.py rule 6) and every
number in the answer must still appear in them (modules/qa/trust.py). Never raises: a dead engine gives an empty list.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup
from loguru import logger

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
_TTL, _TIMEOUT = 600, 8
_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_lock = threading.Lock()


def _clean(url: str) -> str:
    """DuckDuckGo wraps links as //duckduckgo.com/l/?uddg=<encoded>."""
    q = parse_qs(urlparse(url).query)
    return unquote(q["uddg"][0]) if "uddg" in q else url


def _ddg(query: str) -> list[dict[str, str]]:
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out = []
    for res in BeautifulSoup(r.text, "html.parser").select("div.result"):
        a, s = res.select_one("a.result__a"), res.select_one(".result__snippet")
        if a and s:
            out.append({"title": a.get_text(" ", strip=True), "snippet": s.get_text(" ", strip=True), "url": _clean(a.get("href", ""))})
    return out


def _bing(query: str) -> list[dict[str, str]]:
    r = requests.get("https://www.bing.com/search", params={"q": query, "cc": "IN"}, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    out = []
    for res in BeautifulSoup(r.text, "html.parser").select("li.b_algo"):
        a, s = res.select_one("h2 a"), res.select_one(".b_caption p, p")
        if a and s:
            out.append({"title": a.get_text(" ", strip=True), "snippet": s.get_text(" ", strip=True), "url": a.get("href", "")})
    return out


def search(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Up to `limit` {title, snippet, url} results, cached for 10 minutes."""
    query = " ".join((query or "").split())[:200]
    if len(query) < 3:
        return []
    with _lock:
        hit = _cache.get(query.lower())
        if hit and time.monotonic() - hit[0] < _TTL:
            return hit[1][:limit]
    for engine in (_ddg, _bing):
        try:
            results = [r for r in engine(query) if r["url"].startswith("http")][:8]
        except Exception as exc:
            logger.debug(f"web search via {engine.__name__} failed: {type(exc).__name__}")
            continue
        if results:
            with _lock:
                _cache[query.lower()] = (time.monotonic(), results)
            return results[:limit]
    return []
