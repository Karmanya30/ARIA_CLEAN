"""modules/equity_research/beginner_screener.py

build_suggestions_prompt is pure string-building (no network) and tested
directly. beginner_friendly_candidates/top_recent_performers hit real
yfinance -- same untested-mock convention the rest of this codebase's
market/equity-research tests already accept (e.g.
modules/market/analyzer.py's get_index_snapshot is exercised the same way
via tests/test_adversarial.py's multi-intent case), so these just assert
well-formed output rather than exact values."""
from modules.equity_research.beginner_screener import (
    UNIVERSE,
    beginner_friendly_candidates,
    build_suggestions_prompt,
    top_recent_performers,
)


def test_universe_is_a_real_nonempty_deduped_ticker_list():
    assert UNIVERSE
    assert len(UNIVERSE) == len(set(UNIVERSE))
    assert all(ticker.endswith((".NS", ".BO")) for ticker in UNIVERSE)


def test_beginner_friendly_candidates_returns_well_formed_list():
    result = beginner_friendly_candidates(limit=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    for item in result:
        assert item["ticker"] in UNIVERSE
        assert item["market_cap"]


def test_top_recent_performers_returns_well_formed_ranked_list():
    result = top_recent_performers(limit=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    changes = [item["change_pct"] for item in result]
    assert changes == sorted(changes, reverse=True)


def test_suggestions_prompt_states_it_is_not_personalized_advice():
    prompt = build_suggestions_prompt(
        beginner_list=[{"ticker": "TCS.NS", "company_name": "TCS", "market_cap": "Rs 14 lakh crore", "pe_ratio": 28}],
        performers_list=[{"ticker": "INFY.NS", "company_name": "INFY", "change_pct": 5.2}],
        performance_window="1 month",
    )
    assert "NOT a personal recommendation" in prompt
    assert "does not predict future performance" in prompt
    assert "TCS.NS" in prompt
    assert "INFY.NS" in prompt
    assert "5.20%" in prompt


def test_suggestions_prompt_handles_empty_lists_gracefully():
    prompt = build_suggestions_prompt(beginner_list=[], performers_list=[], performance_window="1 month")
    assert "No live data available right now." in prompt
