import pytest
from modules.qa.safeguards import generic_company_request
from ai.llm.groq_client import normalize_currency
from modules.market.pipeline import grounded_market_text

@pytest.mark.parametrize('text', ['Oil is $75 per barrel and USD 0.50 higher.', '100 dollars and 25 cents', 'USD/INR at 83 rupees per dollar'])
def test_currency_never_relabels_units(text):
    assert normalize_currency(text) == text

@pytest.mark.parametrize('text', ["Can you analyse a company's financial fundamentals?", 'Analyse any company financials'])
def test_generic_company_requires_entity(text):
    assert generic_company_request(text)

@pytest.mark.parametrize('text', ['Analyse a company named Infosys', 'Analyse this company', 'Analyse Infosys fundamentals'])
def test_specific_company_not_generic(text):
    assert not generic_company_request(text)

def test_freshness_contradiction_fails_closed():
    text, fallback = grounded_market_text('Today Nifty rose.', {'nifty': {'index': 'Nifty', 'as_of': '2026-10-29', 'current_level': 22000}})
    assert fallback and '2026-10-29' in text and '22000 index points' in text
    assert 'Today' not in text

def test_foreign_units_cannot_be_relabelled():
    text, fallback = grounded_market_text('Oil is 75 rupees.', {'news': ['Oil at $75 per barrel']})
    assert fallback and '75 rupees' not in text

def test_grounded_educational_market_text_preserved():
    answer = 'The dated snapshot shows a rise. Rates can influence markets.'
    assert grounded_market_text(answer, {}) == (answer, False)


@pytest.mark.parametrize('text', ["Analyse a company's financial fundamentals for Reliance", "Analyse a company's financial fundamentals for Apple", "Analyse a company's financials for me"])
def test_entity_provided_is_not_mistaken_for_generic_request(text):
    if text.endswith('for me'):
        assert generic_company_request(text)
    else:
        assert not generic_company_request(text)
