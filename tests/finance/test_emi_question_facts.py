from modules.finance.pipeline import _regex_facts


def test_loan_amount_in_an_emi_question_is_not_the_users_emi():
    assert "existing_emi" not in _regex_facts("What would be the EMI on a 10 lakh loan at 9% for 5 years?")
    assert "existing_emi" not in _regex_facts("Calculate EMI for 1000000 loan")


def test_stated_emi_is_still_remembered():
    assert _regex_facts("my EMI is 12000 and I earn 60000")["existing_emi"] == 12000
