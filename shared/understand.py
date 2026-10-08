"""Query understanding: spelling, text-speak and Hinglish are normalised for ROUTING only.

    text, changes = normalize(query)   # "shud i sel my mutal funds" -> "should i sell my mutual funds"
    goal(text, hit)                    # what the user is trying to do: urgent|decide|afford|track|compare|learn|vent|ask
    suggest(text)                      # "did you mean" phrases for a query no router recognised

The original text stays the display / history / tone text; amounts, punctuation and spacing are copied through unchanged.
Nothing here logs or stores message text. Spell checking: SymSpell (Wolf Garbe, MIT) via symspellpy; see THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from importlib.resources import files

from symspellpy import SymSpell, Verbosity

from shared import human_state

# ponytail: whole-token lookups, not language-model correction. Ceiling: words with two errors in a short token, or a typo that
# is itself a real word ("form" for "from"). Upgrade path: a bigram dictionary (symspellpy ships one) for context.
TEXTSPEAK = {"wat": "what", "wht": "what", "shud": "should", "shld": "should", "r": "are", "u": "you", "ur": "your", "pls": "please",
             "plz": "please", "abt": "about", "hw": "how", "bcz": "because", "coz": "because", "cuz": "because", "tmrw": "tomorrow",
             "tdy": "today", "mnth": "month", "mth": "month", "yr": "year", "yrs": "years", "rnt": "rent", "pr": "per", "thx": "thanks",
             "n": "and", "wid": "with", "gud": "good", "expln": "explain"}
# common transpositions SymSpell would rank behind a rarer domain word; still announced as spelling fixes (not in TEXTSPEAK)
TYPOS = {"teh": "the", "adn": "and", "taht": "that", "wiht": "with", "abuot": "about", "becuase": "because", "recieve": "receive", "spnd": "spend"}
_SPELL_PHRASES = [(re.compile(p, re.I), r) for p, r in (
    (r"\bbye (a|an|the|this|new)\b", r"buy \1"), (r"\bsel (my|all|the)\b", r"sell \1"), (r"\b2day\b", "today"))]
_HINGLISH_PHRASES = [(re.compile(p, re.I), r) for p, r in (
    (r"\bband (?:kr|kar|karo|karna|karu|kardu|kardo)\b", "stop"), (r"\bbech(?:o|na|du|u)?\b", "sell"), (r"\bnikaa?l\b", "withdraw"), (r"\brok\b", "stop"),
    (r"\b(?:kitna|kitni)\b", "how much"), (r"\bkharch[ae]?\b", "spend"), (r"\bbachat\b", "savings"), (r"\bnivesh\b", "invest"),
    (r"\b(?:mera|meri|mere)\b", "my"), (r"\bmaine\b", "i"), (r"\bmujhe\b", "me"))]
# 'du', 'kya', 'karu' stay: the finance pipeline's _WEIGHING needs them.
HINGLISH_KEEP = frozenset(human_state.HINGLISH) | set(
    "ho rha rhi rhe raha hai du kiya hua gaya liya diya pe par mein main hum sirf thoda zyada jyada bol bolo batao bata dikhao lagta lag hu hun hoon "
    "tha thi ke ki ka ko se ye yeh woh wo kal aaj mahine saal band apna apni apne rok dena chahie kuch sab abhi paisa paise rupaye lakh saal mahina "
    "kaise kyun kyu kaun bhi toh to aur ya hoga hogi rahega lena karna karo samjhao accha theek thik bilkul kam wala wali "
    "mujhe mera meri mere humein tumhara unka iska uska isse usse kisi koi kahan kab kitna kitni jaldi lagta lagti lagte".split())
_EXTRA = ("lakh lakhs crore nifty sensex spend food rent score health intelligence research compound interest mutual fund equity elss ppf epf nps "
          "foir nav xirr cagr sip emi how much what should buy sell afford loan tax stop invest savings withdraw income expenses goal aria "
          "lumpsum lump sum swp stp nfo neft imps rtgs demat cibil sebi amfi ltcg stcg upi kyc itr gst etf ipo mf mfs fd fds rd ulip swp stp hra tds zerodha groww paytm").split()
_TOKEN = re.compile(r"(?<![\w@.&/₹])[A-Za-z]+(?![\w@&/])(?!\.[A-Za-z])")
MIN_COUNT = 500_000  # index only common words: the full 82k-word index cost ~135 MB (67 MB at this cut); every word still counts as KNOWN
_SPLIT = {"mutualfund": "mutual fund", "mutualfunds": "mutual funds", "indexfund": "index fund", "indexfunds": "index funds", "goldfund": "gold fund",
          "debtfund": "debt fund", "equityfund": "equity fund", "homeloan": "home loan", "carloan": "car loan", "networth": "net worth"}
_WORD = re.compile(r"[a-z]{3,}")


def _domain_words() -> frozenset[str]:
    """Vocabulary the routers already know, read from their own data so the two never drift apart."""
    from core import router
    from modules.finance.pipeline import _WHAT_IF_TARGET
    from shared import company_resolver, intent_classifier
    from config.paths import CONCEPTS_KB_FILE

    texts = list(company_resolver._COMPANY_MAP) + [p for _, p in _WHAT_IF_TARGET] + list(_EXTRA)
    for mod in (intent_classifier, router):
        for name, val in vars(mod).items():
            if isinstance(val, tuple) and all(isinstance(v, str) for v in val):
                texts += val
    for c in json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf8")):
        texts += [c.get("canonical_name", ""), *c.get("aliases", []), *c.get("keywords", [])]
    return frozenset(w for t in texts for w in _WORD.findall(t.lower()))


@lru_cache(maxsize=1)
def _build():
    sp = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    english: dict[str, int] = {}
    for line in (files("symspellpy") / "frequency_dictionary_en_82_765.txt").read_text(encoding="utf8").splitlines():
        word, _, count = line.partition(" ")
        english[word] = int(count)
    for word, count in english.items():
        if count >= MIN_COUNT:
            sp.create_dictionary_entry(word, count)
    domain = _domain_words()
    top = max(english.values()) + 1  # above every English word, so a longer domain word wins a tie; short ones keep their own frequency
    for word in domain:
        sp.create_dictionary_entry(word, top if len(word) >= 5 else english.get(word, 1_000_000))
    return sp, domain, frozenset(english) | domain | HINGLISH_KEEP, frozenset(english)


def _speller():
    return _build()[0]


def _fix(tok: str, sp, domain, known, after_number: bool, spell: bool = True) -> str | None:
    """The replacement for one token, or None to leave it alone."""
    low = tok.lower()
    if len(tok) > 1 and tok.isupper() and len(tok) <= 6:
        return None
    if low in TEXTSPEAK or (spell and low in TYPOS):
        return TEXTSPEAK.get(low) or TYPOS[low]
    if not spell or low in known or after_number or len(low) <= 2:
        return None
    if len(low) >= 7 and (close := difflib.get_close_matches(low, _SPLIT, n=1, cutoff=0.85)):  # "mutalfund"
        return _SPLIT[close[0]]
    hits = sp.lookup(low, Verbosity.CLOSEST, max_edit_distance=1, include_unknown=False)  # one edit only: gibberish stays gibberish
    if hits:  # hits are the closest, most frequent first; a 3-letter token only becomes a domain word ("fod" -> "food")
        return next((h.term for h in hits if h.term in domain), None) if len(low) <= 3 else hits[0].term
    if len(low) >= 7:  # "mutualfund", "howmuch"
        pieces = sp.word_segmentation(low, max_edit_distance=0).corrected_string.split()
        if len(pieces) > 1 and all(p in known and (len(p) >= 3 or p in domain) for p in pieces) and any(p in domain for p in pieces):
            return " ".join(pieces)
    return None


def normalize(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Corrected text for routing and the list of (old, new) edits. Idempotent; digits, symbols and spacing are untouched."""
    sp, domain, known, english = _build()
    # a Hinglish message (2+ Hindi words that are not English) gets no spell checking: only the phrase and text-speak maps
    spell = sum(w in HINGLISH_KEEP and w not in english for w in re.findall(r"[a-z]+", text.lower())) < 2
    changes: list[tuple[str, str]] = []

    def phrase(m: re.Match, rep: str) -> str:
        new = m.expand(rep)
        changes.append((m.group(0), new))
        return new

    for rx, rep in _SPELL_PHRASES + _HINGLISH_PHRASES:
        text = rx.sub(lambda m, rep=rep: phrase(m, rep), text)
    out, pos, toks = [], 0, list(_TOKEN.finditer(text))
    i = 0
    while i < len(toks):
        m = toks[i]
        tok = m.group(0)
        new = _fix(tok, sp, domain, known, bool(re.search(r"\d\s*$", text[:m.start()])), spell)
        end = m.end()
        if spell and new is None and tok.lower() not in known and not tok.isupper() and i + 1 < len(toks):
            nxt = toks[i + 1]
            if text[end:nxt.start()] == " " and nxt.group(0).lower() not in known and not nxt.group(0).isupper():  # two unknown halves
                joined = (tok + nxt.group(0)).lower()
                hit = sp.lookup(joined, Verbosity.TOP, max_edit_distance=1, include_unknown=False)
                new = joined if joined in domain else hit[0].term if hit else None
                if new:
                    end, i = nxt.end(), i + 1
        if new is not None and new != text[m.start():end]:
            if tok[0].isupper() and tok[1:].islower():
                new = new.capitalize()
            changes.append((text[m.start():end], new))
            out += [text[pos:m.start()], new]
            pos = end
        i += 1
    return "".join(out) + text[pos:], changes


def spelled(changes: list[tuple[str, str]]) -> bool:
    """True if any edit is a spelling fix (not only text-speak or Hinglish words)."""
    return any(old.lower() not in TEXTSPEAK and not any(rx.fullmatch(old) for rx, _ in _HINGLISH_PHRASES) for old, _ in changes)


def goal(text: str, hit: tuple | None = None, intent: str | None = None) -> str:
    """What the user is trying to do. hit = finance_intent(text); intent = human_state's read ("venting" ...)."""
    from core.router import _CONCEPT_QUESTION

    low = text.lower()
    kind = hit[0] if hit else None
    if human_state._score(low, "urgency") >= 0.5:
        return "urgent"
    if kind == "decision" or human_state._score(low, "decision") >= 0.5:
        return "decide"
    if kind in ("afford", "afford_sip"):
        return "afford"
    if kind in ("spending", "health"):
        return "track"
    if re.search(r"\b(vs|versus|compare|comparison|difference between|better than)\b", low):
        return "compare"
    if _CONCEPT_QUESTION.match(low):
        return "learn"
    return "vent" if intent == "venting" else "ask"


INTENT_EXAMPLES = {
    "spending": ("how much did i spend on food last month", "analyse my spending", "show my biggest expenses"),
    "health": ("what is my financial health score", "how healthy are my finances", "what is my net worth"),
    "afford": ("can i afford to buy a car", "can i afford a home loan", "can i buy a house worth 50 lakhs"),
    "afford_sip": ("can i start a sip of 10000", "how much sip can i afford", "should i start a sip"),
    "decision": ("should i sell my mutual funds", "should i stop my sip", "should i exit my stocks"),
    "what_if": ("what if i cut my food spending by 5000", "what if i reduce my rent", "what if my income increases"),
    "retirement": ("when can i retire", "how much do i need to retire", "plan my retirement"),
    "tax": ("old vs new tax regime for me", "how can i save tax", "which tax regime is better"),
    "goal": ("am i on track for my goal", "how much do i need for my goal", "plan my goals"),
    "budget": ("help me plan my monthly budget", "how do i save more money", "where can i cut my expenses"),
    "loan": ("how much emi can i pay", "should i prepay my loan", "home loan emi calculator"),
    "market": ("how is nifty doing today", "what is happening in the stock market", "how is sensex today"),
    "equity_research": ("equity research report on reliance", "valuation of tcs", "investment thesis for infosys"),
    "company_intelligence": ("company intelligence score for infosys", "management tone of tcs", "red flags in reliance"),
    "stock_price": ("what is the stock price of tcs", "share price of hdfc bank", "market cap of itc"),
    "tutor": ("what is compound interest", "explain sip to me", "what is an expense ratio"),
    "quiz": ("quiz me on mutual funds", "teach me about sip", "test me on tax"),
    "mutual_fund": ("which mutual fund is good for me", "how do mutual funds work", "is elss a good investment"),
    "insurance": ("how much term insurance do i need", "do i need health insurance", "what is a term plan"),
    "investing": ("where should i invest my savings", "how do i start investing", "how to build a portfolio"),
}
_EXAMPLES = [p for ps in INTENT_EXAMPLES.values() for p in ps]


def suggest(text: str, n: int = 3) -> list[str]:
    """Canonical phrases the query resembles (difflib ratio >= 0.75, conservative so real questions are not hijacked): a 'did you mean' for queries no keyword router recognised."""
    return difflib.get_close_matches(text.lower().strip(" ?.!"), _EXAMPLES, n=n, cutoff=0.75)
