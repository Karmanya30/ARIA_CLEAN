"""Data questions about something that is not one of the ~45 hard-coded companies in shared/company_resolver.py.

"What is the PE ratio of Suzlon Energy?", "NAV of Para Parish Flexi Cap", "price of gold", "revenue of Kaynes Technology":
the name is looked up in the instrument catalogue (NSE/BSE universe, AMFI funds, crypto, commodities; typo tolerant) and the
question is answered from that instrument's fetched facts (modules/qa/focus.py). A name the catalogue does not hold falls
back to a web search, whose snippets are the only evidence the answer may use. Anything else returns None and the normal
routing carries on, so this never changes how an already-routed question is answered.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from loguru import logger

DATA_Q = re.compile(r"\b(price|nav|p/?e|market ?cap|revenue|sales|profit|income|debt|borrowings?|worth|trading|quote|rate|yield|ebitda|eps|"
                    r"dividend|52[- ]?week|returns?|cagr|volume|valuation|book value|roe|margin|worth|cost|rates?|"
                    r"perform(?:ance|ed|ing)?|how did .{3,60} do|do(?:ing)? this (?:week|month|year))\b", re.I)
_STOP = set("""a an the of for in on at to is are was were be been am do does did what whats what's how which who whom when where why
 tell me show give get find about with and or my your our their its it this that these those please can could would should will
 current currently latest today now right recent last past new price prices nav pe p/e ratio ratios market cap capitalisation
 capitalization revenue sales profit profits income debt borrowing borrowings worth trading quote quotes rate rates yield ebitda eps
 dividend dividends 52 week weeks return returns cagr volume valuation book value roe margin margins cost per share shares stock
 stocks equity company companies limited ltd inc corp corporation india indian inr rupees rupee fy net total annual quarterly
 performance performed performing perform doing much many high low change growth number numbers data info information details say says said tomorrow yesterday year years month
 months day days""".split())
_SOFT = {"india", "cap", "fund", "limited", "ltd"}  # stop words only at the edge of a name: "Nippon India Small Cap Fund"
_WORD = re.compile(r"[A-Za-z0-9&][A-Za-z0-9&.'-]*")
_MAX_SEARCHES = 6
_GREETINGS = {"hello", "thanks", "thank", "please", "hey", "namaste", "sorry", "okay", "yes", "good", "tell", "also"}
_FUND = re.compile(r"\b(nav|mutual funds?|funds?|schemes?|etfs?|amc|flexi ?cap|elss|sip)\b", re.I)


def mentions_fund(text: str) -> bool:
    """"NAV of SBI Bluechip fund": the company alias in it ("SBI") must not turn the question into one about the bank."""
    return bool(_FUND.search(text))


def is_data_question(query: str) -> bool:
    return bool(DATA_Q.search(query))


def _tokens(text: str) -> list[str]:
    return [w.strip(".'-").lower() for w in _WORD.findall(text)]


def candidates(text: str) -> list[str]:
    """Name guesses, most specific first: each run of non-stop words, then its first two words."""
    runs, cur = [], []
    for t in _tokens(text):
        if t in _SOFT and cur:
            cur.append(t)
        elif len(t) > 1 and t not in _STOP and t not in _SOFT and not re.fullmatch(r"(fy)?\d{2,4}([-/]\d{2,4})?", t):
            cur.append(t)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out: list[str] = []
    for run in sorted(runs, key=len, reverse=True):
        for w in ((run, run[:2]) if len(run) > 1 else (run,)):  # never the first word alone: "SBI" is not "SBI Bluechip"
            s = " ".join(w)
            if len(s) >= 3 and s not in out:
                out.append(s)
    return out


def _confident(window: str, item: dict) -> bool:
    """Every word of the guess is a word (or word start) of the instrument; a spelling slip is allowed in ONE word of a
    multi-word guess when another word matches exactly ("keynes technology" -> Kaynes Technology). A single fuzzy word is
    never enough: "inflation" must not become "Insolation Energy"."""
    words = set(re.findall(r"[a-z0-9&]+", f"{item['name']} {item['symbol']}".lower()))
    toks = [t for t in re.findall(r"[a-z0-9&]+", window.lower())]
    exact = fuzzy = 0
    for t in toks:
        if t in words or (len(t) >= 3 and any(w.startswith(t) for w in words)):
            exact += 1
        elif len(t) >= 4 and t.isalpha() and any(abs(len(w) - len(t)) <= 2 and SequenceMatcher(None, t, w).ratio() >= 0.8 for w in words):
            fuzzy += 1
        else:
            return False
    return bool(toks) and exact >= 1 and fuzzy <= 1 and (len(toks) > 1 or fuzzy == 0)


_COMMON_WORD_FREQUENCY = 20_000_000  # symspell frequency above which a bare word is ordinary English ("bond", "tips", "rental")


def _credible(window: str, item: dict, original: str) -> bool:
    """A match is believable as a NAME. A single ordinary English word that the user did not capitalise is not: "bond yield" is not
    Bondada Engineering, "intraday trading tips" is not Tips Music. Commodities, crypto, indices and currencies are named by common words
    ("gold", "silver", "bitcoin") and several-word names are specific enough, so those pass."""
    toks = window.split()
    if item["type"] in ("commodity", "crypto", "index", "currency") or len(toks) >= 2:
        return True
    word = toks[0]
    if any(w.lower() == word and w[:1].isupper() for w in _WORD.findall(original)):
        return True
    try:
        from shared.understand import _speller
        return (_speller().words.get(word) or 0) < _COMMON_WORD_FREQUENCY
    except Exception:  # no dictionary: be strict
        return False


def find_instrument(*texts: str) -> dict | None:
    """The catalogue item the question is about, or None. `texts` are tried in order (the user's own words first, because
    the spelling corrector can change an unfamiliar name)."""
    from modules.market import instruments as I

    tried = 0
    for text in texts:
        for window in candidates(text):
            if tried >= _MAX_SEARCHES:
                return None
            tried += 1
            try:
                items = I.search(window, limit=5)["items"]
            except Exception as exc:
                logger.debug(f"instrument lookup failed: {type(exc).__name__}")
                return None
            fund = mentions_fund(text)
            for it in items:
                if _confident(window, it) and _credible(window, it, texts[0]) and (not fund or it["type"] in ("mutual_fund", "etf")):
                    return it
    return None


def _has_proper_noun(original: str) -> bool:
    """A capitalised word that is not the first word, or an ALL-CAPS word: the user named something specific."""
    words = _WORD.findall(original)
    # A first word counts too when it is not a question/command word: "Kaynes ka revenue kitna hai?" starts with the company
    return any((i > 0 and w[0].isupper() and w.lower() not in _STOP) or (w.isupper() and len(w) >= 3 and w.lower() not in _STOP)
               or (i == 0 and len(w) >= 4 and w[0].isupper() and w.lower() not in _STOP and w.lower() not in _GREETINGS)
               for i, w in enumerate(words))


def web_answer(query: str, why: str) -> dict[str, Any] | None:
    """Answer from web search snippets only. None when the search finds nothing (the caller then keeps its own reply)."""
    from modules.qa import focus
    from shared.websearch import search

    results = search(query, 5)
    if not results:
        return None
    facts = {"UNTRUSTED_CONTEXT_JSON": [{"title": r["title"], "snippet": r["snippet"], "source": r["url"]} for r in results], "unavailable": [why]}
    text, grounding = focus.grounded_answer(
        "a question that ARIA's own market data does not cover, answered only from these web search results", query, facts,
        summary=lambda lead: lead + "\n\n" + "\n".join(f"- {r['title']}: {r['snippet']}" for r in results[:3]))
    sources = [{"title": r["title"], "url": r["url"]} for r in results]
    return {"domain": "general", "query": query, "response": text + "\n\nSources: " + "; ".join(s["url"] for s in sources[:3]),
            "grounding": grounding, "context": {"web_sources": sources, "unavailable": [why]}}


def data_answer(shown: str, normalised: str, owner_id: str | None, history: list[dict] | None) -> dict[str, Any] | None:
    """The answer to a data question about an unlisted name, or None when this is not one (normal routing then continues)."""
    from modules.qa import focus

    if not is_data_question(shown) and not is_data_question(normalised):
        return None
    it = find_instrument(shown, normalised)
    if it:
        resp = focus.instrument_answer(it["id"], normalised, owner_id, history)
        if (resp["context"]["quote"].get("price") is None and not resp["context"].get("financials")) and (web := web_answer(f"{it['name']} {shown}", f"live data for {it['name']}")):
            return web
        return resp
    if _has_proper_noun(shown) and candidates(shown):
        return web_answer(shown, "this name is not in ARIA's instrument lists") or no_data_answer(shown)
    return None


def no_data_answer(query: str) -> dict[str, Any]:
    """Evidence sufficiency gate: a data question about a named thing that neither the instrument lists nor a web search could answer
    must not fall through to the general model, which would answer from memory (that is how an invented gold price once appeared)."""
    why = "I couldn't find reliable data for that right now (it is not in ARIA's instrument lists and a web search returned nothing usable), so I won't guess a figure."
    return {"domain": "general", "query": query, "response": why + " Please check the exact company, fund or ticker name, or try again in a moment.",
            "grounding": {"numbers_checked": True, "passed": True, "fallback": True, "unavailable": ["the requested figure"], "deterministic": True},
            "gate": "no_evidence"}
