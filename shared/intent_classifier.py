"""Lightweight keyword intent classifier with word boundaries."""

import re

FINANCE_KEYWORDS = (
    "sip",
    "spi",
    "systematic investment plan",
    "mutual fund",
    "investment",
    "invest",
    "portfolio",
    "tax",
    "budget",
    "emi",
    "income",
    "expense",
    "saving",
    "savings",
    "risk profile",
    "afford",
    "affordability",
    "financial plan",
    "financial planning",
    "car loan",
    "home loan",
    "p/e",
    "pe ratio",
    "p e ratio",
    "price earnings",
    "valuation",
    "earnings",
    "dividend",
    "equity",
    "nse",
    "bse",
)
MARKET_KEYWORDS = (
    "stock",
    "market analysis",
    "market cap",
    "tata motors",
    "reliance",
    "tcs",
    "infosys",
    "hdfc bank",
    "icici bank",
    "sbi",
    "itc",
    "adani",
    "wipro",
    "maruti",
    "asian paints",
    "axis bank",
)
TUTOR_KEYWORDS = (
    "learn", "explain", "what is",
    # Company/business/management/consultancy terms -- in-scope for ARIA
    # even when they don't hit a finance/market keyword above, so they get
    # the finance/business-framed prompt path rather than being misrouted.
    "company", "companies", "business", "management", "consultancy",
    "consulting", "corporate", "startup", "start-up", "entrepreneur",
    "entrepreneurship", "merger", "acquisition", "strategy", "ceo", "cfo",
    "industry", "enterprise", "firm",
)

# Unambiguous "teach/test me" phrasing -- checked before FINANCE_KEYWORDS
# because the tutor module's own subject matter (SIP, mutual funds, tax,
# dividends, ...) inherently overlaps with finance vocabulary. Without this,
# "Quiz me on mutual funds" matched FINANCE_KEYWORDS' "mutual fund" and was
# misrouted to Module 1 (which has no real quiz engine and just hallucinated
# quiz-shaped text in its narration) instead of Module 2's actual quiz flow.
_STRONG_TUTOR_PHRASES = ("quiz me", "teach me", "explain to me", "test me on")


def _contains(text: str, phrase: str) -> bool:
    # A taxi is not tax; a spaceship is not SIP; a firmament is not a firm.
    endings = {"invest": r"invest(?:s|ed|ing|ments?)?", "saving": r"savings?",
               "expense": r"expenses?", "tax": r"tax(?:es|ation|able)?",
               "stock": r"stocks?", "company": r"compan(?:y|ies)", "learn": r"learn(?:ing)?",
               "mutual fund": r"mutual\s+funds?", "dividend": r"dividends?", "sip": r"sips?",
               "emi": r"emis?", "portfolio": r"portfolios?", "equity": r"equit(?:y|ies)"}
    expression = endings.get(phrase, re.escape(phrase).replace(r"\ ", r"\s+"))
    return bool(re.search(r"(?<!\w)" + expression + r"(?!\w)", text))


def classify_intent(query: str) -> str:
    text = query.lower()

    if any(_contains(text, phrase) for phrase in _STRONG_TUTOR_PHRASES):
        return "tutor"
    if any(_contains(text, keyword) for keyword in FINANCE_KEYWORDS):
        return "finance"
    if any(_contains(text, keyword) for keyword in MARKET_KEYWORDS):
        return "market"
    if any(_contains(text, keyword) for keyword in TUTOR_KEYWORDS):
        return "tutor"
    return "general"


class IntentClassifier:
    def predict(self, text: str) -> str:
        return classify_intent(text)
