"""Accuracy regressions do not restrict research or investment features."""
import pytest

from ai.llm.groq_client import normalize_currency
from modules.market.pipeline import grounded_market_text
from modules.qa.safeguards import generic_company_request


@pytest.mark.parametrize('text', ['Oil is $116 per barrel.', 'A price of USD 10 and ₹830.', 'It costs 50 cents.'])
def test_currency_units_are_never_relabelled_without_conversion(text):
    assert normalize_currency(text) == text


def test_market_fallback_keeps_concept_explanation_and_replaces_stale_claim():
    answer = 'Nifty 50 tracks 50 NSE stocks. Sensex tracks 30 BSE stocks. Today Nifty rose.'
    context = {'query': 'Explain the difference between Nifty and Sensex', 'nifty': {'index': 'Nifty', 'as_of': '2026-10-29', 'current_level': 22936.75, 'today_change_pct': 1.05}}
    result, fallback = grounded_market_text(answer, context)
    assert fallback
    assert 'Nifty 50 tracks 50 NSE stocks.' in result
    assert 'Sensex tracks 30 BSE stocks.' in result
    assert 'Today Nifty rose.' not in result
    assert '2026-10-29' in result and '22936.75' in result


def test_foreign_currency_source_does_not_remove_unrelated_context():
    answer = 'Global oil costs affect transport. Oil is 116 rupees per barrel.'
    result, fallback = grounded_market_text(answer, {'query': 'Explain how oil prices affect markets', 'news': ['Oil is $116 per barrel']})
    assert fallback
    assert 'Global oil costs affect transport.' in result
    assert '116 rupees' not in result


def test_market_driver_fallback_does_not_keep_unsupported_causal_claims():
    text = 'Foreign inflows caused the rally. Today Nifty rose.'
    result, fallback = grounded_market_text(text, {'query': "What factors influence today's market?"})
    assert fallback and 'caused the rally' not in result


def test_driver_query_detects_unsupported_driven_by_even_without_today_word():
    text = 'The market is driven mainly by foreign inflows.'
    result, fallback = grounded_market_text(text, {'query': 'What factors influence the market?'})
    assert fallback and 'driven mainly by' not in result


def test_valid_dated_explanation_is_left_unchanged():
    text = 'Nifty 50 represents fifty NSE stocks; Sensex represents thirty BSE stocks.'
    assert grounded_market_text(text, {}) == (text, False)


@pytest.mark.parametrize('text', ["Can you analyse a company's financial fundamentals?", 'Can you analyse a company for me?'])
def test_generic_company_request_asks_for_entity(text):
    assert generic_company_request(text)


@pytest.mark.parametrize('text', ["Analyse a company's financial fundamentals for Reliance", "Analyse a company's financials for Apple", 'Analyse this company and its financials'])
def test_named_company_or_existing_focus_is_not_indefinite(text):
    assert not generic_company_request(text)


@pytest.mark.parametrize('focus_context', [{'company': 'Reliance'}, {'instrument_id': 'stock:RELIANCE.NS'}])
def test_generic_company_question_keeps_active_company_focus(monkeypatch, focus_context):
    from core import orchestrator
    from modules.qa.models import Focus, QAContext, active_focus
    monkeypatch.setattr(orchestrator, 'dialogue_act', lambda query: 'test-route')
    monkeypatch.setattr(orchestrator, '_dialogue_reply', lambda query, kind, session_id: {'domain': 'continued'})
    token = active_focus.set(Focus(context=QAContext(**focus_context)))
    try:
        result = orchestrator._handle_query("Can you analyse a company's financial fundamentals?", session_id='focus-test', correct=False)
    finally:
        active_focus.reset(token)
    assert result['domain'] == 'continued'
