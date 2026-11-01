"""One regression case for each of the 12 baseline questions that used to fall through to the general model with no data
(evaluation/intent_understanding/results/fallthrough_12.txt), plus the false-positive guards. Rule layer only: no model, no network."""
import pytest

from core import orchestrator
from core.router import decision_without_subject, is_finance_concept_question
from modules.qa import lookup
from shared.understand import normalize


@pytest.mark.parametrize("query,label", [
    ("kitna kharch hua food pe", "finance"),                                        # Hinglish spending question
    ("markets kaisa chal raha hai aaj", "market"),                                  # Hinglish market question
    ("compare it with TCS", "equity_research"),                                     # comparison naming a company
    ("how much do I need monthly to reach 1 crore in 20 years", "finance"),         # goal calculation
    ("I earn 80k and spend 50k, how much can I save", "finance"),                   # first-person money question with abbreviations
    ("dollar vs rupee today", "market"),                                            # currency macro
])
def test_rules_now_place_the_question(query, label):
    assert orchestrator._rule_label(normalize(query)[0]) == label


@pytest.mark.parametrize("query", ["what does NAV mean", "define asset allocation"])
def test_finance_concepts_go_to_the_tutor(query):
    assert is_finance_concept_question(normalize(query)[0])


@pytest.mark.parametrize("query", ["sell everything now?", "should I sell it", "buy now"])
def test_a_decision_with_nothing_to_decide_about_is_asked_about(query):
    assert decision_without_subject(query)


@pytest.mark.parametrize("query", ["How did Bitcoin, Ethereum and gold do this month", "Kaynes ka revenue kitna hai?"])
def test_named_data_questions_reach_the_lookup(query):
    n = normalize(query)[0]
    assert lookup.is_data_question(n) and lookup._has_proper_noun(query)


@pytest.mark.parametrize("query", ["I spend hours coding in python", "what is photosynthesis", "what does the word mean in french",
                                   "should I sell my mutual funds, they are doing bad", "hold on a second", "what is my SIP worth"])
def test_no_false_positives(query):
    n = normalize(query)[0]
    assert not decision_without_subject(query) and not is_finance_concept_question(n)
    assert orchestrator._rule_label(n) in (None, "tutor", "finance")  # never a company, market or lookup route
    if "coding" in query or "hold on" in query:
        assert orchestrator._rule_label(n) is None


def test_the_no_evidence_gate_never_invents_a_figure(monkeypatch):
    monkeypatch.setattr(lookup, "find_instrument", lambda *t: None)
    monkeypatch.setattr(lookup, "web_answer", lambda q, why: None)
    r = lookup.data_answer("What is the PE ratio of Zorblax Industries", "What is the PE ratio of Zorblax Industries", "o", None)
    assert r["gate"] == "no_evidence" and "won't guess" in r["response"] and not any(c.isdigit() for c in r["response"])


def test_a_common_english_word_is_not_a_company_name(monkeypatch):
    """Found by the faithful benchmark stub: "what is a bond yield" matched Bondada Engineering and "intraday trading tips" matched Tips Music."""
    from modules.market import instruments as I

    hit = {"id": "stock:X.BO", "name": "Bondada Engineering Limited", "symbol": "X.BO", "type": "stock"}
    monkeypatch.setattr(I, "search", lambda q, limit=5: {"items": [hit]})
    assert lookup.find_instrument("what is a bond yield") is None
    assert lookup.find_instrument("What is the price of Bondada Engineering") == hit        # a several-word name is specific
    monkeypatch.setattr(I, "search", lambda q, limit=5: {"items": [{**hit, "name": "Kaynes Technology India Limited", "symbol": "KAYNES.NS"}]})
    assert lookup.find_instrument("kaynes revenue") is not None                              # an uncommon single word is a believable name
    monkeypatch.setattr(I, "search", lambda q, limit=5: {"items": [{"id": "commodity:SI=F", "name": "Silver", "symbol": "SI=F", "type": "commodity"}]})
    assert lookup.find_instrument("silver performance this year") is not None                # commodities are named by common words
