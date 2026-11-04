"""Formulas reach the screen, the saved history and the voice as plain text, never as LaTeX code."""
from api.text_utils import plain_math


def test_the_etf_answer_that_showed_raw_latex():
    raw = "Simple formula:\n\\[ \\text{Total Cost} = \\text{ETF Price per Unit} \\times n \\]\nUsing the example: \\[ \\text{Total Cost} = ₹1,200 \\times 5 = ₹6,000 \\]."
    out = plain_math(raw)
    assert "Total Cost = ETF Price per Unit × n" in out and "Total Cost = ₹1,200 × 5 = ₹6,000" in out
    assert "\\" not in out and "[" not in out


def test_brackets_left_behind_after_the_backslashes_were_eaten():
    assert plain_math("[ \\text{Total Cost} = \\text{Price} \\times n ]") == "Total Cost = Price × n"


def test_fractions_powers_and_symbols():
    assert plain_math("FV = P \\times \\frac{(1+r)^{n} - 1}{r}") == "FV = P × ((1+r)^n - 1)/(r)"
    assert plain_math("x^{2} \\times y^{n+1}") == "x^2 × y^(n+1)"
    assert plain_math("x^{2} and y^{n+1}") == "x^{2} and y^{n+1}"  # no LaTeX command: left alone
    assert plain_math("a \\approx b, c \\leq d, 5\\% of e") == "a ≈ b, c ≤ d, 5% of e"
    assert plain_math("\\sqrt{x}") == "sqrt(x)"


def test_ordinary_answers_are_not_touched():
    for text in ["A SIP of ₹5,000 for 10 years at 12% grows to about ₹11.6 lakh.", "Total = 1,200 × 5 = ₹6,000", "Use the [ENTER] key", "path C:\\temp\\new", "Cost is $5 and $10"]:
        assert plain_math(text) == text
