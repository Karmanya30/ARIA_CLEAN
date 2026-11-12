from modules.qa import trust


def test_general_answer_with_figures_gets_the_unverified_note():
    resp = {"domain": "general", "query": "tell me about savings accounts",
            "response": "Most savings accounts pay about 3% a year, and some banks need a balance of Rs 10,000.",
            "grounding": {"numbers_checked": False, "passed": True, "fallback": False, "unavailable": []}}
    assert trust.UNVERIFIED_NOTE in trust.finalize(resp)["response"]


def test_figures_the_user_gave_or_no_figures_get_no_note():
    plain = {"domain": "general", "query": "hello", "response": "Savings accounts keep your money safe and easy to reach every day.",
             "grounding": {"numbers_checked": False}}
    assert trust.UNVERIFIED_NOTE not in trust.finalize(plain)["response"]
    asked = {"domain": "general", "query": "what is 5% of 200 rupees", "response": "5% of 200 rupees is 10 rupees, because five percent is one twentieth.",
             "grounding": {"numbers_checked": False}}
    assert trust.UNVERIFIED_NOTE not in trust.finalize(asked)["response"]
