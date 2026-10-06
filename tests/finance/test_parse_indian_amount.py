"""_parse_indian_amount -- found broken for comma-formatted numbers via
live testing: Conversational Mode's follow-up-query rewrite runs through
the LLM, which writes amounts with thousands separators ("₹60,000"); the
old digits-only regex matched just "60" and silently truncated a real
income by 1000x, producing a nonsensical "budget infeasible" error from
figures that had quietly lost three zeros."""
from modules.finance.pipeline import _parse_indian_amount


def test_plain_number_still_works():
    assert _parse_indian_amount("I earn 60000 a month", "earn") == 60000.0


def test_western_comma_grouping():
    assert _parse_indian_amount("I earn 60,000 a month", "earn") == 60000.0


def test_indian_comma_grouping():
    assert _parse_indian_amount("my income is 1,25,000 per month", "income") == 125000.0


def test_comma_grouping_with_keyword():
    assert _parse_indian_amount("EMI of 12,500 a month", "emi") == 12500.0


def test_lakh_suffix_still_works():
    assert _parse_indian_amount("I earn 12 lakh a year", "earn") == 1_200_000.0


def test_plural_crore_suffix_works():
    assert _parse_indian_amount("my income is 2 crores a year", "income") == 20_000_000.0
