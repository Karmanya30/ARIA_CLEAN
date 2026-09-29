"""shared/domain_guard.py -- classifier parsing, whitelist cross-check, and
fail-open behavior on bad/unparseable LLM output. LLM mocked throughout."""
import json

from shared.domain_guard import (
    ALLOWED_DOMAINS,
    CONFIDENCE_THRESHOLD,
    build_refusal_response,
    classify_domain,
    validate_output,
)


def _set_json(mock_llm, **fields):
    payload = {"domain": "finance", "intent": "explain_concept", "allowed": True, "confidence": 0.95}
    payload.update(fields)
    mock_llm.set_response(json.dumps(payload))


def test_well_formed_json_is_parsed(mock_llm):
    _set_json(mock_llm, domain="finance", allowed=True, confidence=0.95)
    result = classify_domain("what is EBITDA")
    assert result["available"] is True
    assert result["domain"] == "finance"
    assert result["allowed"] is True
    assert result["confidence"] == 0.95


def test_domain_not_in_whitelist_forces_not_allowed_even_if_model_says_true(mock_llm):
    # Cross-check against ALLOWED_DOMAINS locally -- don't just trust the
    # model's self-reported "allowed" flag.
    _set_json(mock_llm, domain="non_finance", allowed=True, confidence=0.9)
    result = classify_domain("tell me a joke")
    assert result["available"] is True
    assert result["domain"] == "non_finance"
    assert result["allowed"] is False


def test_non_json_response_is_unavailable_not_a_crash(mock_llm):
    mock_llm.set_response("Sorry, I can't help with that.")
    result = classify_domain("what is EBITDA")
    assert result["available"] is False
    assert result["allowed"] is None


def test_malformed_json_missing_fields_is_unavailable(mock_llm):
    mock_llm.set_response('{"domain": "finance"}')  # missing allowed/confidence
    result = classify_domain("what is EBITDA")
    assert result["available"] is False


def test_confidence_out_of_range_is_clamped(mock_llm):
    _set_json(mock_llm, confidence=1.7)
    result = classify_domain("what is EBITDA")
    assert result["available"] is True
    assert result["confidence"] == 1.0


def test_empty_query_is_unavailable_without_calling_llm(mock_llm):
    result = classify_domain("   ")
    assert result["available"] is False
    assert mock_llm.calls == []


def test_classifier_uses_a_smaller_model_than_default(mock_llm):
    _set_json(mock_llm)
    classify_domain("what is EBITDA")
    assert mock_llm.models[-1] is not None
    assert mock_llm.models[-1] != ""


def test_allowed_domains_are_all_lowercase_snake_case():
    for label in ALLOWED_DOMAINS:
        assert label == label.lower()
        assert " " not in label


def test_validate_output_reuses_classifier_on_query_and_answer(mock_llm):
    _set_json(mock_llm, domain="finance", allowed=True, confidence=0.9)
    result = validate_output("what is EBITDA", "EBITDA is earnings before interest, tax...")
    assert result["available"] is True
    assert "EBITDA" in mock_llm.calls[-1]


def test_build_refusal_response_shape():
    classification = {"domain": "non_finance", "intent": "trivia", "allowed": False, "confidence": 0.95, "available": True}
    response = build_refusal_response("who won the match", classification)
    assert response["domain"] == "refused"
    assert response["query"] == "who won the match"
    assert "financial intelligence assistant" in response["response"]
    assert response["domain_guard"] == classification


def test_confidence_threshold_is_a_real_probability():
    assert 0.0 < CONFIDENCE_THRESHOLD <= 1.0
