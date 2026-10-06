"""Live news headlines for ARIA from many free public RSS sources (India and abroad), merged, de-duplicated and ranked.

No API keys, no scraping of article pages: only the headline, source, time and link that publishers syndicate over RSS.
One call replaces what used to be three thin, separate fetches (one ET feed, one Google search, yfinance).

    fetch_news("RBI repo rate")        # most relevant recent items for a question
    fetch_news()                       # a broad briefing: the latest across markets, economy and world

Consistency: every feed below was checked live (reachable, parses, newest item < 3 days old) before being listed;
each feed is fetched in parallel with a short timeout, cached for 10 minutes, and a failing feed is skipped (or served
from its last good copy), so one dead publisher never breaks or slows an answer.
"""
from __future__ import annotations

import contextvars
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
from loguru import logger

from config import settings

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
       "Accept": "application/rss+xml, application/xml, text/xml, */*"}
_OK_TTL, _FAIL_TTL, _FETCH_TIMEOUT, _DEADLINE = 600, 120, 5, 8  # seconds

_G_IN = "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
_G_US = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="

# (region, kind, name, url). region: india | world | any. kind: markets | general | official | wire.
# Checked live on 2026-10-06. Dropped after the check: Moneycontrol, India Today, CNN, MarketWatch Pulse (stale for
# months or years), Financial Express (410), Yahoo Finance (404), IMF (403), World Bank / BS Markets (broken XML).
FEEDS: list[tuple[str, str, str, str]] = [
    ("india", "markets", "ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("india", "markets", "ET Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("india", "markets", "ET Top", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
    ("india", "markets", "ET Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
    ("india", "markets", "ET Industry", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
    ("india", "markets", "ET Mutual Funds", "https://economictimes.indiatimes.com/mf/rssfeeds/359241701.cms"),
    ("india", "markets", "ET Wealth", "https://economictimes.indiatimes.com/wealth/rssfeeds/837555174.cms"),
    ("india", "markets", "Mint Markets", "https://www.livemint.com/rss/markets"),
    ("india", "markets", "Mint Companies", "https://www.livemint.com/rss/companies"),
    ("india", "markets", "Mint Economy", "https://www.livemint.com/rss/economy"),
    ("india", "markets", "Mint Money", "https://www.livemint.com/rss/money"),
    ("india", "markets", "Business Standard Economy", "https://www.business-standard.com/rss/economy-102.rss"),
    ("india", "markets", "Business Standard Companies", "https://www.business-standard.com/rss/companies-101.rss"),
    ("india", "markets", "Business Standard Finance", "https://www.business-standard.com/rss/finance-103.rss"),
    ("india", "markets", "Hindu BusinessLine", "https://www.thehindubusinessline.com/feeder/default.rss"),
    ("india", "markets", "Hindu BusinessLine Markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss"),
    ("india", "markets", "Hindu BusinessLine Economy", "https://www.thehindubusinessline.com/economy/feeder/default.rss"),
    ("india", "markets", "The Hindu Business", "https://www.thehindu.com/business/feeder/default.rss"),
    ("india", "markets", "NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
    ("india", "markets", "Indian Express Business", "https://indianexpress.com/section/business/feed/"),
    ("india", "markets", "Hindustan Times Business", "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml"),
    ("india", "markets", "TOI Business", "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"),
    ("india", "markets", "News18 Business", "https://www.news18.com/commonfeeds/v1/eng/rss/business.xml"),
    ("india", "markets", "Firstpost Business", "https://www.firstpost.com/commonfeeds/v1/mfp/rss/business.xml"),

    ("india", "general", "The Hindu National", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("india", "general", "TOI Top Stories", "http://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
    ("india", "general", "NDTV Top Stories", "https://feeds.feedburner.com/ndtvnews-top-stories"),
    ("india", "general", "NDTV India", "https://feeds.feedburner.com/ndtvnews-india-news"),
    ("india", "general", "Hindustan Times India", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
    ("india", "general", "Indian Express India", "https://indianexpress.com/section/india/feed/"),
    ("india", "general", "News18 India", "https://www.news18.com/commonfeeds/v1/eng/rss/india.xml"),
    ("india", "general", "Firstpost India", "https://www.firstpost.com/commonfeeds/v1/mfp/rss/india.xml"),
    ("india", "general", "Business Standard India", "https://www.business-standard.com/rss/india-news-216.rss"),
    ("india", "general", "Mint Politics", "https://www.livemint.com/rss/politics"),

    ("india", "official", "RBI Press Releases", "https://www.rbi.org.in/pressreleases_rss.xml"),

    ("world", "markets", "CNBC Top", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("world", "markets", "CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("world", "markets", "CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("world", "markets", "CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("world", "markets", "CNBC Asia", "https://www.cnbc.com/id/19832390/device/rss/rss.html"),
    ("world", "markets", "MarketWatch Top", "https://feeds.marketwatch.com/marketwatch/topstories"),
    ("world", "markets", "Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("world", "markets", "Bloomberg Economics", "https://feeds.bloomberg.com/economics/news.rss"),
    ("world", "markets", "Bloomberg Politics", "https://feeds.bloomberg.com/politics/news.rss"),
    ("world", "markets", "Investing.com News", "https://www.investing.com/rss/news.rss"),
    ("world", "markets", "Investing.com Stock Markets", "https://www.investing.com/rss/news_25.rss"),
    ("world", "markets", "Investing.com Economy", "https://www.investing.com/rss/news_14.rss"),
    ("world", "markets", "SCMP Economy", "https://www.scmp.com/rss/92/feed"),
    ("world", "markets", "SCMP Business", "https://www.scmp.com/rss/91/feed"),
    ("world", "markets", "Benzinga", "https://www.benzinga.com/feed"),
    ("world", "markets", "OilPrice", "https://oilprice.com/rss/main"),
    ("world", "markets", "Guardian Business", "https://www.theguardian.com/uk/business/rss"),
    ("world", "markets", "BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("world", "markets", "NYT Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ("world", "markets", "NYT Economy", "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
    ("world", "markets", "Seeking Alpha", "https://seekingalpha.com/feed.xml"),
    ("world", "markets", "FT Home", "https://www.ft.com/rss/home"),

    ("world", "general", "BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("world", "general", "BBC Asia", "http://feeds.bbci.co.uk/news/world/asia/rss.xml"),
    ("world", "general", "BBC India", "http://feeds.bbci.co.uk/news/world/asia/india/rss.xml"),
    ("world", "general", "Guardian World", "https://www.theguardian.com/world/rss"),
    ("world", "general", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("world", "general", "NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("world", "general", "DW", "https://rss.dw.com/rdf/rss-en-all"),
    ("world", "general", "France 24", "https://www.france24.com/en/rss"),
    ("world", "general", "Sky News World", "https://feeds.skynews.com/feeds/rss/world.xml"),
    ("world", "general", "NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("world", "general", "ABC Australia World", "https://www.abc.net.au/news/feed/45910/rss.xml"),

    ("world", "official", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("world", "official", "ECB", "https://www.ecb.europa.eu/rss/press.html"),

    ("any", "wire", "Reuters via Google News", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=site:reuters.com+when:2d"),
    ("any", "wire", "Bloomberg via Google News", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=site:bloomberg.com+when:2d"),
    ("any", "wire", "AP via Google News", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=site:apnews.com+when:2d"),
    ("any", "wire", "FT via Google News", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=site:ft.com+when:2d"),
    ("any", "wire", "WSJ via Google News", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=site:wsj.com+when:2d"),
    ("any", "topic", "India business", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=India+business+economy+when:1d"),
    ("any", "topic", "Sensex Nifty", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=Sensex+Nifty+when:1d"),
    ("any", "topic", "RBI", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=RBI+repo+rate+when:7d"),
    ("any", "topic", "World economy", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=global+economy+markets+when:1d"),
    ("any", "topic", "Crude oil", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=crude+oil+prices+when:2d"),
    ("any", "topic", "Fed", "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=Federal+Reserve+rates+when:3d"),
    ("any", "topic", "Rupee dollar", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=rupee+dollar+when:2d"),
    ("any", "topic", "Gold", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=gold+price+when:2d"),
    ("any", "topic", "Budget policy", "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=India+government+policy+tax+when:3d"),
]

# words that never narrow a search: dropped before matching headlines
_STOP = set("""a an the is are was were be been am do does did how what why when where which who whom whose will would should could can
may might must shall of in on at to for from by with about into over under again than then so as and or but if not no yes it its
this that these those i me my we our you your he she they them their his her tell give show explain please pls any some more most
much many very just also still now today tomorrow yesterday latest new news update updates current currently happening happened
going going want need like think know get got make
abroad overseas international internationally domestic around everything anything happening top morning evening night week weekend
breaking headlines headline stories story reports report""".split())
_GENERIC = set("""market markets stock stocks share shares price prices index indices economy economic india indian world global
company companies business finance financial investor investors investing investment trading trade sector""".split())


# auto-generated filler and routine regulator notices: plentiful, never what a question is about
_NOISE = re.compile(
    r"share price live updates|(?:gold|silver|petrol|diesel)\s+(?:rate|price)s?\s+(?:today\s+)?in\s+[A-Z]|"
    r"(?:rate|price)s?\s+today\s+in\s+[A-Z]|directions under section|monetary penalty|imposes penalty|"
    r"approval of application|order under section|stock details$", re.I)


def _norm_title(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in _STOP and len(w) > 2}


def _parse_date(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(xml: bytes, fallback_source: str) -> list[dict]:
    """RSS 2.0 / Atom / RDF bytes -> [{title, source, published (aware datetime), url}]. Raises on malformed XML."""
    out = []
    for item in ET.fromstring(xml).iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        fields = {}
        for child in item:
            name = _local(child.tag)
            if name == "link":  # RSS: text; Atom: href attribute
                fields.setdefault("link", (child.text or "").strip() or child.get("href", ""))
            elif name in ("title", "source", "pubDate", "published", "updated", "date"):
                fields.setdefault(name, (child.text or "").strip())
        title = re.sub(r"[\x00-\x1f\x7f]", " ", fields.get("title", "")).strip()
        published = _parse_date(fields.get("pubDate") or fields.get("published") or fields.get("updated") or fields.get("date", ""))
        source = fields.get("source") or fallback_source  # Google News names the real publisher in <source>
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        if title and published and not _NOISE.search(title):
            out.append({"title": title[:220], "source": source[:60], "published": published, "url": fields.get("link", "")})
    return out


_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _fetch(name: str, url: str) -> list[dict]:
    """One feed, cached. A failure returns the last good copy (or nothing) and is retried after a short pause."""
    now = time.time()
    with _lock:
        hit = _cache.get(url)
    if hit and hit[0] > now:
        return hit[1]
    try:
        res = requests.get(url, headers=_UA, timeout=_FETCH_TIMEOUT)
        res.raise_for_status()
        items = parse_feed(res.content, name)
        with _lock:
            _cache[url] = (now + _OK_TTL, items)
        return items
    except Exception as exc:
        logger.debug(f"news feed {name!r} unavailable: {exc}")
        stale = hit[1] if hit else []
        with _lock:
            _cache[url] = (now + _FAIL_TTL, stale)
        return stale


def _has(words: set[str], key: str) -> bool:
    return key in words or any(w.startswith(key) for w in words)


def _keywords(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9&]+", query.lower())
    return [w for w in dict.fromkeys(words) if w not in _STOP and w not in _GENERIC and len(w) > 2]


def fetch_news(query: str = "", limit: int = 10, max_age_hours: int = 72, region: str | None = None, google: bool = True) -> list[dict]:
    """Most relevant recent headlines for ``query`` (or a broad briefing when it names nothing specific).

    Returns [{title, source, published, url, age_hours, sources}] newest-relevant first; ``sources`` is how many different
    publishers carried the story (more = better corroborated). Never raises. ``region`` limits to "india" or "world";
    ``google=False`` skips the live Google News search (used when the caller already ran its own).
    """
    if not settings.FI_NEWS_RSS:
        return []
    keys = _keywords(query)
    jobs = [(n, u) for r, _k, n, u in FEEDS if region is None or r in (region, "any")]
    search = None
    if google and keys:  # an arbitrary topic is best found by searching, fixed feeds only carry what they carry
        search = _G_IN + quote(" ".join(keys[:5]) + f" when:{max(1, max_age_hours // 24)}d")
        jobs.append(("Google News", search))

    now = datetime.now(timezone.utc)
    pool = ThreadPoolExecutor(max_workers=16)
    futures = {pool.submit(_fetch, n, u): u for n, u in jobs}
    items: list[dict] = []
    try:
        for f in as_completed(futures, timeout=_DEADLINE):
            items.extend({**it, "searched": futures[f] == search} for it in f.result())
    except Exception:  # deadline hit: rank what arrived rather than make the user wait on the slowest feed
        logger.debug("news fetch deadline reached; using the feeds that answered")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    fresh_items = [it for it in items if (now - it["published"]).total_seconds() / 3600 <= max_age_hours]
    for it in fresh_items:
        it["words"] = _norm_title(it["title"])
    # a word in many headlines ("results", "industries") says little; a rare one ("reliance") says a lot
    weight = {k: max(0.05, math.log((len(fresh_items) + 1) / (1 + sum(1 for it in fresh_items if _has(it["words"], k))))) for k in keys}  # floor: a word in every headline still counts as a match
    scored = []
    for it in fresh_items:
        age = max(0.0, (now - it["published"]).total_seconds() / 3600)
        words = it["words"]
        hits = sum(w for k, w in weight.items() if _has(words, k))
        if keys and not hits and not it["searched"]:
            continue  # a specific question: only items that mention its subject (search results already matched upstream)
        scored.append({**it, "age_hours": round(age, 1), "hits": hits, "publishers": {it["source"]}})

    # merge the same story reported by several publishers (title word overlap), remembering how many carried it
    scored.sort(key=lambda i: i["age_hours"])
    merged: list[dict] = []
    for it in scored:
        for m in merged:
            if it["words"] and m["words"] and len(it["words"] & m["words"]) / len(it["words"] | m["words"]) >= 0.6:
                m["publishers"].add(it["source"])
                m["hits"] = max(m["hits"], it["hits"])
                break
        else:
            merged.append(it)

    def score(i: dict) -> float:
        fresh = 1 - i["age_hours"] / max_age_hours
        return i["hits"] + fresh + 0.4 * min(len(i["publishers"]) - 1, 4)  # carried by several publishers = corroborated

    merged.sort(key=score, reverse=True)
    out, per_source = [], {}
    cap = 3 if keys else 2  # a broad briefing should not be all one publisher
    for it in merged:
        if per_source.get(it["source"], 0) >= cap:
            continue
        per_source[it["source"]] = per_source.get(it["source"], 0) + 1
        out.append({**{k: it[k] for k in ("title", "source", "published", "url", "age_hours")}, "sources": len(it["publishers"])})
        if len(out) >= limit:
            break
    return out


def format_headlines(items: list[dict]) -> list[str]:
    """['Title (Source, 3h ago)'] for prompts: the age and source let the model weigh how fresh and how credible a line is."""
    def ago(h: float) -> str:
        return f"{h:.0f}h ago" if h < 48 else f"{h / 24:.0f}d ago"
    return [f"{i['title']} ({i['source']}, {ago(i['age_hours'])}{', ' + str(i['sources']) + ' sources' if i['sources'] > 1 else ''})" for i in items]


# Questions that are about now, or that ask whether to act: worth a look at the headlines. A concept question
# ("what is a mutual fund?") or a personal calculation ("I earn 60000 a month...") is not, and skips the fetch.
_TIME_SENSITIVE = re.compile(
    r"\b(news|headlines?|latest|today|tonight|now|current(?:ly)?|recent(?:ly)?|this (?:week|month|year|quarter)|right now|"
    r"happening|going on|update|outlook|forecast|trend(?:ing)?|should i (?:buy|sell|invest|wait|hold)|good time|worth buying)\b", re.I)
_live_news: contextvars.ContextVar[str | None] = contextvars.ContextVar("aria_live_news", default=None)


def wants_news(query: str) -> bool:
    return bool(_TIME_SENSITIVE.search(query or ""))


def current_news_block() -> str | None:
    """The headlines the running module may use, as a prompt paragraph (or None). Read by ai/llm/groq_client.py."""
    return _live_news.get()


@contextmanager
def news_context(query: str):
    """Within this block every LLM call a module makes gets the freshest headlines about the question appended to its
    system prompt (when the question is time-sensitive). Yields the headline items so the caller can show them."""
    items = fetch_news(query, limit=8) if wants_news(query) else []
    token = _live_news.set(
        "Fresh headlines from Indian and global news feeds (use only what is relevant, name the outlet and how recent it is, "
        "never invent news that is not listed):\n" + "\n".join("- " + h for h in format_headlines(items)) if items else None)
    try:
        yield items
    finally:
        _live_news.reset(token)


def warm_up() -> None:
    """Fetch every feed once in the background so the first question after a restart is not the slow one."""
    fetch_news(limit=1)
