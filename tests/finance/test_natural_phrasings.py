import pytest

from modules.finance.pipeline import finance_intent


@pytest.mark.parametrize("q,tool", [
    ("I want to save 1 crore in 15 years", "goal"),
    ("I need 50 lakh in 10 years for my daughter's education", "goal"),
    ("how am I doing financially?", "health"),
    ("is my emergency fund enough?", "health"),
    ("how many months of expenses do I have saved", "health"),
])
def test_natural_phrasings_reach_the_engine(q, tool):
    hit = finance_intent(q)
    assert hit and hit[0] == tool
