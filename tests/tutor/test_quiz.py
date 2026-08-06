"""Quiz engine parser -- LLM mocked where relevant."""
from modules.tutor.quiz import _parse_quiz_text, generate_quiz, grade
from modules.tutor.schemas import QuizItem


def test_parse_well_formed_quiz():
    text = (
        "QUESTION: What does SIP stand for?\n"
        "CORRECT: Systematic Investment Plan\n"
        "WRONG_1: Simple Interest Plan\n"
        "WRONG_2: Stock Investment Program\n"
        "WRONG_3: Savings Interest Plan\n"
        "EXPLANATION: SIP is a regular mutual fund investment method."
    )
    item = _parse_quiz_text(text, "sip")
    assert item is not None
    assert item.question == "What does SIP stand for?"
    assert item.correct_answer == "Systematic Investment Plan"
    assert len(item.wrong_answers) == 3
    assert item.concept_id == "sip"


def test_parse_malformed_quiz_returns_none_not_crash():
    assert _parse_quiz_text("I don't know.", "sip") is None


def test_generate_quiz_uses_mocked_llm(mock_llm):
    mock_llm.set_response(
        "QUESTION: Q?\nCORRECT: A\nWRONG_1: B\nWRONG_2: C\nWRONG_3: D\nEXPLANATION: because."
    )
    item = generate_quiz("Compound Interest", "compound_interest", level=2)
    assert item is not None
    assert item.correct_answer == "A"


def test_grade_is_case_insensitive():
    item = QuizItem(
        question="Q?", correct_answer="Systematic Investment Plan",
        wrong_answers=["A", "B", "C"], explanation="e", concept_id="sip",
    )
    assert grade(item, "systematic investment plan") is True
    assert grade(item, "wrong answer") is False
