"""The routing taxonomy, derived from ARIA's actual modules (core/orchestrator.py), and the example utterances per route.

The labels are the module the orchestrator can hand a question to. They are NOT a free-form topic list: every label maps to code that
exists. Example utterances are written from the feature descriptions, independently of the benchmark queries (checked in
evaluation/intent_understanding/check_leakage.py). Tuning examples may only be added from the `dev` split.
"""
from __future__ import annotations

FINANCE, TUTOR, MARKET = "finance", "tutor", "market"
EQUITY, INTEL, LOOKUP = "equity_research", "company_intelligence", "data_lookup"
GENERAL, SMALLTALK, CLARIFY = "general", "smalltalk", "clarify"

# What each label runs in core/orchestrator.py (documentation + used by the graph's executor map)
CAPABILITY = {
    FINANCE: "modules.finance.pipeline (profile, transactions, SIP/EMI/tax/health engines)",
    TUTOR: "modules.tutor.pipeline (concept lesson, quiz, mastery)",
    MARKET: "modules.market.pipeline (indices, sectors, macro, news)",
    EQUITY: "modules.equity_research.pipeline (fundamentals, quote, research report)",
    INTEL: "modules.equity_research.intelligence (sentiment, management tone, red flags, score)",
    LOOKUP: "modules.qa.lookup (any listed name/fund/crypto/commodity, web-search fallback)",
    GENERAL: "general model reply with conversation memory",
    SMALLTALK: "short social reply",
    CLARIFY: "ask the user one question before running anything",
}

ROUTE_EXAMPLES: dict[str, list[str]] = {
    FINANCE: [
        "how much can I save every month from my salary", "am I saving enough for retirement", "can I afford this loan with my income",
        "help me plan my expenses for the month", "how healthy are my finances", "how much should I put into a SIP every month",
        "compare the old and new income tax regime for my pay", "should I prepay my home loan or invest the money",
        "look at my bank statement and find unusual spending", "what happens to my savings if my expenses go up",
        "how long until I reach my savings goal", "mera kharcha kitna ho raha hai is mahine", "is my emergency fund big enough",
        "work out how much I need to retire comfortably", "what if I earn ten percent more next year",
    ],
    TUTOR: [
        "teach me how mutual funds work", "explain the idea of compounding", "what does expense ratio mean", "quiz me on investing basics",
        "I want to learn about bonds", "explain the difference between equity and debt funds", "define diversification in simple words",
        "test my knowledge of tax saving", "explain XIRR to a beginner", "what is a SIP in simple terms",
        "how does inflation reduce purchasing power", "help me understand how the stock market works", "what is a fixed deposit and how does it earn",
        "give me an example to understand risk and return", "mujhe mutual fund samjhao",
    ],
    MARKET: [
        "how are the indices doing today", "why did the market fall", "which sectors are leading this week", "what is moving the Nifty",
        "how will interest rate decisions affect the stock market", "outlook for the market this week", "crude oil and rupee movement today",
        "foreign investor flows and market sentiment", "latest market news headlines", "levels of the bank index and the sensex",
        "how did equities react to the budget", "what is happening in global markets", "aaj market kaisa hai",
    ],
    EQUITY: [
        "price of a listed company's share", "analyse the fundamentals of this company", "give me a research report and valuation for this stock",
        "revenue and profit growth over the last five years", "is this stock overvalued compared to its peers", "debt and cash flow of the company",
        "compare two companies on profitability", "fair value estimate for the share", "quarterly results of the company",
        "return on equity and margins of the business", "how is this company's balance sheet", "what is the share price of a large bank",
    ],
    INTEL: [
        "management tone on the earnings call", "sentiment around the company in the news", "red flags in the company's disclosures",
        "company intelligence score", "highlights from the concall and management commentary", "governance concerns and promoter pledging",
        "news sentiment versus fundamentals for a company", "how positive or negative is the coverage of this firm",
    ],
    LOOKUP: [
        "net asset value of a mutual fund scheme", "current price of gold or silver", "bitcoin or ethereum price", "market cap of a small listed company",
        "52 week high and low of a stock", "dividend yield of a stock", "expense ratio and returns of a fund", "price of a commodity or a cryptocurrency",
        "latest NAV of an index fund", "what is the pe ratio of this company", "price of a small cap share",
    ],
    GENERAL: [
        "write me a poem", "tell me something funny", "what is the capital city of a country", "help me with some programming code",
        "a recipe for dinner tonight", "what is the weather like", "recommend a movie to watch", "translate this sentence into another language",
        "who won the match", "tell me a fact from history", "explain how a physical process works in science",
    ],
    SMALLTALK: [
        "hey hi", "hi there how are you", "thanks a lot", "what are you able to help with", "introduce yourself", "good morning", "bye for now", "how are you doing",
    ],
}
