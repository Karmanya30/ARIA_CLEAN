from modules.equity_research.investment import detect_company


def test_finance_acronyms_are_not_taken_for_tickers():
    assert detect_company("What is the PE ratio of ITC?")["ticker"] == "ITC.NS"
    assert detect_company("price of RELIANCE")["ticker"] == "RELIANCE.NS"
