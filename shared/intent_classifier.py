"""Lightweight keyword intent classifier."""

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
    "p/e",
    "pe ratio",
    "p e ratio",
    "price earnings",
    "valuation",
    "earnings",
    "dividend",
    "share",
    "equity",
    "nse",
    "bse",
)
MARKET_KEYWORDS = (
    "stock",
    "share",
    "analyze",
    "analysis",
    "trend",
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
TUTOR_KEYWORDS = ("learn", "explain", "what is")


def classify_intent(query: str) -> str:
    text = query.lower()

    if any(keyword in text for keyword in FINANCE_KEYWORDS):
        return "finance"
    if any(keyword in text for keyword in MARKET_KEYWORDS):
        return "market"
    if any(keyword in text for keyword in TUTOR_KEYWORDS):
        return "tutor"
    return "general"


class IntentClassifier:
    def predict(self, text: str) -> str:
        return classify_intent(text)
