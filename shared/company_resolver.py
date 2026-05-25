"""
shared/company_resolver.py

Maps natural language company names / aliases to screener.in URL slugs.
"""
from __future__ import annotations

# Map of lowercase aliases → screener.in slug
_COMPANY_MAP: dict[str, str] = {
    # ICICI
    "icici bank": "ICICIBANK",
    "icici": "ICICIBANK",
    "icicibank": "ICICIBANK",
    # HDFC
    "hdfc bank": "HDFCBANK",
    "hdfc": "HDFCBANK",
    "hdfcbank": "HDFCBANK",
    # Reliance
    "reliance": "RELIANCE",
    "reliance industries": "RELIANCE",
    "ril": "RELIANCE",
    # TCS
    "tcs": "TCS",
    "tata consultancy": "TCS",
    "tata consultancy services": "TCS",
    # Infosys
    "infosys": "INFY",
    "infy": "INFY",
    # Wipro
    "wipro": "WIPRO",
    # SBI
    "sbi": "SBIN",
    "state bank of india": "SBIN",
    "state bank": "SBIN",
    # Tata Motors
    "tata motors": "TATAMOTORS",
    "tatamotors": "TATAMOTORS",
    # ITC
    "itc": "ITC",
    # Adani
    "adani": "ADANIENT",
    "adani enterprises": "ADANIENT",
    # Maruti
    "maruti": "MARUTI",
    "maruti suzuki": "MARUTI",
    # Asian Paints
    "asian paints": "ASIANPAINT",
    "asianpaints": "ASIANPAINT",
    # Axis Bank
    "axis bank": "AXISBANK",
    "axisbank": "AXISBANK",
    # Bajaj Finance
    "bajaj finance": "BAJFINANCE",
    "bajfinance": "BAJFINANCE",
    # Kotak
    "kotak": "KOTAKBANK",
    "kotak mahindra": "KOTAKBANK",
    "kotak bank": "KOTAKBANK",
    # HUL
    "hul": "HINDUNILVR",
    "hindustan unilever": "HINDUNILVR",
    "hindustan lever": "HINDUNILVR",
    # Bharti Airtel
    "airtel": "BHARTIARTL",
    "bharti airtel": "BHARTIARTL",
    # L&T
    "l&t": "LT",
    "larsen and toubro": "LT",
    "larsen & toubro": "LT",
    # ONGC
    "ongc": "ONGC",
    # NTPC
    "ntpc": "NTPC",
    # PowerGrid
    "power grid": "POWERGRID",
    # Sun Pharma
    "sun pharma": "SUNPHARMA",
    "sunpharma": "SUNPHARMA",
    # Tech Mahindra
    "tech mahindra": "TECHM",
    "techm": "TECHM",
    # Nestle
    "nestle": "NESTLEIND",
    "nestle india": "NESTLEIND",
    # Titan
    "titan": "TITAN",
}


def resolve_company(text: str) -> str | None:
    """
    Given a user's natural language query or company mention, return
    the screener.in slug.

    Priority:
    1. Exact alias match (case-insensitive)
    2. Longest substring alias match
    3. None if no match found
    """
    text_lower = text.lower()

    # Direct exact match
    if text_lower in _COMPANY_MAP:
        return _COMPANY_MAP[text_lower]

    # Longest substring match — avoids short aliases like "sbi" matching "sbi life"
    best_match: str | None = None
    best_len = 0
    for alias, ticker in _COMPANY_MAP.items():
        if alias in text_lower and len(alias) > best_len:
            best_match = ticker
            best_len = len(alias)

    return best_match
