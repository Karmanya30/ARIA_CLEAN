"""UV-001: the user's own question must be in the narration prompt (it used to be dropped, so every question got the same summary)."""
from modules.finance.pipeline import run_pipeline
from shared import user_store

_USER = "__pytest_question_prompt__"


def test_the_question_is_part_of_the_narration_prompt(mock_llm):
    user_store.clear_transactions(_USER)
    user_store.delete_financial_profile(_USER)
    try:
        run_pipeline("I earn 80000 a month, what is my risk profile", user_id=_USER)
    finally:
        user_store.clear_transactions(_USER)
        user_store.delete_financial_profile(_USER)
    narration = [c for c in mock_llm.calls if "COMPUTED DATA" in c]
    assert narration, "the narration prompt was not built"
    assert all("USER QUESTION" in c and "what is my risk profile" in c for c in narration)
