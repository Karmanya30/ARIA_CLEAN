"""shared/intent_classifier.py -- coarse M1 (finance) vs M2 (tutor) bucket.

Found broken via live UI testing: the app's own suggested example prompt
"Quiz me on mutual funds" was misrouted to Module 1 (finance) because
FINANCE_KEYWORDS' "mutual fund" matched before TUTOR_KEYWORDS was ever
checked -- Module 1 then hallucinated quiz-shaped text in its narration
instead of the query ever reaching Module 2's real quiz engine."""
from shared.intent_classifier import classify_intent


def test_quiz_me_on_finance_topic_routes_to_tutor():
    assert classify_intent("Quiz me on mutual funds") == "tutor"


def test_teach_me_on_finance_topic_routes_to_tutor():
    assert classify_intent("Teach me about SIPs") == "tutor"


def test_explain_to_me_routes_to_tutor():
    assert classify_intent("Explain to me how compound interest works") == "tutor"


def test_ambiguous_personal_finance_query_still_routes_to_finance():
    # Unchanged precedence: "what is my risk profile" is a question about
    # the user's own computed data, not a request to be taught a concept.
    assert classify_intent("what is my risk profile") == "finance"


def test_plain_concept_question_still_routes_to_tutor():
    assert classify_intent("What is compound interest?") == "tutor"


def test_plain_finance_query_still_routes_to_finance():
    assert classify_intent("I earn 60000 a month, what SIP should I start") == "finance"
